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
from src.llm.provider import get_callbacks, get_llm, get_llm_for_tools
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
                "name": "search_knowledge_base",
                "description": (
                    "Search the internal Linux troubleshooting knowledge base for documented fixes. "
                    "Use this when you need more context about a specific error, driver, or issue pattern. "
                    "Returns relevant articles with symptoms, fix steps, and verification commands. "
                    "Runs on the backend — does NOT dispatch to the device."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language search query, e.g. 'camera not working video group'",
                        },
                        "category": {
                            "type": "string",
                            "description": "Optional category filter: camera, wifi, audio, bluetooth, driver, nvidia, docker, ssh, grub, disk, etc.",
                        },
                    },
                    "required": ["query"],
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
                "name": "search_knowledge_base",
                "description": (
                    "Search the internal Linux troubleshooting KB for documented fixes. "
                    "Runs on the backend — no device dispatch. "
                    "Returns articles with symptoms, fix_steps, and verification commands."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":    {"type": "string", "description": "Search query"},
                        "category": {"type": "string", "description": "Optional category filter"},
                    },
                    "required": ["query"],
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
5. FINISH   — call finish() with a complete user-facing explanation

Rules:
- Prefer targeted fixes over broad ones (fix one service, not reinstall the OS)
- Always verify before finishing
- If 3 fix attempts fail, escalate with a clear explanation
- finish() explanation is read by the END USER, not a technician — write it for them
- For INSTALLATION or SETUP tickets: the resolution MUST include:
    * What was installed/configured and where
    * Step-by-step instructions on HOW TO USE it (the user does not know)
    * Any credentials, config files, or commands they need (e.g. "run: sudo openvpn --config /etc/openvpn/client.conf")
    * What to do if it doesn't work (basic troubleshooting tip)
  Example: after installing a VPN client, don't just say "OpenVPN installed". Instead:
    "OpenVPN has been installed. To connect to a VPN: 1) Obtain a .ovpn config file from your VPN provider.
     2) Run: sudo openvpn --config /path/to/your.ovpn  3) To verify the connection: curl ifconfig.me
     If you need a specific VPN provider configured, please share the .ovpn file with your IT team."
VPN SETUP / TROUBLESHOOTING:
- wifi_status shows nearby WiFi access points — NOT VPN connections. Never use it for VPN diagnosis.
- For "setup" / "install" / "I need a VPN" tickets: install a VPN client using install_package.
  * "free VPN" / unspecified → install openvpn
  * "WireGuard" → install wireguard
  * "Cisco AnyConnect" / corporate → install openconnect
- After installing: verify with dpkg -l openvpn (or equivalent), then provide usage steps in finish().
- To check existing VPN connections: use vpn_status or connection_list (never wifi_status).
- You have {max_steps} total steps — use them wisely

