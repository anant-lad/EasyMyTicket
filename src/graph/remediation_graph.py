"""
EasyMyTicket — Agentic Remediation Loop (Part 2)
=================================================
Runs server-side. Drives a multi-turn tool-call loop with the LLM where:
  - LLM reads the ticket and decides what diagnostic command to run next.
  - Command is sent to the user's machine via WebSocket (dispatch_tool_call).
  - LLM reads the output, reasons, decides the next step.
  - Loop continues until the LLM marks the issue as resolved (or max_steps hit).

Think of it as Claude Code in auto mode, but for IT remediation on the user's
machine. The desktop agent is the "terminal" — the LLM here is the "brain".

Entry point:
    from src.graph.remediation_graph import run_remediation_session
    await run_remediation_session(ticket_number, device_id, title, description, category)
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.database.db_connection import DatabaseConnection
from src.llm.provider import get_callbacks, get_llm
try:
    from agent.executor import list_available_commands
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from agent.executor import list_available_commands

log = logging.getLogger(__name__)

MAX_STEPS = 20       # hard cap per session
TOOL_TIMEOUT = 120   # seconds to wait for device response


# ─────────────────────────────────────────────────────────────────────────────
#  Tool definitions (sent to LLM so it knows what it can call)
# ─────────────────────────────────────────────────────────────────────────────

def _build_tool_definitions() -> list:
    """Return LangChain-compatible tool schemas for the remediation LLM."""
    cmds = list_available_commands()
    tier1_list = ", ".join(cmds["tier1_diagnostic"])
    tier2_list = ", ".join(cmds["tier2_fix"])
    web_note   = cmds.get("web_tools_note", "")

    return [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": (
                    "Run a diagnostic or fix command on the user's machine. "
                    "The result will be returned to you so you can reason about it.\n"
                    f"Tier-1 (diagnostic, always safe): {tier1_list}.\n"
                    f"Tier-2 (fix operations, use when confident): {tier2_list}.\n"
                    f"Web & download tools: {web_note}\n"
                    "For web_search pass args={{\"QUERY\": \"your search terms\"}}. "
                    "For download_file pass args={{\"URL\": \"https://...\", \"PATH\": \"/tmp/file.deb\"}}. "
                    "For install_from_file pass args={{\"PATH\": \"/tmp/file.deb\"}}. "
                    "For open_browser pass args={{\"URL\": \"https://...\"}}. "
                    "On Linux use CLI downloads (wget/curl) whenever possible. "
                    "On Windows/macOS, prefer direct download_file; fall back to open_browser "
                    "only when the site requires authentication or a CAPTCHA."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Command name from the tier1 or tier2 list above.",
                        },
                        "args": {
                            "type": "object",
                            "description": (
                                "Key-value substitutions for __ARG__ placeholders. "
                                "E.g. {\"SERVICE\": \"bluetoothd\", \"HOST\": \"8.8.8.8\"}."
                            ),
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "One sentence: why you are running this command now.",
                        },
                    },
                    "required": ["command", "reasoning"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_script",
                "description": (
                    "Execute a custom shell/PowerShell/Python script on the user's machine "
                    "for issues that cannot be solved with a named command. "
                    "Use only when named commands are insufficient. "
                    "Never include destructive operations (rm -rf /, format, etc.)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script": {
                            "type": "string",
                            "description": "The full script content to execute.",
                        },
                        "script_type": {
                            "type": "string",
                            "enum": ["bash", "powershell", "python"],
                            "description": "Script interpreter.",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Why a custom script is needed here.",
                        },
                    },
                    "required": ["script", "script_type", "reasoning"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finish",
                "description": "Mark the session as complete. Call when the issue is resolved or cannot be fixed autonomously.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "resolved": {
                            "type": "boolean",
                            "description": "True if the issue was fixed, False if escalation is needed.",
                        },
                        "explanation": {
                            "type": "string",
                            "description": "Plain-English explanation for the user of what was found and done.",
                        },
                        "escalation_reason": {
                            "type": "string",
                            "description": "If resolved=False, explain why and what the technician should do.",
                        },
                    },
                    "required": ["resolved", "explanation"],
                },
            },
        },
    ]


_TOOLS = _build_tool_definitions()


def _build_auto_tool_definitions() -> list:
    """Tool definitions for auto mode — full unrestricted system access."""
    cmds = list_available_commands()
    tier1_list = ", ".join(cmds["tier1_diagnostic"])
    tier2_list = ", ".join(cmds["tier2_fix"])

    return [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": (
                    "Run a named diagnostic or fix command on the user's machine.\n"
                    f"Tier-1 (read-only): {tier1_list}.\n"
                    f"Tier-2 (fix): {tier2_list}.\n"
                    "In auto mode all commands run immediately with no approval gate."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command":   {"type": "string", "description": "Command name."},
                        "args":      {"type": "object", "description": "Substitution args."},
                        "reasoning": {"type": "string", "description": "Why you are running this."},
                    },
                    "required": ["command", "reasoning"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shell",
                "description": (
                    "Run any shell command on the user's machine. "
                    "Linux/macOS: bash. Windows: PowerShell. "
                    "Use for anything not covered by named commands."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command":   {"type": "string", "description": "Full shell command to execute."},
                        "reasoning": {"type": "string", "description": "Why this command is needed."},
                    },
                    "required": ["command", "reasoning"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the full contents of any file on the user's machine.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":      {"type": "string", "description": "Absolute path to the file."},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["path", "reasoning"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write (overwrite) a file on the user's machine. Creates parent dirs automatically.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":      {"type": "string", "description": "Absolute path to write."},
                        "content":   {"type": "string", "description": "Full file content."},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["path", "content", "reasoning"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_dir",
                "description": "List files and directories at a path on the user's machine.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":      {"type": "string", "description": "Directory path."},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["path", "reasoning"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "download",
                "description": "Download a file from a URL to a path on the user's machine.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url":       {"type": "string", "description": "URL to download."},
                        "path":      {"type": "string", "description": "Destination path on the machine."},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["url", "path", "reasoning"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for drivers, error messages, fix procedures, package names.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":     {"type": "string", "description": "Search query."},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["query", "reasoning"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_script",
                "description": "Execute a multi-line bash/PowerShell/Python script on the user's machine.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script":      {"type": "string", "description": "Script content."},
                        "script_type": {"type": "string", "enum": ["bash", "powershell", "python"]},
                        "reasoning":   {"type": "string"},
                    },
                    "required": ["script", "script_type", "reasoning"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finish",
                "description": "Mark the session complete when the issue is resolved or cannot be fixed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "resolved":          {"type": "boolean"},
                        "explanation":       {"type": "string"},
                        "escalation_reason": {"type": "string"},
                    },
                    "required": ["resolved", "explanation"],
                },
            },
        },
    ]


_AUTO_TOOLS = _build_auto_tool_definitions()

_AUTO_SYSTEM_PROMPT = """You are an expert IT support engineer with FULL autonomous access to the user's machine.
The user has enabled AUTO MODE — you can run any command, read/write any file, download tools, and modify system config.
Your goal: diagnose and completely fix the reported issue without any human approval.

