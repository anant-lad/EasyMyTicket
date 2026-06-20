"""Picklist and auto-resolve unit tests — pure logic, no HTTP."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_picklist_defaults_load():
    from src.utils.picklist_loader import get_picklist_loader
    pl = get_picklist_loader()
    assert pl.get_label("priority", "1") == "Critical"
    assert pl.get_label("priority", "4") == "Low"
    assert pl.get_label("issuetype", "4") == "Hardware & Equipment"
    assert pl.get_label("issuetype", "5") == "Software & Applications"


def test_picklist_reverse_lookup():
    from src.utils.picklist_loader import get_picklist_loader
    pl = get_picklist_loader()
    assert pl.get_value("priority", "High") == "2"
    assert pl.get_value("issuetype", "Network & Connectivity") == "6"


def test_picklist_normalize_label():
    from src.utils.picklist_loader import get_picklist_loader
    pl = get_picklist_loader()
    assert pl.normalize_label("priority", "2") == "High"
    assert pl.normalize_label("priority", "high") == "High"


def test_picklist_all_fields_present():
    from src.utils.picklist_loader import get_picklist_loader
    pl = get_picklist_loader()
    fields = pl.get_fields()
    assert "issuetype" in fields
    assert "priority" in fields
    assert "ticketcategory" in fields


def test_picklist_format_for_prompt_contains_labels():
    from src.utils.picklist_loader import get_picklist_loader
    pl = get_picklist_loader()
    out = pl.format_for_prompt("priority")
    assert "Critical" in out
    assert "High" in out


def test_auto_resolve_dns_flush():
    from src.graph.auto_resolve import check_auto_resolve
    can, cmd, _, _ = check_auto_resolve(
        "network", "DNS resolution failure",
        "Cannot resolve hostnames — nslookup fails on the network"
    )
    assert can is True
    assert cmd == "flush_dns"


def test_auto_resolve_disk_clear():
    from src.graph.auto_resolve import check_auto_resolve
    can, cmd, _, _ = check_auto_resolve(
        "hardware", "Low disk space warning",
        "Disk is at 92% full, no space left on drive"
    )
    assert can is True
    assert cmd == "clear_temp"


def test_auto_resolve_wifi_diagnostics():
    from src.graph.auto_resolve import check_auto_resolve
    can, cmd, _, _ = check_auto_resolve(
        "network", "WiFi not connecting",
        "Wireless WLAN SSID keeps dropping every few minutes"
    )
    assert can is True
    assert cmd == "wifi_diagnostics"


def test_auto_resolve_rejects_hardware_failure():
    from src.graph.auto_resolve import check_auto_resolve
    can, cmd, _, _ = check_auto_resolve(
        "hardware", "Hard drive failing",
        "Shows bad sectors and physical damage — SMART errors"
    )
    assert can is False
    assert cmd is None
