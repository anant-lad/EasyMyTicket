# EasyMyTicket — System Architecture

*Derived from the original design sketch (WhatsApp Image 2026-06-12) and implementation.*

---

## Core Philosophy

The routing decision — whether a ticket goes to the **desktop agent** or a **human technician** — is made by the **LLM**, not by hardcoded keyword rules. The LLM reads the ticket title, description, and classification metadata, then decides:

> "Can this be resolved programmatically (CLI, system commands, config changes, browser actions)?"

If yes → agentic session on the user's device.
If no → assign to a technician.

---

## Pipeline (Ticket Lifecycle)

```
Ticket Submitted
      │
      ▼
┌─────────────┐
│   CREATE    │  Saves raw ticket to DB, assigns ticket number
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  CLASSIFY   │  Two-step LLM pipeline:
│             │    1. Small model (llama-3.1-8b) extracts metadata
│             │       (urgency, affected systems, error messages)
│             │    2. Large model (llama-3.3-70b) classifies against
│             │       picklist (issuetype, category, priority)
│             │  Also runs semantic search over 118k historical tickets
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│  LLM ROUTING    │  ← KEY DECISION (should be LLM-driven, see below)
│  DECISION       │
└────┬────────────┘
     │
     ├──── Agent can solve ──────────────────────────────────────────┐
     │     (device connected + ticket is programmatically solvable)  │
     │                                                               ▼
     │                                                    ┌─────────────────┐
     │                                                    │  AGENTIC        │
     │                                                    │  REMEDIATION    │
     │                                                    │  SESSION        │
     │                                                    │                 │
     │                                                    │  Multi-turn LLM │
     │                                                    │  loop (up to 20 │
     │                                                    │  steps):        │
     │                                                    │                 │
     │                                                    │  Tier-1 cmds:   │
     │                                                    │  diagnostic /   │
     │                                                    │  read-only      │
     │                                                    │                 │
     │                                                    │  Tier-2 cmds:   │
     │                                                    │  fix / write    │
     │                                                    │  (require tech  │
     │                                                    │  approval)      │
     │                                                    └────────┬────────┘
     │                                                             │
     │                                                             ▼
     │                                                    ┌────────────────┐
     │                                                    │ GUARDRAILS     │
     │                                                    │ VALIDATION     │
     │                                                    │ (nemoguardrails│
     │                                                    │  or fallback)  │
     │                                                    └────────┬───────┘
     │                                                             │
     │                                               ┌────────────┴──────────┐
     │                                               │                       │
     │                                           Safe ✅               Risky ⚠️
     │                                               │                       │
     │                                           Execute             Pause for
     │                                           command             human validation
     │
     └──── Human needed ──────────────────────────────────────────┐
           (account issues, policy, physical hardware, complex)    │
                                                                   ▼
                                                        ┌─────────────────┐
                                                        │  SMART          │
                                                        │  ASSIGNMENT     │
                                                        │                 │
                                                        │  Skill match +  │
                                                        │  workload       │
                                                        │  balancing      │
                                                        └────────┬────────┘
                                                                 │
     ┌───────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────┐
│  GENERATE   │  LLM generates human-readable resolution / investigation guide
│  RESOLUTION │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   NOTIFY    │  Email notification via SQS → worker pod
└─────────────┘
```

---

## The Routing Decision (Critical)

### What it IS now (LLM-driven — IMPLEMENTED)

The small LLM (llama-3.1-8b) reads the ticket title, description, and category and returns:
```json
{
  "can_agent_solve": true,
  "confidence": 0.9,
  "reasoning": "Camera driver can be reloaded via modprobe and group permissions can be fixed via CLI",
  "suggested_first_command": "camera_driver_check"
}
```
Any ticket the LLM judges as CLI/script-solvable routes to the agentic session.

### What it SHOULD BE (LLM-driven)

The classification LLM reads the ticket and answers one question:

> **"Can this be diagnosed and/or fixed by running shell commands, system utilities, or CLI tools on the user's device?"**