You have these tools:
- shell(command)          — run any bash/PowerShell command
- read_file(path)         — read any file
- write_file(path,content)— write/create any file
- list_dir(path)          — browse the filesystem
- download(url, path)     — download files from the internet
- web_search(query)       — search the web for fixes, drivers, packages
- run_script(script, type)— run multi-line bash/PowerShell/Python scripts
- run_command(command)    — use named diagnostic/fix commands

Workflow:
1. DIAGNOSE — gather evidence before acting (shell, read_file, named diagnostics)
2. SEARCH   — web_search for the exact error or fix procedure if needed
3. FIX      — apply the fix directly (no approval needed in auto mode)
4. VERIFY   — confirm the fix worked with a follow-up check
5. FINISH   — call finish() with a plain-English explanation

Rules:
- Prefer targeted fixes over broad ones (fix one service, not reinstall the OS)
- Always verify before finishing
- If 3 fix attempts fail, escalate with a clear explanation
- Keep finish() explanation in plain English for the user
- You have {max_steps} total steps — use them wisely

User's machine OS: {os}
"""


# ─────────────────────────────────────────────────────────────────────────────
#  System prompt
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an expert IT support engineer with remote access to the user's machine.
Your job is to diagnose and fix the reported issue autonomously — like running Claude Code in auto mode.

Workflow:
1. READ the ticket carefully. Think about what could cause the issue.
2. DIAGNOSE: run diagnostic (Tier-1) commands to gather evidence. Start broad, then narrow down.
3. UNDERSTAND: reason about each command output before the next step.
4. PLAN: once you understand the root cause, decide on the fix.
5. FIX: execute Tier-2 fix commands. Prefer targeted fixes over broad ones.
6. VERIFY: re-run the relevant diagnostic to confirm the fix worked.
7. FINISH: call finish() with a clear explanation for the user.

Web search & download capabilities:
- Use web_search(QUERY) to find driver names, package names, download URLs, or fix procedures.
  Example: web_search(QUERY="ubuntu 22.04 uvcvideo camera driver fix")
- Use check_url(URL) to verify a download link is reachable.
- Use download_file(URL, PATH) to download drivers, packages, or tools to the device.
  On Linux: always prefer CLI downloads (wget/curl via download_file) over open_browser.
  On Windows/macOS: use download_file for direct links; use open_browser only when the
  download requires authentication or a CAPTCHA that cannot be bypassed programmatically.
- Use install_from_file(PATH) to install a downloaded .deb/.rpm/.pkg/.exe/.msi.
- Use open_browser(URL) as a last resort for auth-gated OEM driver pages on Windows/macOS.
- Use verify_download(PATH) to check a file's type and checksum after downloading.

Rules:
- Run Tier-1 (diagnostic) commands freely — they are read-only.
- Run Tier-2 (fix) commands only when you have identified the root cause.
- Never assume — always verify with a diagnostic command first.
- If a fix attempt fails, try an alternative approach including web search for the error message.
- If after 3 fix attempts the issue persists, call finish(resolved=False) with escalation_reason.
- Keep the user's explanation in plain English — no jargon.
- You have {max_steps} total steps. Use them wisely.

The user's machine OS is: {os}
"""


