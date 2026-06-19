"""
EasyMyTicket Desktop Remediation Agent
=======================================
Runs as a background service on Windows / macOS / Linux.

Two operating modes
───────────────────
1. DAILY SCAN (triggered by OS scheduler at 06:00):
   python -m agent.main --scan
   → Runs agent/monitor.py once, caches the report locally.
   → If the server is reachable, uploads immediately.
   → Exits after upload (or after caching if offline).

2. PERSISTENT WEBSOCKET (triggered separately, also at startup):
   python -m agent.main          (default)
   → Maintains a persistent WebSocket to the backend.
   → On connect: drains any unsent daily report + pending task results.
   → Processes two message types:
       task      — legacy one-shot command (backward compat)
       tool_call — agentic-session step (multi-turn, reply with tool_result)

Env vars
────────
  AGENT_API_URL           wss://api.yourdomain.com
  AGENT_API_KEY           <API key>
  AGENT_DEVICE_ID         <UUID — auto-generated on first run and persisted>
  AGENT_MONITOR_USER_ID   user account that "owns" this machine
  AGENT_RECONNECT_DELAY   seconds between reconnect attempts (default 10)
"""
import argparse
import asyncio
import json
import logging
import os
import platform
import signal
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    import websockets
except ImportError:
    print("Missing dependency: pip install websockets")
    sys.exit(1)

from agent.diagnostics  import get_system_info, ping, run_all as run_diagnostics
from agent.executor     import execute, execute_auto, execute_script, TIER1, TIER2
from agent.offline_queue import (
    drain_pending_tasks, drain_to_websocket,
    enqueue_result, queue_stats,
)
from agent.reporter     import send_pending_report, run_and_send

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("agent")

# ── Config ────────────────────────────────────────────────────────────────────

_CACHE_DIR    = Path(os.getenv("AGENT_CACHE_DIR", Path.home() / ".easymyticket"))
_DEVICE_ID_FILE = _CACHE_DIR / "device_id.txt"


def _get_or_create_device_id() -> str:
    """Persist device ID across restarts so the server can correlate machines."""
    env_id = os.getenv("AGENT_DEVICE_ID", "")
    if env_id:
        return env_id
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if _DEVICE_ID_FILE.exists():
            return _DEVICE_ID_FILE.read_text().strip()
        new_id = str(uuid.uuid4())
        _DEVICE_ID_FILE.write_text(new_id)
        return new_id
    except OSError:
        return str(uuid.uuid4())


API_URL         = os.getenv("AGENT_API_URL", "ws://localhost:8000")
API_KEY         = os.getenv("AGENT_API_KEY", "")
DEVICE_ID       = _get_or_create_device_id()
MONITOR_USER_ID = os.getenv("AGENT_MONITOR_USER_ID", "agent_monitor")
RECONNECT_DELAY = int(os.getenv("AGENT_RECONNECT_DELAY", "10"))
AUTO_MODE       = os.getenv("AGENT_AUTO_MODE", "0") == "1"  # full system access when enabled

WS_URL = f"{API_URL.rstrip('/')}/ws/agent/{DEVICE_ID}"


# ─────────────────────────────────────────────────────────────────────────────
#  Legacy one-shot task handler (backward compat with existing pipelines)
# ─────────────────────────────────────────────────────────────────────────────