Tickets the **agent can handle** (programmable/CLI-solvable):
- Camera not working → `lsmod`, `v4l2-ctl`, check video group, reload driver
- WiFi not connecting → `nmcli`, restart NetworkManager, flush DNS
- Disk full → `df -h`, find large files, clear temp
- Slow performance → `top`, kill high-CPU processes, clear cache
- Printer not working → `lpstat`, restart CUPS
- Service crashed → `systemctl status`, `journalctl`, restart service
- Missing driver → `dmesg`, `lspci`, `modprobe`
- Software won't open → check logs, reinstall via `apt`/`brew`/`winget`
- Audio not working → `aplay -l`, `pulseaudio`, ALSA config

Tickets that **need a human technician** (non-programmable):
- Password reset / account locked (identity verification needed)
- Hardware physically broken (screen cracked, keyboard spill)
- VPN/firewall policy changes (requires admin approval)
- Software licensing / procurement
- New employee onboarding
- Complex multi-system incidents requiring judgment
- Anything requiring physical presence

### LLM Routing Prompt (target state)

```python
ROUTING_PROMPT = """
You are deciding whether an IT support ticket should be handled by an 
automated desktop agent (running commands on the user's machine) or 
escalated to a human technician.

Ticket:
Title: {title}
Description: {description}
Category: {category}

Answer with JSON:
{
  "can_agent_solve": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "one sentence",
  "suggested_first_command": "command_name or null"
}

can_agent_solve = true when the issue can be diagnosed/fixed by:
- Running shell commands or system utilities
- Checking/modifying system configuration files
- Restarting services or reloading drivers
- Clearing caches, temp files, or queues
- Checking device/driver status

can_agent_solve = false when the issue requires:
- Identity verification (password reset, account access)
- Physical hardware replacement
- Policy/approval decisions
- Procurement or licensing
- Complex multi-system root cause investigation
"""
```

---

## Web Search & Download Capabilities (IMPLEMENTED)

The agent can search the web and download files to resolve issues that require
fetching drivers, packages, or tools not available via the system package manager.

### How it works

```
LLM decides: "I need to download the camera driver from Ubuntu's repos"
     │
     ▼
run_command(web_search, {QUERY: "ubuntu uvcvideo driver dkms package"})
     │  ← DuckDuckGo JSON API, no key needed, pure Python (urllib)
     ▼
Returns: [{url: "https://packages.ubuntu.com/...", snippet: "..."}]
     │
     ▼
run_command(check_url, {URL: "https://..."})   ← verify reachable
     │
     ▼  [Tier-2 — needs tech approval]
run_command(download_file, {URL: "...", PATH: "/tmp/driver.deb"})
     │  Linux: wget    macOS: curl    Windows: Invoke-WebRequest
     ▼
run_command(verify_download, {PATH: "/tmp/driver.deb"})  ← sha256 + file type
     │
     ▼  [Tier-2 — needs tech approval]
run_command(install_from_file, {PATH: "/tmp/driver.deb"})
     │  Linux: apt install / dpkg -i
     │  macOS: installer -pkg / hdiutil attach
     │  Windows: msiexec /i / Start-Process .exe /S
```

### OS-specific download strategy

| Situation | Linux | macOS | Windows |
|-----------|-------|-------|---------|
| Package in repo | `install_package(apt/brew/winget)` | same | same |
| Direct URL download | `download_file` (wget) | `download_file` (curl) | `download_file` (Invoke-WebRequest) |
| Auth-gated OEM page | `download_file` with headers or `run_script` | `open_browser` as fallback | `open_browser` as fallback |
| Install downloaded pkg | `install_from_file` (.deb/.rpm/.sh) | `install_from_file` (.pkg/.dmg) | `install_from_file` (.msi/.exe) |

### Security model
- `web_search` and `check_url` are **Tier-1** (no approval needed) — read-only
- `download_file`, `install_from_file`, `open_browser` are **Tier-2** (tech approval required)
- The blocklist and protected-path validator still apply to all download paths
- Checksums via `verify_download` after every download

