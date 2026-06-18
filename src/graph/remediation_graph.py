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

    return [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": (
                    "Run a diagnostic or fix command on the user's machine. "
                    "The result will be returned to you so you can reason about it. "
                    f"Tier-1 (diagnostic, always safe): {tier1_list}. "
                    f"Tier-2 (fix operations, use when confident): {tier2_list}."
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

Rules:
- Run Tier-1 (diagnostic) commands freely — they are read-only.
- Run Tier-2 (fix) commands only when you have identified the root cause.
- Never assume — always verify with a diagnostic command first.
- If a fix attempt fails, try an alternative approach.
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

    log.info("Remediation session started: ticket=%s device=%s session=%s",
             ticket_number, device_id, session_id[:8])

    # ── Initialise LLM conversation ───────────────────────────────────────────
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
    llm        = get_llm(callbacks).bind_tools(_TOOLS)

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

            # ── run_command() ─────────────────────────────────────────────────
            elif fn_name == "run_command":
                command = fn_args.get("command", "")
                args    = fn_args.get("args") or {}
                is_fix  = command in __import__("agent.executor", fromlist=["TIER2"]).TIER2
                if is_fix:
                    fix_attempts += 1
                    # E3: gate Tier-2 commands behind technician approval
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