async def handle_task(task: dict, ws=None) -> dict:
    """Execute a single dispatched one-shot task and return the result dict."""
    task_id      = task.get("task_id", "?")
    command_type = task.get("command_type", "")
    payload      = task.get("command_payload") or {}

    log.info("Task %s: command=%s", task_id, command_type)

    try:
        if command_type == "diagnostic":
            result_data = run_diagnostics()
            exit_code, stdout, stderr = 0, json.dumps(result_data, default=str), ""

        elif command_type == "ping":
            host = payload.get("host", "8.8.8.8")
            result_data = ping(host)
            exit_code = 0 if result_data.get("reachable") else 1
            stdout, stderr = json.dumps(result_data), ""

        else:
            # Allow Tier-2 for explicit one-shot tasks (dispatched by a human tech)
            exit_code, stdout, stderr = execute(command_type, payload, allow_tier2=True)

        result = {
            "type":          "task_result",
            "task_id":       task_id,
            "status":        "completed" if exit_code == 0 else "failed",
            "result_output": stdout[:10_000],
            "stderr":        stderr[:2_000],
            "exit_code":     exit_code,
            "completed_at":  datetime.now(timezone.utc).isoformat(),
        }

    except (ValueError, PermissionError) as e:
        log.warning("Task %s rejected: %s", task_id, e)
        result = {"type": "task_result", "task_id": task_id,
                  "status": "failed", "result_output": "", "stderr": str(e), "exit_code": 2}
    except Exception as e:
        log.error("Task %s error: %s", task_id, e)
        result = {"type": "task_result", "task_id": task_id,
                  "status": "failed", "result_output": "", "stderr": str(e), "exit_code": 1}

    if ws is not None:
        try:
            await ws.send(json.dumps(result))
        except Exception as send_err:
            log.warning("Could not send task result — queuing: %s", send_err)
            enqueue_result(task_id, result)
    else:
        enqueue_result(task_id, result)

    return result


# ─────────────────────────────────────────────────────────────────────────────
#  Agentic session — tool_call handler (Part 2)
# ─────────────────────────────────────────────────────────────────────────────

async def handle_tool_call(msg: dict, ws) -> None:
    """
    Handle a tool_call from the server's agentic remediation loop.

    The server sends:
        {"type": "tool_call", "session_id": "...", "call_id": "...",
         "command": "bluetooth_status", "args": {}, "allow_tier2": false,
         "script": null}

    We execute and reply with:
        {"type": "tool_result", "session_id": "...", "call_id": "...",
         "exit_code": 0, "output": "...", "stderr": ""}
    """
    session_id   = msg.get("session_id", "")
    call_id      = msg.get("call_id", "")
    command      = msg.get("command", "")
    args         = msg.get("args") or {}
    allow_tier2  = bool(msg.get("allow_tier2", True))   # agentic sessions allow Tier-2
    script       = msg.get("script")                     # optional inline script
    script_type  = msg.get("script_type", "auto")

    log.info("tool_call [session=%s call=%s]: %s args=%s",
             session_id[:8], call_id[:8], command, args)

    # Server tells us if this session was started in auto mode
    server_auto_mode = bool(msg.get("auto_mode", False))
    use_auto = AUTO_MODE and server_auto_mode

    try:
        if script:
            # Inline script from server (novel fix or auto mode custom command)
            exit_code, stdout, stderr = execute_script(
                script, script_type=script_type, args=args
            )
        elif command == "diagnostic":
            data = run_diagnostics()
            exit_code, stdout, stderr = 0, json.dumps(data, default=str), ""
        elif command == "ping":
            data = ping(args.get("host", "8.8.8.8"))
            exit_code = 0 if data.get("reachable") else 1
            stdout, stderr = json.dumps(data), ""
        elif use_auto:
            # Full unrestricted access — shell, file r/w, download, etc.
            exit_code, stdout, stderr = execute_auto(command, args)
        else:
            exit_code, stdout, stderr = execute(command, args, allow_tier2=allow_tier2)

    except Exception as e:
        log.error("tool_call error [%s]: %s", command, e)
        exit_code, stdout, stderr = 1, "", str(e)

    result = {
        "type":       "tool_result",
        "session_id": session_id,
        "call_id":    call_id,
        "exit_code":  exit_code,
        "output":     stdout[:20_000],
        "stderr":     stderr[:4_000],
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await ws.send(json.dumps(result))
    except Exception as e:
        log.error("Could not send tool_result for call_id=%s: %s", call_id, e)


# ─────────────────────────────────────────────────────────────────────────────
#  WebSocket loop
# ─────────────────────────────────────────────────────────────────────────────

async def agent_loop(stop_event: asyncio.Event):
    headers     = {"X-API-Key": API_KEY} if API_KEY else {}
    device_info = get_system_info()
    device_info["device_id"] = DEVICE_ID
    device_info["os"]        = platform.system()

    log.info("Connecting to %s", WS_URL)

    async with websockets.connect(
        WS_URL, additional_headers=headers,
        ping_interval=30, ping_timeout=10,
    ) as ws:
        # Register — include auto_mode flag so server knows what this agent supports
        device_info["auto_mode"] = AUTO_MODE
        await ws.send(json.dumps({"type": "register", "device": device_info}))
        log.info("Registered: device_id=%s os=%s host=%s auto_mode=%s",
                 DEVICE_ID, platform.system(), platform.node(), AUTO_MODE)

        # On reconnect — drain any unsent daily report and offline task results
        await send_pending_report(API_URL, API_KEY, DEVICE_ID)

        stats = queue_stats()
        if stats.get("pending_results", 0) > 0:
            await drain_to_websocket(ws)
        if stats.get("pending_tasks", 0) > 0:
            await drain_pending_tasks(handle_task)

        # Main message loop
        async for raw in ws:
            if stop_event.is_set():
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("Non-JSON message: %s", raw[:100])
                continue

            msg_type = msg.get("type", "")

            if msg_type == "task":
                # Legacy one-shot task
                await handle_task(msg, ws)

            elif msg_type == "tool_call":
                # Agentic session step — execute and reply immediately
                asyncio.ensure_future(handle_tool_call(msg, ws))

            elif msg_type == "ping":
                await ws.send(json.dumps({"type": "pong"}))

            elif msg_type == "shutdown":
                log.info("Server requested shutdown")
                stop_event.set()
                break

            elif msg_type == "queue_stats":
                await ws.send(json.dumps({"type": "queue_stats_response", **queue_stats()}))

            else:
                log.debug("Unknown message type: %s", msg_type)


# ─────────────────────────────────────────────────────────────────────────────
#  Reconnect wrapper
# ─────────────────────────────────────────────────────────────────────────────

async def run_with_reconnect():
    stop_event = asyncio.Event()

    def _signal_handler():
        log.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_event_loop()
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)
        loop.add_signal_handler(signal.SIGINT,  _signal_handler)

    while not stop_event.is_set():
        try:
            await agent_loop(stop_event)
        except (OSError,
                websockets.exceptions.ConnectionClosed,
                websockets.exceptions.WebSocketException) as e:
            log.warning("Connection lost (%s) — reconnecting in %ds", e, RECONNECT_DELAY)
        except Exception as e:
            log.error("Unexpected error: %s — reconnecting in %ds", e, RECONNECT_DELAY)

        if not stop_event.is_set():
            for _ in range(RECONNECT_DELAY):
                if stop_event.is_set():
                    break
                await asyncio.sleep(1)

    log.info("Agent stopped")