# ─────────────────────────────────────────────────────────────────────────────
#  DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _create_session(db: DatabaseConnection, ticket_number: str, device_id: str,
                    user_id: str) -> str:
    session_id = str(uuid.uuid4())
    db.execute_query(
        """INSERT INTO agent_sessions
           (session_id, ticket_number, device_id, user_id, status, max_steps)
           VALUES (%s, %s, %s, %s, 'running', %s)""",
        (session_id, ticket_number, device_id, user_id, MAX_STEPS),
        fetch=False,
    )
    return session_id


def _save_step(db: DatabaseConnection, session_id: str, step_num: int,
               step_type: str, command: str = None, args: dict = None,
               output: str = None, stderr: str = None, exit_code: int = None,
               llm_reasoning: str = None):
    db.execute_query(
        """INSERT INTO session_steps
           (session_id, step_number, step_type, command, args, output, stderr,
            exit_code, llm_reasoning)
           VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)""",
        (session_id, step_num, step_type, command,
         json.dumps(args or {}), output, stderr, exit_code, llm_reasoning),
        fetch=False,
    )


def _generate_report_md(
    session_id: str, ticket_number: str, title: str, category: str,
    status: str, resolution: str, escalation: str,
    steps: list, step_count: int,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    outcome = "✅ Resolved" if status == "resolved" else ("⚠️ Escalated" if status == "escalated" else "❌ Failed")
    lines = [
        f"# Agent Session Report — {ticket_number}",
        f"",
        f"| Field | Value |",
        f"|---|---|",
        f"| **Ticket** | `{ticket_number}` |",
        f"| **Title** | {title} |",
        f"| **Category** | {category or '—'} |",
        f"| **Session ID** | `{session_id}` |",
        f"| **Outcome** | {outcome} |",
        f"| **Total Steps** | {step_count} |",
        f"| **Generated** | {now} |",
        f"",
        f"## Summary",
        f"",
        resolution or escalation or "No resolution recorded.",
        f"",
        f"---",
        f"",
        f"## Step-by-Step Trace",
        f"",
    ]
    for i, s in enumerate(steps, 1):
        stype    = s.get("step_type", "")
        command  = s.get("command") or ""
        args     = s.get("args") or {}
        output   = s.get("output") or ""
        stderr   = s.get("stderr") or ""
        exit_c   = s.get("exit_code")
        reasoning = s.get("llm_reasoning") or ""

        if stype == "reasoning":
            lines += [f"### Step {i}: 🧠 Reasoning", f"", f"> {reasoning}", f""]
        elif stype == "command":
            is_web = command == "web_search"
            icon   = "🔍" if is_web else ("📜" if command.startswith("script:") else "⚡")
            label  = "Web Search" if is_web else ("Script" if command.startswith("script:") else "Command")
            lines += [f"### Step {i}: {icon} {label} — `{command}`", f""]
            if reasoning:
                lines += [f"**Reasoning:** {reasoning}", f""]
            if is_web and args.get("query"):
                lines += [f"**Query:** `{args['query']}`", f""]
            elif args:
                arg_str = " ".join(f"`{k}={v}`" for k, v in args.items() if k != "script_preview")
                if arg_str:
                    lines += [f"**Args:** {arg_str}", f""]
            if args.get("script_preview"):
                lines += [f"**Script preview:**", f"```bash", args["script_preview"], f"```", f""]
        elif stype == "result":
            ec_label = f"Exit `{exit_c}`" if exit_c is not None else ""
            lines += [f"### Step {i}: 📋 Result {ec_label}", f""]
            if output:
                preview = output[:600] + ("…" if len(output) > 600 else "")
                lines += [f"```", preview, f"```", f""]
            if stderr:
                err_preview = stderr[:300] + ("…" if len(stderr) > 300 else "")
                lines += [f"**stderr:**", f"```", err_preview, f"```", f""]
        else:
            lines += [f"### Step {i}: {stype}", f""]

    if escalation:
        lines += [f"", f"---", f"", f"## ⚠️ Escalation Reason", f"", escalation, f""]

    lines += [f"", f"---", f"", f"*Auto-generated by EasyMyTicket AI Agent*"]
    return "\n".join(lines)


def _upload_report(db: DatabaseConnection, session_id: str, report_md: str, ticket_number: str) -> Optional[str]:
    try:
        import boto3, os
        bucket = os.environ.get("S3_EXPORTS_BUCKET", "ticketing-prod-exports-808812816838")
        s3_key = f"agent-reports/{ticket_number}/{session_id}.md"
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=report_md.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
        )
        db.execute_query(
            "UPDATE agent_sessions SET report_s3_key=%s WHERE session_id=%s",
            (s3_key, session_id),
            fetch=False,
        )
        log.info("Agent report uploaded: s3://%s/%s", bucket, s3_key)
        return s3_key
    except Exception as e:
        log.warning("Could not upload agent report to S3: %s", e)
        return None