User's machine OS: {os}
"""


# ─────────────────────────────────────────────────────────────────────────────
#  System prompt
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an expert IT support engineer with remote access to the user's machine.
Your job: read the ticket, reason about the root cause, diagnose it, fix it, verify the fix actually resolves what the user reported, then close.

WORKFLOW:
1. READ   — understand exactly what the user says is broken. What did they try? What error did they see?
2. REASON — before running any command, think: what are the possible causes of this specific issue?
3. DIAGNOSE — run Tier-1 (read-only) commands to gather evidence. Let output guide next steps — not a preset script.
4. ROOT CAUSE — identify the specific cause from evidence. Don't fix until you know what you're fixing.
5. FIX — apply the minimal targeted fix. One change at a time.
6. VERIFY — this is mandatory. Prove the user's actual reported problem is gone.
   Verification must test the SAME THING the user complained about — not a proxy.
   Examples:
     - "camera not working" → capture a real frame as the actual human user, confirm it succeeds
     - "WiFi not connecting" → ping 8.8.8.8, not just check ifconfig
     - "app crashes on launch" → actually launch the app, check exit code
   A kernel module being loaded, a service being active, or a file existing is NOT verification.
7. FINISH — call finish(resolved=True) only after verification passes with concrete proof.
            If verification fails after 3 fix attempts, call finish(resolved=False, escalation_reason=
            "What I tried: ... What failed: ... What the technician should try next: ...")
            The resolution text in finish() is read directly by the END USER — write it for them, not a technician.
            For INSTALLATION or SETUP tickets, you MUST include in the resolution:
              * What was installed/configured
              * Step-by-step HOW TO USE instructions (assume the user has never used this before)
              * Any commands, config files, or credentials they need to know
              * A basic "what to do if it doesn't work" tip
            Example — VPN installation resolution:
              "OpenVPN has been installed on your machine. To connect to a VPN:
               1. Get a .ovpn config file from your VPN provider or IT team.
               2. Connect by running: sudo openvpn --config /path/to/your.ovpn
               3. Verify the VPN is working: curl ifconfig.me (should show your VPN server's IP)
               4. To disconnect: press Ctrl+C in the terminal where OpenVPN is running.
               If you need a corporate VPN profile set up, share the .ovpn file with your IT team."

SYSTEM CONTEXT (important):
- This agent runs as root inside a systemd service. $(whoami) = root — never use it for the human user.
- Get the actual logged-in user: ACTUAL_USER=$(logname 2>/dev/null || who | awk 'NR==1{print $1}')
- Run things AS the human user: su - "$ACTUAL_USER" -c '...' (for permission-sensitive checks)
- Named commands like camera_permission_check and add_user_to_video_group already handle this internally.

WEB SEARCH & DOWNLOAD:
- web_search(QUERY) — find drivers, packages, error explanations, fix procedures
- download_file(URL, PATH) — download to device (prefer over open_browser on Linux)
- install_from_file(PATH) — install .deb/.rpm/.pkg/.exe/.msi
- open_browser(URL) — only when download requires auth or CAPTCHA

KNOWLEDGE BASE:
- You have access to search_knowledge_base(query) — searches our internal Linux troubleshooting KB.
- At session start, relevant KB articles may already be provided in the ticket context below.
- When a KB article is shown, compare its fix against what YOUR diagnostics find first.
  Don't blindly apply it — use it to guide your approach, then confirm with evidence.
- KB articles include a VERIFY command — run it verbatim to prove resolution.
- If no KB context was pre-loaded, call search_knowledge_base early in your diagnosis.

PHYSICAL / HARDWARE TRIAGE (read this first):
Some tickets cannot be fixed remotely. Identify them immediately from the ticket title and description — do NOT run diagnostics first.
Call finish(resolved=False, escalation_reason="...") RIGHT AWAY if the ticket describes:
  - Broken, cracked, or damaged physical components (screen, keyboard, motherboard, battery, ports)
  - Hardware replacement or procurement requests (new laptop, RAM upgrade, printer replacement)
  - Physical theft, loss, or destruction of equipment
  - On-site setup, cable installation, or physical deployment tasks
  - Any issue where the resolution inherently requires a human technician to be physically present

Example: "laptop screen is broken" → immediately call finish(resolved=False, escalation_reason=
"Physical hardware damage — broken laptop screen requires on-site technician or hardware replacement. Cannot be resolved remotely.")
Do NOT web-search, do NOT run any commands — just finish with escalation.

VPN SETUP / TROUBLESHOOTING (read this section for any VPN ticket):
- wifi_status shows nearby wireless access points — it does NOT show VPN connections. Never use it for VPN diagnosis.
- To check VPN connections: use vpn_status or connection_list.
- For "setup" / "install" / "I need a VPN" tickets — the user needs a VPN client installed:
  * "free VPN" / unspecified → install openvpn (apt-get install -y openvpn)
  * "WireGuard" → install_package(wireguard)
  * "Cisco AnyConnect" / corporate → install_package(openconnect)
- After installing, test with: dpkg -l openvpn (Linux) or which openvpn.
- The resolution MUST include exact steps the user needs to run to connect to their VPN.
- For "connect to VPN" tickets (client already installed): use vpn_status to find the connection name,
  then run_script to execute: nmcli con up id "<NAME>" or sudo openvpn --config /path/to/file.ovpn

RULES:
- Tier-1 (diagnostic) commands are read-only — run them freely.
- Tier-2 (fix) commands — only after you know the root cause from evidence.
- Never run the same diagnostic twice expecting different output.
- If a fix fails, search the web for the actual error message before trying another approach.
- You have {max_steps} steps — use them on reasoning and targeted actions, not repeat checks.

User's machine OS: {os}
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
    ticket_number:       str,
    device_id:           str,
    title:               str,
    description:         str,
    category:            str,
    user_id:             str = "",
    device_os:           str = "Unknown",
    auto_mode:           bool = False,
    oversight_tech_id:   Optional[str] = None,
    oversight_tech_name: Optional[str] = None,
    session_id:          Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the full agentic remediation loop for a ticket.

    This is a long-running async coroutine — run it with asyncio.create_task()
    so it doesn't block the FastAPI request.

    Pass session_id if the caller pre-created the session (e.g. to return it
    immediately to the client before the coroutine runs).

    Returns a result dict with {session_id, resolved, explanation, step_count}.
    """
    from routes.agent_routes import dispatch_tool_call, is_agent_connected

    db = DatabaseConnection()
    if not session_id:
        session_id = _create_session(db, ticket_number, device_id, user_id)

    # Store oversight tech and notify them
    if oversight_tech_id:
        try:
            db.execute_query(
                """UPDATE agent_sessions SET oversight_tech_id=%s, oversight_tech_name=%s,
                   oversight_notified_at=NOW() WHERE session_id=%s""",
                (oversight_tech_id, oversight_tech_name, session_id),
                fetch=False,
            )
            # Get oversight tech email and send notification
            tech_rows = db.execute_query(
                "SELECT tech_mail FROM technician_data WHERE tech_id=%s LIMIT 1",
                (oversight_tech_id,),
            )
            if tech_rows and tech_rows[0].get("tech_mail"):
                from src.agents.notification_agent import NotificationAgent
                NotificationAgent().notify_oversight_tech(
                    tech_name=oversight_tech_name or oversight_tech_id,
                    tech_email=tech_rows[0]["tech_mail"],
                    ticket_number=ticket_number,
                    title=title,
                    session_id=session_id,
                )
        except Exception as e:
            log.warning("Could not set oversight tech: %s", e)

    log.info("Remediation session started: ticket=%s device=%s session=%s auto_mode=%s",
             ticket_number, device_id, session_id[:8], auto_mode)

    # ── Pre-fetch KB context ──────────────────────────────────────────────────
    kb_context = ""
    try:
        from src.database.db_connection import format_kb_context
        kb_articles = db.search_kb(f"{title} {description}", top_k=3)
        if kb_articles:
            kb_context = format_kb_context(kb_articles)
            log.info("Session %s: KB pre-fetch found %d articles", session_id[:8], len(kb_articles))
        else:
            log.info("Session %s: no KB articles found for this ticket", session_id[:8])
    except Exception as e:
        log.warning("Session %s: KB pre-fetch failed (non-fatal): %s", session_id[:8], e)

    # ── Pre-fetch similar resolved tickets ────────────────────────────────────
    similar_context = ""
    try:
        similar = db.find_similar_tickets(title, description or "", limit=2)
        resolved_similar = [
            t for t in similar
            if t.get("resolution") and t.get("status") in ("resolved", "closed")
        ]
        if resolved_similar:
            lines = ["SIMILAR RESOLVED TICKETS:\n"]
            for t in resolved_similar[:2]:
                lines.append(f"- [{t['ticketnumber']}] {t['title']}")
                lines.append(f"  Resolution: {str(t['resolution'])[:300]}")
                lines.append("")
            similar_context = "\n".join(lines)
            log.info("Session %s: found %d similar resolved tickets", session_id[:8], len(resolved_similar))
    except Exception as e:
        log.warning("Session %s: similar ticket search failed (non-fatal): %s", session_id[:8], e)

    # ── Initialise LLM conversation ───────────────────────────────────────────
    if auto_mode:
        system_content = _AUTO_SYSTEM_PROMPT.format(os=device_os, max_steps=MAX_STEPS)
    else:
        system_content = _SYSTEM_PROMPT.format(os=device_os, max_steps=MAX_STEPS)

    ticket_msg = (
        f"Ticket #{ticket_number}\n"
        f"Category: {category}\n"
        f"Title: {title}\n"
        f"Description: {description}\n\n"
    )
    if kb_context:
        ticket_msg += kb_context + "\n"
    if similar_context:
        ticket_msg += similar_context + "\n"
    ticket_msg += (
        "Please diagnose and fix this issue.\n"
        + ("If KB articles or similar tickets are shown above, compare their fixes against "
           "what you observe from diagnostics before applying anything.\n"
           if kb_context or similar_context else "")
    )

    messages: List[Any] = [
        SystemMessage(content=system_content),
        HumanMessage(content=ticket_msg),
    ]

    callbacks  = get_callbacks()
    tools      = _AUTO_TOOLS if auto_mode else _TOOLS
    # Pass tools into get_llm_for_tools so bind_tools is applied per-model
    # before the Groq→OpenRouter fallback chain is built. Calling .bind_tools()
    # on the returned chain would fail because RunnableWithFallbacks doesn't expose it.
    llm        = get_llm_for_tools(callbacks, tools=tools)

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
        log.info("Session %s step %d: invoking LLM...", session_id[:8], step_count)
        try:
            response = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, lambda: llm.invoke(messages)
                ),
                timeout=90,  # 90 s max per step — prevents hang on Groq rate-limit stalls
            )
        except asyncio.TimeoutError:
            log.error("Session %s: LLM timed out at step %d", session_id[:8], step_count)
            escalation = f"LLM timed out at step {step_count} — Groq/OpenRouter did not respond within 90 s."
            break
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

            # ── search_knowledge_base() — backend only, no device dispatch ────
            if fn_name == "search_knowledge_base":
                query    = fn_args.get("query", "")
                category = fn_args.get("category")
                try:
                    from src.database.db_connection import format_kb_context
                    results = db.search_kb(query, category=category, top_k=3)
                    content = format_kb_context(results) or "No relevant articles found in knowledge base."
                    log.info("Session %s: KB search=%r → %d results",
                             session_id[:8], query[:60], len(results))
                except Exception as e:
                    content = f"Knowledge base search failed: {e}"
                    log.warning("Session %s: KB search error: %s", session_id[:8], e)
                _save_step(db, session_id, step_count, "reasoning",
                           llm_reasoning=f"KB search: {query}")
                messages.append(ToolMessage(content=content, tool_call_id=tc_id))
                continue

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
    # Escalated = technician needs to take over → "In Progress", not "Open"
    ticket_status = "Resolved" if resolved else ("In Progress" if escalation else "Open")

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

    # Notify user and technician on session completion
    try:
        from src.agents.notification_agent import NotificationAgent
        ticket_rows = db.execute_query(
            "SELECT assigned_tech_id, issuetype, priority FROM new_tickets WHERE ticketnumber=%s",
            (ticket_number,),
        )
        ticket_meta = ticket_rows[0] if ticket_rows else {}
        assigned_tech_id = ticket_meta.get("assigned_tech_id") or oversight_tech_id
        notif = NotificationAgent()

        # Standard user + tech notification (resolved or assigned)
        notif.send_ticket_notification(
            ticket_number=ticket_number,
            title=title,
            priority=ticket_meta.get("priority", "Medium"),
            category=ticket_meta.get("issuetype", category),
            resolution=explanation,
            assigned_tech_id=assigned_tech_id,
            user_id=user_id,
            auto_resolved=resolved,
            agent_dispatched=False,  # completion email: show resolution or technician info, not "AI dispatched"
        )

        # Escalation: tech handoff email with session trace link
        if not resolved and assigned_tech_id:
            try:
                tech_rows = db.execute_query(
                    "SELECT tech_name, tech_mail FROM technician_data WHERE tech_id=%s",
                    (assigned_tech_id,),
                )
                if tech_rows:
                    notif.send_escalation_notification(
                        tech_id=assigned_tech_id,
                        tech_name=tech_rows[0]["tech_name"],
                        tech_mail=tech_rows[0].get("tech_mail", ""),
                        ticket_number=ticket_number,
                        title=title,
                        escalation_reason=escalation or explanation,
                        session_id=session_id,
                        step_count=step_count,
                    )
            except Exception as e:
                log.warning("Could not send escalation notification: %s", e)
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
