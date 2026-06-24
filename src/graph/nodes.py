"""
LangGraph node implementations for the EasyMyTicket ticket pipeline.

Node contract:
  - Accepts TicketState dict
  - Returns a partial TicketState dict (only the fields it sets)
  - Appends to state["errors"] on non-fatal failures rather than raising

Graph order:
  create_ticket → classify → auto_route_decision → (agent_task | assign_tech)
                                                              ↓
                                                       generate_resolution
                                                              ↓
                                                          notify
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from src.graph.state import TicketState
from src.llm.provider import get_callbacks, get_llm, get_small_llm
from src.utils.logger import flow, Timer

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  Helper: safe JSON parse from LLM output
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    import re
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


# ─────────────────────────────────────────────────────────────────────────────
#  Node 1 — create_ticket
# ─────────────────────────────────────────────────────────────────────────────

def create_ticket_node(state: TicketState) -> Dict:
    """Save the raw ticket to new_tickets and return the ticket_number.
    If state already contains ticket_number the ticket was pre-created — skip INSERT."""
    from src.database.db_connection import DatabaseConnection

    db = DatabaseConnection()

    # Pre-created by API endpoint (async path) — just return the existing number
    if state.get("ticket_number"):
        flow(log, "TICKET:EXISTS", ticket=state["ticket_number"], source=state.get("source"))
        return {"ticket_number": state["ticket_number"], "errors": list(state.get("errors", []))}

    ticket_number = f"TKT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    query = """
        INSERT INTO new_tickets
            (ticketnumber, title, description, user_id, status, createdate, source)
        VALUES (%s, %s, %s, %s, 'Open', NOW(), %s)
        ON CONFLICT (ticketnumber) DO NOTHING
    """
    try:
        db.execute_query(
            query,
            (
                ticket_number,
                state["title"],
                state["description"],
                state["user_id"],
                state.get("source", "portal"),
            ),
        )
        flow(log, "TICKET:CREATED",
             ticket=ticket_number, user=state["user_id"],
             source=state.get("source", "portal"),
             title=state["title"][:80])
    except Exception as e:
        log.error("create_ticket_node failed for %s: %s", ticket_number, e, exc_info=True)
        return {"ticket_number": ticket_number, "errors": [str(e)]}

    return {"ticket_number": ticket_number, "errors": []}


# ─────────────────────────────────────────────────────────────────────────────
#  Node 2 — classify
# ─────────────────────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessage(content=(
        "You are an IT support metadata extractor. "
        "Extract ONLY information that is explicitly stated in the ticket — do NOT invent or infer details. "
        "If a field has no evidence in the ticket, use an empty list or null. "
        "Reply ONLY with valid JSON — no prose, no markdown."
    )),
    HumanMessage(content=(
        "Ticket title: {title}\n"
        "Ticket description: {description}\n\n"
        "Extract only what is explicitly mentioned:\n"
        "{{\n"
        '  "urgency_level": "Critical|High|Medium|Low",\n'
        '  "affected_systems": ["only systems explicitly named in the ticket, or []"],\n'
        '  "error_messages": ["only exact error text copied from the ticket, or []"],\n'
        '  "user_impact": "brief impact description based on what is stated",\n'
        '  "keywords": ["up to 8 technical terms actually mentioned"]\n'
        "}}"
    )),
])

_CLASSIFY_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessage(content=(
        "You are an IT support ticket classifier. "
        "You MUST return a valid JSON object. "
        "CRITICAL: For every field, you MUST copy one of the allowed strings EXACTLY — "
        "do not paraphrase, do not use synonyms, do not invent new values. "
        "If you return a string not in the allowed list the ticket will be miscategorised. "
        "Reply ONLY with valid JSON — no prose, no markdown, no code fences."
    )),
    HumanMessage(content=(
        "Ticket:\nTitle: {title}\nDescription: {description}\n\n"
        "ALLOWED VALUES — copy these strings exactly, character for character:\n"
        "{picklist}\n\n"
        "Field guidance:\n"
        "- issuetype: physical device/peripheral (keyboard/screen/battery/printer/webcam/mouse/trackpad) → Hardware; "
        "app/OS/driver/software install/crash/update → Software; "
        "VPN/tunnel/remote access/wifi/ethernet/internet/firewall/DNS/connectivity → Network; "
        "login/password/permissions/account locked/MFA → Account/Access; "
        "email/Teams/calendar/Outlook/OneDrive → Email/Collaboration; "
        "cloud/server/infra/Azure/AWS/database/backup → Cloud/Infrastructure\n"
        "- subissuetype: pick the single most specific match. Examples: "
        "VPN setup/connect/disconnect → VPN/Remote Access; "
        "wifi not connecting/slow → WiFi; "
        "internet/WAN down → Internet/WAN; "
        "camera/webcam not working → Camera/Webcam; "
        "can't log in/forgot password → Password Reset; "
        "account locked → Account Lockout; "
        "no permission/access denied → Permissions/Access; "
        "app crash/freeze → Crash/BSOD; "
        "install/update app or OS → Application/Software or Operating System; "
        "driver issue → Driver/Firmware; "
        "slow machine → Performance/Speed; "
        "printer → Printer/Scanner; "
        "monitor/screen → Monitor/Display; "
        "keyboard/mouse → Keyboard/Mouse/Peripherals; "
        "laptop/desktop hardware → Laptop/Desktop; "
        "audio/speaker/mic → Audio/Speaker/Microphone; "
        "disk/storage → Storage/Disk; "
        "virus/malware → Security/Virus; "
        "backup → Backup/Restore; "
        "email → Email; "
        "hardware swap/replace → Hardware Replacement; "
        "nothing matches → Other\n"
        "- ticketcategory: something broke or stopped working → Incident; "
        "user wants something new → Service Request; planned system change → Change; "
        "recurring/root-cause investigation → Problem\n"
        "- tickettype: broken thing needs fixing → Break/Fix; new setup or provisioning → New Request; "
        "user asking how to do something → How-To; scheduled upkeep → Maintenance\n"
        "- priority: service down / data loss → Critical; major impact → High; "
        "limited workaround available → Medium; minor nuisance → Low\n\n"
        "Return JSON with these exact keys:\n"
        "{{\n"
        '  "issuetype": "<one string from ISSUETYPE above>",\n'
        '  "subissuetype": "<one string from SUBISSUETYPE above, or null>",\n'
        '  "ticketcategory": "<one string from TICKETCATEGORY above>",\n'
        '  "tickettype": "<one string from TICKETTYPE above>",\n'
        '  "priority": "<one string from PRIORITY above>",\n'
        '  "status": "Open",\n'
        '  "category_label": "<one of: hardware|software|network|security|account_access|email_collaboration|cloud_infrastructure|backup_recovery|billing|general_inquiry>",\n'
        '  "confidence": <number 0.1-1.0>\n'
        "}}"
    )),
])


def classify_node(state: TicketState) -> Dict:
    """
    Two-step classification:
      1. Small model extracts raw metadata (fast, cheap).
      2. Large model classifies against picklist (accurate).
    Also runs semantic search to find similar historical tickets.
    """
    from src.database.db_connection import DatabaseConnection
    from src.utils.picklist_loader import get_picklist_loader

    title = state["title"]
    description = state["description"]
    callbacks = get_callbacks()
    errors = list(state.get("errors", []))

    # ── Step 1: metadata extraction ──────────────────────────────────────────
    extracted_metadata: Dict[str, Any] = {}
    try:
        small = get_small_llm(callbacks)
        chain = _EXTRACT_PROMPT | small
        resp = chain.invoke({"title": title, "description": description})
        extracted_metadata = _parse_json(resp.content) or {}
    except Exception as e:
        log.warning("Metadata extraction failed: %s", e)
        errors.append(f"metadata_extraction: {e}")

    # ── Step 2: classification ───────────────────────────────────────────────
    classification: Dict[str, Any] = {}
    try:
        picklist_loader = get_picklist_loader()
        picklist_text = "\n".join(
            picklist_loader.format_for_prompt(f)
            for f in ["issuetype", "subissuetype", "ticketcategory", "tickettype", "priority"]
        )
        large = get_llm(callbacks)
        chain = _CLASSIFY_PROMPT | large
        resp = chain.invoke({
            "title": title,
            "description": description,
            "metadata": json.dumps(extracted_metadata),
            "picklist": picklist_text,
        })
        raw = _parse_json(resp.content) or {}
        # Detect OpenRouter/provider error responses
        if "error" in raw and "issuetype" not in raw:
            log.warning("CLASSIFY:LLM_ERROR ticket=%s error=%s", ticket_number, raw.get("error"))
            raw = {}
        else:
            log.debug("CLASSIFY:LLM_RAW ticket=%s result=%s", ticket_number, json.dumps(raw)[:300])
        classification = raw
    except Exception as e:
        log.warning("CLASSIFY:LLM_FAILED ticket=%s error=%s", ticket_number, e)
        errors.append(f"classification: {e}")

    # Derive normalised category + priority
    category = classification.get("category_label", "general_inquiry")
    priority_map = {"Critical": "critical", "High": "high", "Medium": "medium", "Low": "low"}
    urgency = extracted_metadata.get("urgency_level", "Medium")
    priority = priority_map.get(urgency, "medium")

    # ── Step 3: semantic search ───────────────────────────────────────────────
    similar_tickets: list = []
    try:
        db = DatabaseConnection()
        similar_tickets = db.find_similar_tickets(title, description) or []
    except Exception as e:
        log.warning("Semantic search failed: %s", e)
        errors.append(f"semantic_search: {e}")

    # Warn when classification model returned all-null (free/fallback model failure)
    if not classification.get("issuetype") and not classification.get("priority"):
        log.warning(
            "classify_node: LLM returned all-null classification for %s (confidence=%.1f) — "
            "using extracted_metadata priority=%s as fallback",
            state["ticket_number"],
            float(classification.get("confidence", 0.0)),
            priority,
        )

    # Persist classification to DB — convert label strings → picklist codes
    # Use derived `priority` (from extracted_metadata urgency) as fallback when LLM returns null.
    # Skip null fields rather than overwriting existing DB values with null.
    try:
        db = DatabaseConnection()
        pl = get_picklist_loader()

        def to_code(field: str, label):
            """Convert a label or code to the stored code.
            Falls back to fuzzy matching when the LLM returns a near-miss label.
            Returns None only when no reasonable match exists."""
            if label is None:
                return None
            label_str = str(label).strip()
            # Try exact label → code reverse lookup
            code = pl.get_value(field, label_str)
            if code:
                return code
            # Already a valid code?
            if label_str in pl.get_all_values_for_field(field):
                return label_str
            # Fuzzy match — catch LLM near-misses like "IT Support" → "General Inquiry"
            import difflib
            all_labels = list(pl.get_all_values_for_field(field).values())
            matches = difflib.get_close_matches(label_str, all_labels, n=1, cutoff=0.4)
            if matches:
                fuzzy_code = pl.get_value(field, matches[0])
                if fuzzy_code:
                    log.warning(
                        "classify_node: fuzzy-matched %r → %r (code=%s) for field=%s",
                        label_str, matches[0], fuzzy_code, field,
                    )
                    return fuzzy_code
            log.warning("classify_node: value %r not in picklist for field=%s — skipping", label_str, field)
            return None

        # Build SET clause dynamically — only update fields that have a value
        effective_priority     = to_code("priority", classification.get("priority")) or priority
        effective_issuetype    = to_code("issuetype", classification.get("issuetype"))
        effective_category     = to_code("ticketcategory", classification.get("ticketcategory"))
        effective_type         = to_code("tickettype", classification.get("tickettype"))
        effective_subissuetype = to_code("subissuetype", classification.get("subissuetype"))

        set_parts = ["priority=%s"]
        params: list = [effective_priority]
        if effective_issuetype:
            set_parts.append("issuetype=%s")
            params.append(effective_issuetype)
        if effective_category:
            set_parts.append("ticketcategory=%s")
            params.append(effective_category)
        if effective_type:
            set_parts.append("tickettype=%s")
            params.append(effective_type)
        if effective_subissuetype:
            set_parts.append("subissuetype=%s")
            params.append(effective_subissuetype)
        params.append(state["ticket_number"])

        db.execute_query(
            f"UPDATE new_tickets SET {', '.join(set_parts)} WHERE ticketnumber=%s",
            tuple(params),
        )
        # Resolve human-readable labels for the flow log
        pl = _get_picklist()
        it_label  = pl.get_label("issuetype",    str(effective_issuetype))    if effective_issuetype    else None
        sub_label = pl.get_label("subissuetype", str(effective_subissuetype)) if effective_subissuetype else None
        pri_label = pl.get_label("priority",     str(effective_priority))     if effective_priority     else None
        flow(log, "TICKET:CLASSIFIED",
             ticket=state["ticket_number"],
             issuetype=it_label or effective_issuetype,
             subissuetype=sub_label or effective_subissuetype,
             priority=pri_label or effective_priority,
             similar=len(similar_tickets))
    except Exception as e:
        log.warning("CLASSIFY:PERSIST_FAILED ticket=%s error=%s", state.get("ticket_number"), e)

    return {
        "extracted_metadata": extracted_metadata,
        "classification": classification,
        "category": category,
        "priority": priority,
        "similar_tickets": similar_tickets,
        "errors": errors,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Node 3 — auto_route_decision  (LLM-based, not keyword rules)
# ─────────────────────────────────────────────────────────────────────────────

_ROUTING_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessage(content=(
        "You are an IT support routing engine. "
        "Decide if this ticket can be resolved by a desktop automation agent running "
        "shell commands, scripts, or system utilities on the user's machine. "
        "Reply ONLY with valid JSON — no prose, no markdown fences."
    )),
    HumanMessage(content=(
        "Ticket:\n"
        "Title: {title}\n"
        "Description: {description}\n"
        "Category: {category}\n"
        "Device OS: {device_os}\n\n"
        "IMPORTANT INSTRUCTIONS:\n"
        "1. Do NOT rely only on what the user says — reason about what the issue COULD be.\n"
        "   Example: 'camera not working on Ubuntu' → almost certainly a driver/kernel module "
        "   issue, even if the user didn't say 'software'. Set can_agent_solve=true.\n"
        "2. If there is ANY plausible software pathway to diagnose or fix the issue "
        "   (even if hardware is also possible), prefer can_agent_solve=true. "
        "   The agent will diagnose first and escalate to human if it hits a dead end.\n"
        "3. Only set can_agent_solve=false when the issue is DEFINITIVELY outside software "
        "   reach (physical damage, procurement, identity verification, multi-system outages).\n\n"
        "Agent CAN handle: camera/audio/display/Bluetooth/printer not working, "
        "disk full, slow performance, service crashes, driver issues, network connectivity, "
        "software installs/updates, permission errors, startup failures, "
        "missing devices, high CPU/memory — anything where CLI, drivers, or config might help.\n\n"
        "Agent CANNOT handle: password resets needing identity verification, "
        "confirmed physical hardware damage (broken screen, liquid damage), "
        "procurement/licensing decisions, account access needing admin approval, "
        "multi-machine outages requiring on-site presence.\n\n"
        "Return:\n"
        "{{\n"
        '  "can_agent_solve": true or false,\n'
        '  "confidence": 0.0 to 1.0,\n'
        '  "reasoning": "one sentence explaining your decision",\n'
        '  "suggested_first_command": "first diagnostic command or null"\n'
        "}}"
    )),
])


def auto_route_decision_node(state: TicketState) -> Dict:
    """
    LLM decides whether this ticket can be resolved by the desktop agent.
    Replaces the old hardcoded keyword-matching rules in auto_resolve.py.
    """
    callbacks = get_callbacks()
    errors    = list(state.get("errors", []))
    can_resolve = False
    cmd_type    = None

    confidence = 0.0
    try:
        # Fetch device OS from agent metadata if a device is connected
        device_id  = state.get("device_id") or ""
        device_os  = "Unknown"
        if device_id:
            try:
                from routes.agent_routes import get_device_metadata
                meta = get_device_metadata(device_id)
                device_os = meta.get("os") or meta.get("platform") or "Unknown"
            except Exception:
                pass

        llm   = get_small_llm(callbacks)
        chain = _ROUTING_PROMPT | llm
        resp  = chain.invoke({
            "title":       state.get("title", ""),
            "description": state.get("description", ""),
            "category":    state.get("category", "general_inquiry"),
            "device_os":   device_os,
        })
        result = _parse_json(resp.content) or {}
        can_resolve = bool(result.get("can_agent_solve", False))
        confidence  = float(result.get("confidence", 0.0))
        reasoning   = result.get("reasoning", "")
        cmd_type    = result.get("suggested_first_command") or None
        route = "AGENT" if can_resolve else "TECH"
        flow(log, f"TICKET:ROUTED:{route}",
             ticket=state.get("ticket_number"),
             confidence=round(confidence, 2),
             device=device_id or None,
             device_os=device_os if device_id else None,
             reason=reasoning[:120] if reasoning else None)
    except Exception as e:
        log.warning("ROUTE:LLM_FAILED ticket=%s — defaulting to tech path: %s",
                    state.get("ticket_number"), e)
        errors.append(f"routing_llm: {e}")

    return {
        "can_auto_resolve": can_resolve,
        "auto_resolve_confidence": confidence,
        "auto_command_type": cmd_type,
        "auto_command_payload": {},
        "agent_connected": False,
        "errors": errors,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Node 4a — agent_task  (auto-resolve path)
# ─────────────────────────────────────────────────────────────────────────────

def agent_task_node(state: TicketState) -> Dict:
    """
    Launch an agentic remediation session for this ticket on the user's device.

    Every agent-routed ticket gets DUAL ASSIGNMENT:
      - A human oversight/fallback tech is assigned to new_tickets.assigned_tech_id
      - An agentic session runs (or ticket queued as Pending Agent if device offline)

    If the device is offline or unknown: marks the ticket 'Pending Agent'.
    When the device reconnects, _auto_start_pending_sessions picks it up.
    If the agent fails: escalates to the already-assigned tech with email notification.
    """
    import asyncio as _asyncio
    from routes.agent_routes import is_agent_connected
    from src.database.db_connection import DatabaseConnection

    device_id     = state.get("device_id") or ""
    ticket_number = state["ticket_number"]
    errors        = list(state.get("errors", []))

    # ── 1. Resolve device from connected agents if not in state ───────────────
    if not device_id:
        try:
            from routes.agent_routes import get_connected_device_for_user
            device_id = get_connected_device_for_user(state.get("user_id", "")) or ""
        except Exception as e:
            log.warning("Device lookup failed: %s", e)

    # Cross-pod fallback: agent may be connected to another pod (in-memory dict is pod-local).
    # If we still have no device_id, check `devices` table for a recently-seen device.
    if not device_id:
        try:
            db_dev = DatabaseConnection()
            rows = db_dev.execute_query(
                "SELECT device_id FROM devices WHERE user_id=%s "
                "AND last_seen > NOW() - INTERVAL '5 minutes' ORDER BY last_seen DESC LIMIT 1",
                (state.get("user_id", ""),),
            )
            if rows:
                device_id = rows[0]["device_id"]
                log.info(
                    "Cross-pod device found for user %s: device=%s (agent on another pod)",
                    state.get("user_id"), device_id,
                )
        except Exception as e:
            log.warning("Cross-pod device DB lookup failed: %s", e)

    # ── 2. Get actual device OS from registered agent metadata ────────────────
    device_os = "Unknown"
    if device_id:
        try:
            from routes.agent_routes import get_device_metadata
            meta = get_device_metadata(device_id)
            device_os = meta.get("os") or meta.get("platform") or "Unknown"
        except Exception:
            pass

    agent_connected = bool(device_id and is_agent_connected(device_id))

    # Cross-pod check: is_agent_connected() is in-memory (per-pod). If False, verify
    # via DB — if the device has last_seen within 3 minutes it's connected on another pod.
    if not agent_connected and device_id:
        try:
            db_cp = DatabaseConnection()
            rows = db_cp.execute_query(
                "SELECT device_id FROM devices WHERE device_id=%s "
                "AND last_seen > NOW() - INTERVAL '3 minutes'",
                (device_id,),
            )
            if rows:
                agent_connected = True
                log.info(
                    "Cross-pod agent detected for ticket=%s device=%s (agent on another pod, last_seen recent)",
                    ticket_number, device_id,
                )
        except Exception as e:
            log.warning("Cross-pod agent check failed: %s", e)

    log.info(
        "agent_task_node: ticket=%s device=%s agent_connected=%s device_os=%s",
        ticket_number, device_id or "none", agent_connected, device_os,
    )

    # ── 3. DUAL ASSIGN: pick oversight/fallback tech and set on the ticket ────
    # Tech can monitor the session live and takes over if agent escalates.
    oversight_tech_id   = None
    oversight_tech_name = None
    oversight_tech_mail = ""
    try:
        from src.agents.smart_ticket_assignment import SmartAssignmentAgent
        db_ov = DatabaseConnection()
        assigner = SmartAssignmentAgent(db_ov)
        oversight_tech_id = assigner.assign_ticket(
            ticket_data={
                "title":        state["title"],
                "description":  state["description"],
                "ticketnumber": ticket_number,
            },
            classification=state.get("classification", {}),
        )
        if oversight_tech_id:
            # Fetch name/mail for notifications
            tech_row = db_ov.execute_query(
                "SELECT tech_name, tech_mail FROM technician_data WHERE tech_id=%s",
                (oversight_tech_id,),
            )
            if tech_row:
                oversight_tech_name = tech_row[0]["tech_name"]
                oversight_tech_mail = tech_row[0].get("tech_mail", "")
            # Write assigned_tech_id to ticket so it appears in tech's dashboard now
            db_ov.execute_query(
                "UPDATE new_tickets SET assigned_tech_id=%s WHERE ticketnumber=%s",
                (oversight_tech_id, ticket_number), fetch=False,
            )
            log.info("Oversight tech assigned: %s (%s) for ticket %s",
                     oversight_tech_name, oversight_tech_id, ticket_number)
    except Exception as e:
        log.warning("Oversight tech assignment failed: %s", e)
        errors.append(f"oversight_assignment: {e}")

    # ── 4. Launch session or queue as Pending Agent ───────────────────────────
    if agent_connected:
        try:
            from src.graph.remediation_graph import run_remediation_session
            from routes.agent_routes import _main_loop, is_agent_auto_mode
            coro = run_remediation_session(
                ticket_number=ticket_number,
                device_id=device_id,
                title=state["title"],
                description=state["description"],
                category=state.get("category", "general_inquiry"),
                user_id=state.get("user_id", ""),
                device_os=device_os,
                auto_mode=is_agent_auto_mode(device_id),
                oversight_tech_id=oversight_tech_id,
                oversight_tech_name=oversight_tech_name,
            )
            if _main_loop and _main_loop.is_running():
                _asyncio.run_coroutine_threadsafe(coro, _main_loop)
                flow(log, "AGENT:SESSION_QUEUED",
                     ticket=ticket_number, device=device_id,
                     oversight=oversight_tech_id, auto_mode=is_agent_auto_mode(device_id))
            else:
                log.warning("AGENT:LOOP_MISSING ticket=%s — session NOT launched", ticket_number)
                agent_connected = False
        except Exception as e:
            log.warning("AGENT:LAUNCH_FAILED ticket=%s error=%s", ticket_number, e)
            errors.append(f"session_launch: {e}")
            agent_connected = False

    if not agent_connected:
        flow(log, "TICKET:PENDING_AGENT", ticket=ticket_number, device=device_id or "none")
        try:
            db = DatabaseConnection()
            if device_id:
                # Persist the resolved device_id so reconnect can find this ticket via Query 1
                db.execute_query(
                    "UPDATE new_tickets SET device_id=%s WHERE ticketnumber=%s AND (device_id IS NULL OR device_id='')",
                    (device_id, ticket_number), fetch=False,
                )
            db.execute_query(
                "UPDATE new_tickets SET status='Pending Agent' WHERE ticketnumber=%s",
                (ticket_number,), fetch=False,
            )
        except Exception as e:
            errors.append(f"pending_status: {e}")

    return {
        "agent_task_id":   None,
        "agent_connected": agent_connected,
        "assigned_tech_id": oversight_tech_id,
        "errors":          errors,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Node 4b — assign_technician  (human path)
# ─────────────────────────────────────────────────────────────────────────────

def assign_technician_node(state: TicketState) -> Dict:
    """Skill-match and assign the ticket to the best available technician."""
    from src.agents.smart_ticket_assignment import SmartAssignmentAgent
    from src.database.db_connection import DatabaseConnection

    errors = list(state.get("errors", []))
    try:
        db = DatabaseConnection()
        agent = SmartAssignmentAgent(db)
        tech_id = agent.assign_ticket(
            ticket_data={
                "title": state["title"],
                "description": state["description"],
                "ticketnumber": state["ticket_number"],
            },
            classification=state.get("classification", {}),
        )
        if tech_id:
            db.execute_query(
                "UPDATE new_tickets SET assigned_tech_id=%s WHERE ticketnumber=%s",
                (tech_id, state["ticket_number"]),
            )
            flow(log, "TICKET:ASSIGNED_TECH", ticket=state["ticket_number"], tech=tech_id)
        else:
            log.warning("ASSIGN:NO_TECH_FOUND ticket=%s", state["ticket_number"])
        return {"assigned_tech_id": tech_id, "errors": errors}
    except Exception as e:
        log.warning("ASSIGN:FAILED ticket=%s error=%s", state["ticket_number"], e)
        return {"assigned_tech_id": None, "errors": errors + [f"assignment: {e}"]}


# ─────────────────────────────────────────────────────────────────────────────
#  Node 5 — generate_resolution
# ─────────────────────────────────────────────────────────────────────────────

_RESOLUTION_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessage(content=(
        "You are an expert IT support engineer writing a resolution guide for a technician.\n"
        "Rules:\n"
        "- Write specific, actionable steps tailored to THIS exact ticket — not generic advice.\n"
        "- If the issue is physical hardware (broken screen, damaged component, replacement needed): "
        "write steps for procurement/replacement, NOT software diagnostics.\n"
        "- If the issue requires on-site presence: say so clearly in step 1.\n"
        "- If similar resolved tickets are provided, reference their specific solutions.\n"
        "- Do NOT include generic steps like 'Check system logs' or 'Reproduce the issue' "
        "unless they directly apply to this specific ticket.\n"
        "- Keep it under 10 steps. Be concise and direct."
    )),
    HumanMessage(content=(
        "Ticket: {title}\n"
        "Description: {description}\n"
        "Issue Type: {category}\n"
        "Priority: {priority}\n\n"
        "Similar resolved tickets:\n{similar}\n\n"
        "Write specific resolution steps for this ticket:"
    )),
])


def generate_resolution_node(state: TicketState) -> Dict:
    """Generate a context-aware resolution guide using the LLM, informed by similar tickets."""
    errors = list(state.get("errors", []))

    similar_text = ""
    for i, t in enumerate(state.get("similar_tickets", [])[:3], 1):
        similar_text += f"\n{i}. Problem: {t.get('title','')}\n   Resolution: {(t.get('resolution') or '(none)')[:300]}\n"
    if not similar_text:
        similar_text = "No similar tickets found."

    resolution = None
    try:
        callbacks = get_callbacks()
        llm = get_llm(callbacks)
        chain = _RESOLUTION_PROMPT | llm
        resp = chain.invoke({
            "title": state["title"],
            "description": state["description"],
            "category": state.get("category", "general_inquiry"),
            "priority": state.get("priority", "medium"),
            "similar": similar_text,
        })
        resolution = resp.content.strip()
        flow(log, "TICKET:RESOLUTION_GENERATED",
             ticket=state["ticket_number"], method="llm", chars=len(resolution))
    except Exception as e:
        log.warning("RESOLUTION:LLM_FAILED ticket=%s error=%s", state["ticket_number"], e)
        errors.append(f"resolution_gen: {e}")
        return {"resolution": None, "errors": errors}

    # Persist the LLM-generated resolution
    try:
        from src.database.db_connection import DatabaseConnection
        db = DatabaseConnection()
        db.execute_query(
            "UPDATE new_tickets SET resolution=%s WHERE ticketnumber=%s",
            (resolution, state["ticket_number"]),
        )
    except Exception as e:
        log.warning("RESOLUTION:PERSIST_FAILED ticket=%s error=%s", state["ticket_number"], e)

    return {"resolution": resolution, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
#  Node 6 — notify
# ─────────────────────────────────────────────────────────────────────────────

def notify_node(state: TicketState) -> Dict:
    """Send email notifications to technician (if assigned) and ticket creator."""
    from src.agents.notification_agent import NotificationAgent

    errors = list(state.get("errors", []))
    sent: list = []

    try:
        agent = NotificationAgent()
        result = agent.send_ticket_notification(
            ticket_number=state["ticket_number"],
            title=state["title"],
            priority=state.get("priority", "medium"),
            category=state.get("category", "general_inquiry"),
            resolution=state.get("resolution", ""),
            assigned_tech_id=state.get("assigned_tech_id"),
            user_id=state.get("user_id"),
            auto_resolved=state.get("can_auto_resolve", False),
            agent_dispatched=state.get("agent_connected", False),
        )
        if result:
            sent = result if isinstance(result, list) else [str(result)]
            flow(log, "TICKET:NOTIFIED",
                 ticket=state["ticket_number"],
                 recipients=len(sent), channels=",".join(sent[:3]))
    except Exception as e:
        log.warning("NOTIFY:FAILED ticket=%s error=%s", state["ticket_number"], e)
        errors.append(f"notify: {e}")

    return {"notifications_sent": sent, "errors": errors}
