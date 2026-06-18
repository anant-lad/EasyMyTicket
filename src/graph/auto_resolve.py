"""
Auto-resolve rules — decides whether a ticket can be fixed automatically
by the desktop remediation agent without human involvement.

Rules are deliberately conservative: only route to auto-resolve when we are
highly confident the fix is safe and reversible.
"""
from typing import Dict, Optional, Tuple

# Maps (category, keyword_set) → (command_type, payload)
# The graph checks these in order; first match wins.
_RULES: list = [
    # ── Network / connectivity ────────────────────────────────────────────────
    {
        "categories": {"network"},
        "keywords": {"dns", "resolve", "cannot reach", "name resolution", "nslookup"},
        "command_type": "flush_dns",
        "payload": {},
        "description": "Flush DNS cache to fix name-resolution failures",
    },
    {
        "categories": {"network"},
        "keywords": {"wifi", "wireless", "wi-fi", "wlan", "ssid"},
        "command_type": "wifi_diagnostics",
        "payload": {},
        "description": "Run Wi-Fi diagnostics",
    },
    {
        "categories": {"network"},
        "keywords": {"ping", "unreachable", "timeout", "gateway", "connectivity"},
        "command_type": "ping_gateway",
        "payload": {"host": "8.8.8.8"},
        "description": "Run gateway ping diagnostic",
    },

    # ── Hardware / disk ───────────────────────────────────────────────────────
    {
        "categories": {"hardware"},
        "keywords": {"disk", "storage", "space", "full", "low disk", "no space"},
        "command_type": "clear_temp",
        "payload": {},
        "description": "Clear temporary files to free disk space",
    },
    {
        "categories": {"hardware"},
        "keywords": {"printer", "print", "spooler", "printing", "print queue"},
        "command_type": "restart_print_spooler",
        "payload": {},
        "description": "Restart print spooler service to fix stuck print jobs",
    },
    {
        "categories": {"hardware"},
        "keywords": {"driver", "device driver", "outdated driver", "missing driver"},
        "command_type": "driver_update_scan",
        "payload": {},
        "description": "Scan for and apply pending driver updates",
    },

    # ── Software / performance ────────────────────────────────────────────────
    {
        "categories": {"software", "performance"},
        "keywords": {"slow", "temp", "cache", "junk", "cleanup", "performance"},
        "command_type": "clear_temp",
        "payload": {},
        "description": "Clear temp/cache files to improve performance",
    },
    {
        "categories": {"software"},
        "keywords": {"service", "crashed", "not running", "stopped service", "failed service"},
        "command_type": "check_services",
        "payload": {},
        "description": "List and report failed system services",
    },
    {
        "categories": {"software"},
        "keywords": {"dependency", "missing dll", "missing library", "import error", "module not found"},
        "command_type": "install_dependency",
        "payload": {},
        "description": "Scan and install missing system dependencies",
    },

    # ── Security ──────────────────────────────────────────────────────────────
    {
        "categories": {"security"},
        "keywords": {"virus", "malware", "scan", "antivirus", "threat", "infected"},
        "command_type": "run_av_scan",
        "payload": {},
        "description": "Trigger antivirus / malware scan",
    },
]

# Category + keyword threshold: require at least 1 keyword match
_MIN_KEYWORD_MATCHES = 1


def check_auto_resolve(
    category: str,
    title: str,
    description: str,
) -> Tuple[bool, Optional[str], Optional[Dict], Optional[str]]:
    """
    Determine whether this ticket can be auto-resolved by the desktop agent.

    Returns:
        (can_resolve, command_type, command_payload, description)
        command_type is None when can_resolve is False.
    """
    text = f"{title} {description}".lower()

    for rule in _RULES:
        if category not in rule["categories"]:
            continue
        matches = sum(1 for kw in rule["keywords"] if kw in text)
        if matches >= _MIN_KEYWORD_MATCHES:
            return True, rule["command_type"], rule["payload"], rule["description"]

    return False, None, None, None