# ─────────────────────────────────────────────────────────────────────────────
#  CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

async def _run_daily_scan_mode():
    """--scan mode: run scan, upload, exit."""
    log.info("Running in daily-scan mode (device_id=%s)", DEVICE_ID)
    sent = await run_and_send(
        api_url=API_URL,
        api_key=API_KEY,
        device_id=DEVICE_ID,
        user_id=MONITOR_USER_ID,
    )
    if sent:
        log.info("Daily report uploaded successfully")
    else:
        log.info("Daily report cached locally — will upload on next WebSocket connection")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EasyMyTicket Desktop Agent")
    parser.add_argument("--scan", action="store_true",
                        help="Run daily scan once and exit (called by OS scheduler)")
    parser.add_argument("--auto", action="store_true",
                        help=(
                            "Enable auto mode: grants the AI full access to this machine "
                            "(shell commands, file read/write, downloads). "
                            "Equivalent to setting AGENT_AUTO_MODE=1."
                        ))
    args = parser.parse_args()

    if args.auto:
        import agent.main as _self
        _self.AUTO_MODE = True
        os.environ["AGENT_AUTO_MODE"] = "1"
        log.info("AUTO MODE ENABLED — AI has full system access on this machine")

    if args.scan:
        asyncio.run(_run_daily_scan_mode())
    else:
        asyncio.run(run_with_reconnect())