def _close_session(db: DatabaseConnection, session_id: str, status: str,
                   resolution: str = None, escalation_reason: str = None,
                   step_count: int = 0):
    db.execute_query(
        """UPDATE agent_sessions SET
           status=%s, resolution=%s, escalation_reason=%s,
           step_count=%s, completed_at=NOW()
           WHERE session_id=%s""",
        (status, resolution, escalation_reason, step_count, session_id),
        fetch=False,
    )


def _update_ticket(db: DatabaseConnection, ticket_number: str,
                   status: str, resolution: str):
    db.execute_query(
        "UPDATE new_tickets SET status=%s, resolution=%s WHERE ticketnumber=%s",
        (status, resolution, ticket_number),
        fetch=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Main agentic loop
# ─────────────────────────────────────────────────────────────────────────────

async def run_remediation_session(
    ticket_number: str,
    device_id:     str,
    title:         str,
    description:   str,
    category:      str,
    user_id:       str = "",
    device_os:     str = "Unknown",
    auto_mode:     bool = False,
) -> Dict[str, Any]:
    """
    Run the full agentic remediation loop for a ticket.

    This is a long-running async coroutine — run it with asyncio.create_task()
    so it doesn't block the FastAPI request.

    Returns a result dict with {session_id, resolved, explanation, step_count}.
    """
    from routes.agent_routes import dispatch_tool_call, is_agent_connected

    db = DatabaseConnection()
    session_id = _create_session(db, ticket_number, device_id, user_id)

    log.info("Remediation session started: ticket=%s device=%s session=%s auto_mode=%s",
             ticket_number, device_id, session_id[:8], auto_mode)

    # ── Initialise LLM conversation ───────────────────────────────────────────
    if auto_mode:
        system_content = _AUTO_SYSTEM_PROMPT.format(os=device_os, max_steps=MAX_STEPS)
    else:
        system_content = _SYSTEM_PROMPT.format(os=device_os, max_steps=MAX_STEPS)
    messages: List[Any] = [
        SystemMessage(content=system_content),
        HumanMessage(content=(
            f"Ticket #{ticket_number}\n"
            f"Category: {category}\n"
            f"Title: {title}\n"
            f"Description: {description}\n\n"
            "Please diagnose and fix this issue."
        )),
    ]

    callbacks  = get_callbacks()
    tools      = _AUTO_TOOLS if auto_mode else _TOOLS
    llm        = get_llm(callbacks).bind_tools(tools)

    step_count  = 0
    resolved    = False
    explanation = ""
    escalation  = ""
    fix_attempts = 0

    # ── Agentic loop ──────────────────────────────────────────────────────────
    while step_count < MAX_STEPS:
        step_count += 1

        # Check device is still connected
        if not is_agent_connected(device_id):
            log.warning("Session %s: device %s disconnected at step %d",
                        session_id[:8], device_id, step_count)
            escalation = "Device disconnected during remediation. Please reconnect the agent."
            break

        # LLM decides next action
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: llm.invoke(messages)
            )
        except Exception as e:
            log.error("Session %s: LLM call failed at step %d: %s",
                      session_id[:8], step_count, e)
            escalation = f"LLM error during step {step_count}: {e}"
            break

        messages.append(response)

        # No tool calls → LLM finished without calling finish()
        if not getattr(response, "tool_calls", None):
            explanation = response.content or "Issue investigated — no further actions taken."
            resolved    = True
            _save_step(db, session_id, step_count, "reasoning",
                       llm_reasoning=explanation)
            break

        # Process each tool call the LLM made
        for tool_call in response.tool_calls:
            fn_name = tool_call["name"]
            fn_args = tool_call.get("args", {})
            tc_id   = tool_call.get("id", str(uuid.uuid4()))

            reasoning = fn_args.get("reasoning", "")
            log.info("Session %s step %d: %s(%s) — %s",
                     session_id[:8], step_count, fn_name,
                     fn_args.get("command", fn_name), reasoning)

            # ── finish() ──────────────────────────────────────────────────────
            if fn_name == "finish":
                resolved    = bool(fn_args.get("resolved", False))
                explanation = fn_args.get("explanation", "")
                escalation  = fn_args.get("escalation_reason", "")
                _save_step(db, session_id, step_count, "reasoning",
                           llm_reasoning=explanation)
                messages.append(ToolMessage(content="Session finished.", tool_call_id=tc_id))
                step_count = MAX_STEPS   # break outer loop
                break

            # ── auto mode tools: shell, read_file, write_file, list_dir, download, web_search ──
            elif auto_mode and fn_name in ("shell", "read_file", "write_file",
                                           "list_dir", "create_dir", "delete_path",
                                           "move_path", "copy_path", "download",
                                           "web_search"):
                # Map LLM tool name → execute_auto command + build args
                if fn_name == "shell":
                    command = "shell"
                    args    = {"command": fn_args.get("command", "")}
                elif fn_name == "web_search":
                    command = "web_search"
                    args    = {"query": fn_args.get("query", "")}
                elif fn_name == "download":
                    command = "download"
                    args    = {"url": fn_args.get("url", ""), "path": fn_args.get("path", "")}
                else:
                    command = fn_name
                    args    = {k: v for k, v in fn_args.items() if k != "reasoning"}

                fix_attempts += 1
                _save_step(db, session_id, step_count, "command",
                           command=command, args=args, llm_reasoning=reasoning)
                try:
                    result = await dispatch_tool_call(
                        device_id=device_id,
                        session_id=session_id,
                        command=command,
                        args=args,
                        allow_tier2=True,
                        auto_mode=True,
                        timeout=TOOL_TIMEOUT,
                    )
                    output    = result.get("output", "")
                    stderr    = result.get("stderr", "")
                    exit_code = result.get("exit_code", 0)

                    _save_step(db, session_id, step_count, "result",
                               command=command, output=output, stderr=stderr,
                               exit_code=exit_code)
                    tool_content = (
                        f"exit_code: {exit_code}\nstdout:\n{output[:8000]}"
                        + (f"\nstderr:\n{stderr[:2000]}" if stderr else "")
                    )
                    messages.append(ToolMessage(content=tool_content, tool_call_id=tc_id))

                except Exception as e:
                    err_msg = f"Auto tool '{command}' failed: {e}"
                    _save_step(db, session_id, step_count, "result",
                               command=command, stderr=err_msg, exit_code=1)
                    messages.append(ToolMessage(content=err_msg, tool_call_id=tc_id))

            # ── run_command() ─────────────────────────────────────────────────
            elif fn_name == "run_command":
                command = fn_args.get("command", "")
                args    = fn_args.get("args") or {}
                from agent.executor import TIER2 as _TIER2
                is_fix  = command in _TIER2
                if is_fix and not auto_mode:
                    fix_attempts += 1
                    # E3: gate Tier-2 commands behind technician approval (standard mode only)
                    from routes.agent_routes import request_tier2_approval
                    approved = await request_tier2_approval(
                        session_id=session_id,
                        command=command,
                        reasoning=reasoning,
                        timeout=300,
                    )
                    if not approved:
                        escalation = (
                            f"Technician did not approve Tier-2 command '{command}'. "
                            "Session escalated for manual intervention."
                        )
                        _save_step(db, session_id, step_count, "reasoning",
                                   llm_reasoning=f"Approval denied for {command}")
                        messages.append(ToolMessage(
                            content="Approval denied — session escalated.", tool_call_id=tc_id
                        ))
                        step_count = MAX_STEPS
                        break
                elif is_fix:
                    fix_attempts += 1

                _save_step(db, session_id, step_count, "command",
                           command=command, args=args, llm_reasoning=reasoning)
                try:
                    result = await dispatch_tool_call(
                        device_id=device_id,
                        session_id=session_id,
                        command=command,
                        args=args,
                        allow_tier2=True,
                        timeout=TOOL_TIMEOUT,
                    )
                    output   = result.get("output", "")
                    stderr   = result.get("stderr", "")
                    exit_code = result.get("exit_code", 0)

                    _save_step(db, session_id, step_count, "result",
                               command=command, output=output, stderr=stderr,
                               exit_code=exit_code)

                    tool_content = (
                        f"exit_code: {exit_code}\n"
                        f"stdout:\n{output[:4000]}\n"
                        f"stderr:\n{stderr[:1000]}" if stderr else
                        f"exit_code: {exit_code}\nstdout:\n{output[:4000]}"
                    )
                    messages.append(ToolMessage(content=tool_content, tool_call_id=tc_id))

                except (TimeoutError, RuntimeError) as e:
                    err_msg = f"Command failed: {e}"
                    _save_step(db, session_id, step_count, "result",
                               command=command, stderr=err_msg, exit_code=1)
                    messages.append(ToolMessage(content=err_msg, tool_call_id=tc_id))

            # ── run_script() ──────────────────────────────────────────────────
            elif fn_name == "run_script":
                script      = fn_args.get("script", "")
                script_type = fn_args.get("script_type", "bash")
                fix_attempts += 1

                _save_step(db, session_id, step_count, "command",
                           command=f"script:{script_type}",
                           args={"script_preview": script[:200]},
                           llm_reasoning=reasoning)
                try:
                    result = await dispatch_tool_call(
                        device_id=device_id,
                        session_id=session_id,
                        command="run_script",
                        args={},
                        script=script,
                        script_type=script_type,
                        allow_tier2=True,
                        timeout=TOOL_TIMEOUT,
                    )
                    output    = result.get("output", "")
                    stderr    = result.get("stderr", "")
                    exit_code = result.get("exit_code", 0)

                    _save_step(db, session_id, step_count, "result",
                               command=f"script:{script_type}",
                               output=output, stderr=stderr, exit_code=exit_code)

                    tool_content = (
                        f"exit_code: {exit_code}\nstdout:\n{output[:4000]}\n"
                        + (f"stderr:\n{stderr[:1000]}" if stderr else "")
                    )
                    messages.append(ToolMessage(content=tool_content, tool_call_id=tc_id))

                except Exception as e:
                    err_msg = f"Script execution failed: {e}"
                    _save_step(db, session_id, step_count, "result",
                               stderr=err_msg, exit_code=1)
                    messages.append(ToolMessage(content=err_msg, tool_call_id=tc_id))

            else:
                messages.append(ToolMessage(
                    content=f"Unknown tool: {fn_name}", tool_call_id=tc_id
                ))

            # Auto-escalate after 3 failed fix attempts
            if fix_attempts >= 3 and not resolved:
                last_result = messages[-1].content if messages else ""
                if "exit_code: 1" in last_result or "failed" in last_result.lower():
                    log.warning("Session %s: 3 fix attempts failed — escalating", session_id[:8])
                    escalation  = (
                        "Automated fix attempted 3 times without success. "
                        "The issue requires manual technician intervention."
                    )
                    break

    # ── Max steps reached without finish() ───────────────────────────────────
    if step_count >= MAX_STEPS and not resolved and not escalation:
        escalation = f"Reached maximum step limit ({MAX_STEPS}) without resolution."

    # ── Determine final status ────────────────────────────────────────────────
    final_status = "resolved" if resolved else ("escalated" if escalation else "failed")
    ticket_status = "Resolved" if resolved else "Open"

    if not explanation and escalation:
        explanation = escalation

    _close_session(db, session_id,
                   status=final_status,
                   resolution=explanation,
                   escalation_reason=escalation if not resolved else None,
                   step_count=step_count)

    _update_ticket(db, ticket_number, ticket_status, explanation)

    log.info("Session %s %s after %d steps: %s",
             session_id[:8], final_status, step_count,
             explanation[:100] if explanation else "(none)")

    # Generate and upload markdown report for technician oversight
    try:
        all_steps = db.execute_query(
            "SELECT * FROM session_steps WHERE session_id=%s ORDER BY step_number",
            (session_id,),
        ) or []
        report_md = _generate_report_md(
            session_id=session_id,
            ticket_number=ticket_number,
            title=title,
            category=category,
            status=final_status,
            resolution=explanation,
            escalation=escalation,
            steps=all_steps,
            step_count=step_count,
        )
        _upload_report(db, session_id, report_md, ticket_number)
    except Exception as e:
        log.warning("Report generation failed: %s", e)

    # E2: notify user and technician on session completion
    try:
        from src.agents.notification_agent import NotificationAgent
        ticket_rows = db.execute_query(
            "SELECT assigned_tech_id, issuetype, priority FROM new_tickets WHERE ticketnumber=%s",
            (ticket_number,),
        )
        ticket_meta = ticket_rows[0] if ticket_rows else {}
        NotificationAgent().send_ticket_notification(
            ticket_number=ticket_number,
            title=title,
            priority=ticket_meta.get("priority", "Medium"),
            category=ticket_meta.get("issuetype", category),
            resolution=explanation,
            assigned_tech_id=ticket_meta.get("assigned_tech_id"),
            user_id=user_id,
            auto_resolved=resolved,
            agent_dispatched=True,
        )
    except Exception as e:
        log.warning("Could not send session-completion notification: %s", e)

    return {
        "session_id":  session_id,
        "resolved":    resolved,
        "explanation": explanation,
        "escalation":  escalation,
        "step_count":  step_count,
        "status":      final_status,
    }