---

## Agent Architecture (Desktop Side)

```
┌────────────────────────────────────┐
│         User's Machine             │
│                                    │
│  ┌──────────────────────────────┐  │
│  │   agent/main.py              │  │
│  │   (WebSocket client)         │  │
│  │   • Persistent connection    │  │
│  │   • Auto-reconnect (15s)     │  │
│  │   • Handles tool_call msgs   │  │
│  └──────────┬───────────────────┘  │
│             │                      │
│  ┌──────────▼───────────────────┐  │
│  │   agent/executor.py          │  │
│  │   (Sandboxed command runner) │  │
│  │                              │  │
│  │   TIER 1 — Diagnostic        │  │
│  │   camera_list, disk_usage,   │  │
│  │   service_status, dmesg,     │  │
│  │   web_search, check_url,     │  │
│  │   verify_download ...        │  │
│  │                              │  │
│  │   TIER 2 — Fix operations    │  │
│  │   (need tech approval)       │  │
│  │   download_file, install_from│  │
│  │   _file, open_browser,       │  │
│  │   reload_camera_driver,      │  │
│  │   add_user_to_video_group,   │  │
│  │   restart_service...         │  │
│  └──────────────────────────────┘  │
│                                    │
│  ┌──────────────────────────────┐  │
│  │   agent/monitor.py           │  │
│  │   (Daily health scan @ 06:00)│  │
│  │   Checks disk, memory, CPU,  │  │
│  │   services, drivers          │  │
│  └──────────────────────────────┘  │
└────────────────────────────────────┘
              │ WebSocket (persistent)
              ▼
┌────────────────────────────────────┐
│    EKS API Pod (FastAPI + uvicorn) │
│    routes/agent_routes.py          │
│    • _connected_agents dict        │
│    • dispatch_tool_call()          │
│    • Tier-2 approval gate          │
└────────────────────────────────────┘
```

---

## Feedback Loop / Learning

The architecture includes a feedback loop where resolved tickets feed back into:
1. **Historical tickets DB** (118k rows) — used for semantic search on new tickets
2. **LangFuse traces** — LLM call quality monitoring
3. **Daily reports** — morning digest of overnight scans and auto-created tickets

---

## Agentic Remediation Session (Multi-turn LLM Loop)

```
Session Created
      │
      ▼
LLM reads: ticket title + description + category + device OS
      │
      ▼
LLM picks a tool:
  run_command(name, args, reasoning)   → sends to agent via WebSocket
  run_script(language, code, reasoning) → agent executes inline script
  finish(resolution, outcome)           → ends session
      │
      ▼
Agent executes on device → returns output
      │
      ▼
Is this a Tier-2 command?
  No  → execute immediately, show result to LLM
  Yes → pause session (status: awaiting_approval)
        technician sees command + reasoning in dashboard
        approve → execute
        reject  → LLM tries alternative approach
      │
      ▼
LLM reads output → next tool call (up to 20 steps)
      │
      ▼
finish() called:
  outcome=resolved → ticket status → Resolved
  outcome=escalated → assign to technician with full session transcript
```

---

## Infrastructure

| Component | Technology | Details |
|-----------|-----------|---------|
| API | FastAPI + uvicorn (1 worker) | EKS, ap-south-1 |
| Worker | Same image, different CMD | SQS consumer for notifications |
| DB | PostgreSQL 16 (RDS) | 11 tables, 118k historical rows |
| Cache | ElastiCache Redis | Semantic search result caching |
| Queue | SQS (2 queues) | LLM tasks + notifications |
| LLM | Groq (primary) → OpenRouter (fallback) | llama-3.3-70b + llama-3.1-8b |
| Observability | LangFuse + custom PostgreSQL traces | |
| Agent state | In-memory dict (single worker) | Future: Redis pub/sub for multi-pod |
