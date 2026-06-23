#!/usr/bin/env python3
"""
EasyMyTicket Desktop Remediation Agent — Single-File Edition
Version: 1.0.0

Install: see https://github.com/anant-lad/easymyticket-frontend
Config via env vars:
  AGENT_API_URL     wss://your-backend/
  AGENT_USER_ID     your user ID
  AGENT_API_KEY     your personal agent API key (emt_xxxx)
  AGENT_DEVICE_ID   auto-generated UUID (persisted)
"""

# ─────────────────────────────────────────────────────────────────────────────
#  Standard library imports
# ─────────────────────────────────────────────────────────────────────────────
import argparse
import asyncio
import contextlib
import json
import logging
import os
import platform
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import psutil
except ImportError:
    print("Missing dependency: pip install psutil")
    sys.exit(1)

try:
    import websockets
except ImportError:
    print("Missing dependency: pip install websockets")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("agent")

# ─────────────────────────────────────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────────────────────────────────────

_OS = platform.system()   # "Linux" | "Darwin" | "Windows"

_CACHE_DIR      = Path(os.getenv("AGENT_CACHE_DIR", Path.home() / ".easymyticket"))
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
AUTO_MODE       = os.getenv("AGENT_AUTO_MODE", "0") == "1"

# Auth: include ?key= query param so the server can validate this agent
WS_URL = f"{API_URL.rstrip('/')}/ws/agent/{DEVICE_ID}?key={API_KEY}"


# ─────────────────────────────────────────────────────────────────────────────
#  DIAGNOSTICS  (from agent/diagnostics.py)
# ─────────────────────────────────────────────────────────────────────────────

def get_system_info() -> dict:
    """CPU, memory, disk, OS version."""
    try:
        vm   = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "os":              platform.system(),
            "os_version":      platform.version(),
            "hostname":        platform.node(),
            "cpu_count":       psutil.cpu_count(),
            "cpu_percent":     psutil.cpu_percent(interval=1),
            "memory_total_gb": round(vm.total / 1e9, 2),
            "memory_used_pct": vm.percent,
            "disk_total_gb":   round(disk.total / 1e9, 2),
            "disk_free_gb":    round(disk.free  / 1e9, 2),
            "disk_used_pct":   disk.percent,
        }
    except Exception as e:
        log.error("get_system_info failed: %s", e)
        return {"error": str(e)}


def get_network_info() -> dict:
    """Network adapters and connectivity."""
    try:
        adapters = {}
        for name, addrs in psutil.net_if_addrs().items():
            ips = [a.address for a in addrs if a.family.name in ("AF_INET", "AF_INET6")]
            if ips:
                adapters[name] = ips
        return {"adapters": adapters}
    except Exception as e:
        return {"error": str(e)}


def get_running_processes(top_n: int = 20) -> list:
    """Top N processes by CPU usage."""
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x.get("cpu_percent", 0) or 0, reverse=True)
        return procs[:top_n]
    except Exception as e:
        return [{"error": str(e)}]


def get_recent_errors(lines: int = 50) -> list:
    """Fetch recent system error log entries."""
    try:
        if _OS == "Windows":
            cmd = ["wevtutil", "qe", "System", "/c:50", "/rd:true", "/f:text"]
        elif _OS == "Darwin":
            cmd = ["log", "show", "--predicate", "messageType == error",
                   "--last", "1h", "--style", "compact"]
        else:
            cmd = ["journalctl", "-p", "err", "-n", str(lines), "--no-pager"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.stdout.splitlines()[:lines] if result.returncode == 0 else []
    except Exception as e:
        log.warning("get_recent_errors failed: %s", e)
        return []


def ping(host: str) -> dict:
    """Ping a host and return reachability."""
    try:
        flag = "-n" if _OS == "Windows" else "-c"
        result = subprocess.run(
            ["ping", flag, "4", host], capture_output=True, text=True, timeout=10
        )
        return {"host": host, "reachable": result.returncode == 0, "output": result.stdout[:500]}
    except Exception as e:
        return {"host": host, "reachable": False, "error": str(e)}


def run_diagnostics() -> dict:
    """Collect a full diagnostic bundle."""
    return {
        "system":    get_system_info(),
        "network":   get_network_info(),
        "processes": get_running_processes(),
        "errors":    get_recent_errors(),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  EXECUTOR  (from agent/executor.py)
# ─────────────────────────────────────────────────────────────────────────────

# ── TIER 1 — Diagnostic / read-only ──────────────────────────────────────────

TIER1: Dict[str, Tuple[List, List, List]] = {

    # System
    "system_info": (
        ["uname", "-a"],
        ["uname", "-a"],
        ["powershell", "-NoProfile", "-Command",
         "Get-ComputerInfo | Select-Object CsName,OsName,OsVersion,CsProcessors | ConvertTo-Json -Compress"],
    ),
    "uptime": (
        ["uptime"],
        ["uptime"],
        ["powershell", "-NoProfile", "-Command",
         "(Get-Date) - (gcim Win32_OperatingSystem).LastBootUpTime | "
         "Select-Object Days,Hours,Minutes | ConvertTo-Json -Compress"],
    ),
    "process_list": (
        ["ps", "aux", "--sort=-%cpu"],
        ["ps", "aux"],
        ["powershell", "-NoProfile", "-Command",
         "Get-Process | Sort-Object CPU -Descending | Select-Object -First 20 Name,Id,CPU,WorkingSet | "
         "ConvertTo-Json -Compress"],
    ),

    # Disk
    "disk_usage": (
        ["df", "-h"],
        ["df", "-h"],
        ["powershell", "-NoProfile", "-Command",
         "Get-PSDrive -PSProvider FileSystem | ConvertTo-Json -Compress"],
    ),
    "find_large_files": (
        ["find", "__PATH__", "-type", "f", "-size", "+__SIZE__M", "-not", "-path", "*/proc/*"],
        ["find", "__PATH__", "-type", "f", "-size", "+__SIZE__M"],
        ["powershell", "-NoProfile", "-Command",
         "Get-ChildItem '__PATH__' -Recurse -File -ErrorAction SilentlyContinue | "
         "Where-Object Length -GT __SIZEB__ | Sort-Object Length -Desc | Select-Object -First 20 "
         "FullName,@{N='SizeMB';E={[math]::Round($_.Length/1MB,1)}} | ConvertTo-Json -Compress"],
    ),
    "disk_health": (
        ["sudo", "smartctl", "-H", "/dev/sda"],
        ["diskutil", "verifyDisk", "/"],
        ["chkdsk", "C:", "/scan"],
    ),

    # Memory
    "memory_usage": (
        ["free", "-h"],
        ["vm_stat"],
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_OperatingSystem | "
         "Select-Object TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json -Compress"],
    ),
    "memory_top_procs": (
        ["ps", "aux", "--sort=-%mem"],
        ["ps", "aux", "-o", "pid,%mem,rss,comm"],
        ["powershell", "-NoProfile", "-Command",
         "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 "
         "Name,Id,@{N='MB';E={[math]::Round($_.WorkingSet64/1MB,1)}} | ConvertTo-Json -Compress"],
    ),

    # CPU
    "cpu_usage": (
        ["top", "-bn1", "-c"],
        ["top", "-l", "1", "-n", "10"],
        ["powershell", "-NoProfile", "-Command",
         "Get-Process | Sort-Object CPU -Descending | Select-Object -First 10 Name,Id,CPU | "
         "ConvertTo-Json -Compress"],
    ),

    # Services
    "service_status": (
        ["systemctl", "status", "__SERVICE__"],
        ["launchctl", "list", "__SERVICE__"],
        ["powershell", "-NoProfile", "-Command",
         "Get-Service '__SERVICE__' | Select-Object Name,Status,StartType | ConvertTo-Json -Compress"],
    ),
    "list_failed_services": (
        ["systemctl", "list-units", "--type=service", "--state=failed", "--no-pager"],
        ["launchctl", "list"],
        ["powershell", "-NoProfile", "-Command",
         "Get-Service | Where-Object {$_.StartType -eq 'Automatic' -and $_.Status -ne 'Running'} | "
         "Select-Object DisplayName,Status | ConvertTo-Json -Compress"],
    ),

    # Network
    "network_interfaces": (
        ["ip", "addr"],
        ["ifconfig"],
        ["ipconfig", "/all"],
    ),
    "dns_lookup": (
        ["nslookup", "__HOST__"],
        ["nslookup", "__HOST__"],
        ["nslookup", "__HOST__"],
    ),
    "ping": (
        ["ping", "-c", "4", "__HOST__"],
        ["ping", "-c", "4", "__HOST__"],
        ["ping", "-n", "4", "__HOST__"],
    ),
    "traceroute": (
        ["traceroute", "-m", "15", "__HOST__"],
        ["traceroute", "-m", "15", "__HOST__"],
        ["tracert", "-h", "15", "__HOST__"],
    ),
    "netstat": (
        ["ss", "-tulnp"],
        ["netstat", "-an"],
        ["netstat", "-an"],
    ),
    "route_table": (
        ["ip", "route"],
        ["netstat", "-rn"],
        ["route", "print"],
    ),

    # Bluetooth
    "bluetooth_status": (
        ["bluetoothctl", "show"],
        ["system_profiler", "SPBluetoothDataType"],
        ["powershell", "-NoProfile", "-Command",
         "Get-PnpDevice -Class Bluetooth | Select-Object FriendlyName,Status,InstanceId | "
         "ConvertTo-Json -Compress"],
    ),

    # WiFi
    "wifi_status": (
        ["nmcli", "dev", "wifi"],
        ["airport", "-I"],
        ["netsh", "wlan", "show", "interfaces"],
    ),

    # Drivers / hardware
    "driver_errors": (
        ["dmesg", "--level=err,crit", "-T"],
        ["log", "show", "--predicate",
         "subsystem == 'com.apple.iokit' AND messageType == 17",
         "--last", "24h", "--style", "compact"],
        ["powershell", "-NoProfile", "-Command",
         "Get-PnpDevice | Where-Object {$_.Status -ne 'OK'} | "
         "Select-Object FriendlyName,Status | ConvertTo-Json -Compress"],
    ),
    "hardware_info": (
        ["lshw", "-short"],
        ["system_profiler", "SPHardwareDataType"],
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_ComputerSystem | ConvertTo-Json -Compress"],
    ),
    "usb_devices": (
        ["lsusb"],
        ["system_profiler", "SPUSBDataType"],
        ["powershell", "-NoProfile", "-Command",
         "Get-PnpDevice -Class USB | ConvertTo-Json -Compress"],
    ),

    # Camera / webcam
    "camera_list": (
        ["bash", "-c", "ls -la /dev/video* 2>/dev/null || echo 'No video devices found'"],
        ["bash", "-c", "system_profiler SPCameraDataType 2>/dev/null"],
        ["powershell", "-NoProfile", "-Command",
         "Get-PnpDevice | Where-Object {$_.FriendlyName -like '*camera*' -or $_.FriendlyName -like '*webcam*'} | "
         "Select-Object FriendlyName,Status,InstanceId | ConvertTo-Json -Compress"],
    ),
    "camera_driver_check": (
        ["bash", "-c", "lsmod | grep -i 'uvc\\|video\\|camera'; dmesg | grep -i 'uvc\\|video\\|camera' | tail -20"],
        ["bash", "-c", "log show --predicate \"subsystem contains 'camera'\" --last 1h --style compact 2>/dev/null | tail -30"],
        ["powershell", "-NoProfile", "-Command",
         "Get-PnpDevice | Where-Object {$_.FriendlyName -match 'camera|webcam'} | "
         "Select-Object FriendlyName,Status,ConfigManagerErrorCode | ConvertTo-Json -Compress"],
    ),
    "camera_in_use_check": (
        ["bash", "-c", "fuser /dev/video* 2>/dev/null && echo 'Camera in use' || echo 'Camera not in use by any process'"],
        ["bash", "-c", "lsof +c 0 2>/dev/null | grep -i 'video\\|camera' | head -10 || echo 'No camera locks found'"],
        ["powershell", "-NoProfile", "-Command",
         "Get-Process | Where-Object {$_.Modules.ModuleName -like '*camera*'} | "
         "Select-Object Name,Id,Description | ConvertTo-Json -Compress"],
    ),
    "camera_permission_check": (
        ["bash", "-c", "groups | grep -i 'video\\|camera' && echo 'User has video group' || echo 'User NOT in video group'"],
        ["bash", "-c", "tccutil status Camera 2>/dev/null || echo 'TCC check unavailable'"],
        ["powershell", "-NoProfile", "-Command",
         "Get-AppxPackage | Where-Object {$_.PackageFullName -match 'camera'} | "
         "Select-Object Name,Status | ConvertTo-Json -Compress"],
    ),
    "camera_v4l2_info": (
        ["bash", "-c", "v4l2-ctl --list-devices 2>/dev/null || echo 'v4l2-ctl not available'"],
        ["bash", "-c", "echo 'v4l2 not applicable on macOS'"],
        ["powershell", "-NoProfile", "-Command", "echo 'v4l2 not applicable on Windows'"],
    ),
    "camera_usb_detect": (
        ["bash", "-c", "lsusb | grep -i -E 'camera|webcam|imaging|uvc|video' || echo 'No camera USB device found'"],
        ["bash", "-c", "system_profiler SPCameraDataType 2>/dev/null | head -10 || echo 'No camera found'"],
        ["powershell", "-NoProfile", "-Command",
         "Get-PnpDevice | Where-Object {$_.FriendlyName -match 'camera|webcam'} | "
         "Select-Object Status,FriendlyName | ConvertTo-Json -Compress"],
    ),
    "camera_dmesg_errors": (
        ["bash", "-c", "dmesg | grep -i -E 'uvc|camera|video|webcam' | tail -30 || echo 'No camera messages in dmesg'"],
        ["bash", "-c", "log show --predicate \"subsystem contains 'camera'\" --last 1h 2>/dev/null | tail -20 || echo 'No camera log entries'"],
        ["powershell", "-NoProfile", "-Command",
         "Get-EventLog System -Source *camera* -Newest 10 -ErrorAction SilentlyContinue | ConvertTo-Json -Compress"],
    ),
    "camera_module_info": (
        ["bash", "-c", "modinfo uvcvideo 2>/dev/null | head -8 || echo 'uvcvideo module not found'"],
        ["bash", "-c", "echo 'macOS uses AVFoundation — no kernel module check needed'"],
        ["powershell", "-NoProfile", "-Command", "echo 'Windows camera uses built-in UVC class driver'"],
    ),

    # Security
    "firewall_status": (
        ["ufw", "status"],
        ["defaults", "read", "/Library/Preferences/com.apple.alf", "globalstate"],
        ["netsh", "advfirewall", "show", "allprofiles"],
    ),
    "startup_items": (
        ["systemctl", "list-unit-files", "--type=service", "--state=enabled"],
        ["launchctl", "list"],
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_StartupCommand | Select-Object Name,Command,Location | "
         "ConvertTo-Json -Compress"],
    ),
    "av_status": (
        ["clamscan", "--version"],
        ["spctl", "--status"],
        ["powershell", "-NoProfile", "-Command",
         "Get-MpComputerStatus | Select-Object AMServiceEnabled,RealTimeProtectionEnabled,"
         "AntivirusSignatureLastUpdated,QuickScanAge | ConvertTo-Json -Compress"],
    ),

    # Logs
    "system_log": (
        ["journalctl", "-n", "100", "--no-pager"],
        ["log", "show", "--last", "1h", "--style", "compact"],
        ["powershell", "-NoProfile", "-Command",
         "Get-EventLog -LogName System -Newest 50 | Select-Object TimeGenerated,EntryType,Message | "
         "ConvertTo-Json -Compress"],
    ),
    "service_log": (
        ["journalctl", "-u", "__SERVICE__", "-n", "100", "--no-pager"],
        ["log", "show", "--predicate", "subsystem == '__SERVICE__'",
         "--last", "1h", "--style", "compact"],
        ["powershell", "-NoProfile", "-Command",
         "Get-EventLog -LogName Application -Source '__SERVICE__' -Newest 50 | "
         "Select-Object TimeGenerated,EntryType,Message | ConvertTo-Json -Compress"],
    ),
    "crash_log": (
        ["journalctl", "-p", "err", "-n", "50", "--no-pager"],
        ["log", "show", "--predicate",
         "messageType == 17 OR messageType == 16", "--last", "24h", "--style", "compact"],
        ["powershell", "-NoProfile", "-Command",
         "Get-EventLog -LogName Application -EntryType Error -Newest 30 | "
         "Select-Object TimeGenerated,Source,Message | ConvertTo-Json -Compress"],
    ),
    "bluetooth_log": (
        ["journalctl", "-u", "bluetooth", "--since", "1 hour ago", "--no-pager"],
        ["log", "show", "--predicate", "subsystem == 'com.apple.bluetooth'",
         "--last", "1h", "--style", "compact"],
        ["powershell", "-NoProfile", "-Command",
         "Get-EventLog -LogName System -Source 'BTHUSB*' -Newest 30 | "
         "Select-Object TimeGenerated,EntryType,Message | ConvertTo-Json -Compress"],
    ),

    # Software
    "installed_packages": (
        ["dpkg", "--get-selections"],
        ["brew", "list"],
        ["winget", "list"],
    ),
    "pending_updates": (
        ["apt-get", "--just-print", "upgrade"],
        ["softwareupdate", "-l"],
        ["winget", "upgrade", "--include-unknown"],
    ),
    "app_version": (
        ["dpkg", "-l", "__APP__"],
        ["brew", "info", "__APP__"],
        ["winget", "show", "__APP__"],
    ),

    # Battery
    "battery_status": (
        ["upower", "-i", "/org/freedesktop/UPower/devices/battery_BAT0"],
        ["pmset", "-g", "batt"],
        ["powershell", "-NoProfile", "-Command",
         "Get-WmiObject Win32_Battery | Select-Object EstimatedChargeRemaining,BatteryStatus | "
         "ConvertTo-Json -Compress"],
    ),

    # Printing
    "printer_status": (
        ["lpstat", "-p"],
        ["lpstat", "-p"],
        ["powershell", "-NoProfile", "-Command",
         "Get-Printer | Select-Object Name,PrinterStatus | ConvertTo-Json -Compress"],
    ),
    "print_queue": (
        ["lpq"],
        ["lpq"],
        ["powershell", "-NoProfile", "-Command",
         "Get-PrintJob -PrinterName * | Select-Object JobStatus,DocumentName | ConvertTo-Json -Compress"],
    ),

    # General diagnostic
    "diagnostic": ([], [], []),   # handled specially
    "ping_gateway": (
        ["ping", "-c", "4", "8.8.8.8"],
        ["ping", "-c", "4", "8.8.8.8"],
        ["ping", "-n", "4", "8.8.8.8"],
    ),

    # Web / network research
    "web_search": ([], [], []),   # sentinel: routed to _web_search()

    "check_url": (
        ["bash", "-c", "curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 10 '__URL__'"],
        ["bash", "-c", "curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 10 '__URL__'"],
        ["powershell", "-NoProfile", "-Command",
         "$url=\"__URL__\"; "
         "try { $r=(Invoke-WebRequest $url -Method Head -TimeoutSec 10 -UseBasicParsing); "
         "$r.StatusCode } catch { $_.Exception.Response.StatusCode.value__ }"],
    ),

    "verify_download": (
        ["bash", "-c", "ls -lh '__PATH__' 2>/dev/null && file '__PATH__' && sha256sum '__PATH__'"],
        ["bash", "-c", "ls -lh '__PATH__' 2>/dev/null && file '__PATH__' && shasum -a 256 '__PATH__'"],
        ["powershell", "-NoProfile", "-Command",
         "if (Test-Path '__PATH__') { Get-Item '__PATH__' | Select-Object Name,Length,LastWriteTime; "
         "(Get-FileHash '__PATH__' -Algorithm SHA256).Hash }"],
    ),
}


# ── TIER 2 — Fix / write operations ──────────────────────────────────────────

TIER2: Dict[str, Tuple[List, List, List]] = {

    "clear_temp": (
        ["find", "/tmp", "-maxdepth", "1", "-mindepth", "1", "-not", "-name", ".", "-delete"],
        ["find", "/private/tmp", "-maxdepth", "1", "-mindepth", "1", "-not", "-name", ".", "-delete"],
        ["powershell", "-NoProfile", "-Command",
         "Remove-Item \"$env:TEMP\\*\" -Recurse -Force -ErrorAction SilentlyContinue"],
    ),
    "clear_app_cache": (
        ["find", "__CACHE_PATH__", "-type", "f", "-delete"],
        ["find", "__CACHE_PATH__", "-type", "f", "-delete"],
        ["powershell", "-NoProfile", "-Command",
         "Remove-Item '__CACHE_PATH__' -Recurse -Force -ErrorAction SilentlyContinue"],
    ),

    "flush_dns": (
        ["sudo", "systemd-resolve", "--flush-caches"],
        ["sudo", "dscacheutil", "-flushcache"],
        ["ipconfig", "/flushdns"],
    ),

    "restart_service": (
        ["sudo", "systemctl", "restart", "__SERVICE__"],
        ["sudo", "launchctl", "kickstart", "-k", "system/__SERVICE__"],
        ["powershell", "-NoProfile", "-Command", "Restart-Service '__SERVICE__' -Force"],
    ),
    "stop_service": (
        ["sudo", "systemctl", "stop", "__SERVICE__"],
        ["sudo", "launchctl", "stop", "__SERVICE__"],
        ["powershell", "-NoProfile", "-Command", "Stop-Service '__SERVICE__' -Force"],
    ),
    "start_service": (
        ["sudo", "systemctl", "start", "__SERVICE__"],
        ["sudo", "launchctl", "start", "__SERVICE__"],
        ["powershell", "-NoProfile", "-Command", "Start-Service '__SERVICE__'"],
    ),

    "restart_bluetooth": (
        ["sudo", "systemctl", "restart", "bluetooth"],
        ["sudo", "pkill", "-f", "bluetoothd"],
        ["powershell", "-NoProfile", "-Command", "Restart-Service bthserv -Force"],
    ),
    "reset_bluetooth_prefs": (
        [],
        ["sudo", "rm", "-f", "/Library/Preferences/com.apple.Bluetooth.plist"],
        ["powershell", "-NoProfile", "-Command",
         "Remove-Item 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\bthport\\Parameters\\Devices' "
         "-Recurse -Force -ErrorAction SilentlyContinue"],
    ),

    "reset_network_adapter": (
        ["sudo", "ip", "link", "set", "__IFACE__", "down"],
        ["sudo", "ifconfig", "__IFACE__", "down"],
        ["powershell", "-NoProfile", "-Command",
         "Disable-NetAdapter -Name '__IFACE__' -Confirm:$false"],
    ),
    "bring_up_adapter": (
        ["sudo", "ip", "link", "set", "__IFACE__", "up"],
        ["sudo", "ifconfig", "__IFACE__", "up"],
        ["powershell", "-NoProfile", "-Command",
         "Enable-NetAdapter -Name '__IFACE__' -Confirm:$false"],
    ),
    "release_renew_dhcp": (
        ["sudo", "dhclient", "-r"],
        ["sudo", "ipconfig", "set", "en0", "DHCP"],
        ["ipconfig", "/release"],
    ),

    "restart_print_spooler": (
        ["sudo", "systemctl", "restart", "cups"],
        ["sudo", "launchctl", "kickstart", "-k", "system/org.cups.cupsd"],
        ["powershell", "-NoProfile", "-Command", "Restart-Service Spooler -Force"],
    ),
    "clear_print_queue": (
        ["sudo", "cancel", "-a"],
        ["sudo", "cancel", "-a"],
        ["powershell", "-NoProfile", "-Command",
         "Get-PrintJob -PrinterName * | Remove-PrintJob"],
    ),

    "install_package": (
        ["sudo", "apt-get", "install", "-y", "__PACKAGE__"],
        ["brew", "install", "__PACKAGE__"],
        ["winget", "install", "--id", "__PACKAGE__", "--silent",
         "--accept-package-agreements", "--accept-source-agreements"],
    ),
    "update_packages": (
        ["sudo", "apt-get", "upgrade", "-y"],
        ["brew", "upgrade"],
        ["winget", "upgrade", "--all", "--silent",
         "--accept-package-agreements", "--accept-source-agreements"],
    ),
    "install_system_updates": (
        ["sudo", "apt-get", "upgrade", "-y"],
        ["softwareupdate", "-ia"],
        ["powershell", "-NoProfile", "-Command",
         "Install-WindowsUpdate -AcceptAll -AutoReboot:$false"],
    ),

    "scan_and_update_drivers": (
        ["sudo", "dmesg", "--level=err,crit"],
        ["system_profiler", "SPHardwareDataType"],
        ["pnputil", "/scan-devices"],
    ),

    "run_av_scan": (
        ["clamscan", "--recursive", "--infected", os.path.expanduser("~")],
        ["mrt"],
        ["powershell", "-NoProfile", "-Command",
         "Start-MpScan -ScanType QuickScan"],
    ),
    "enable_firewall": (
        ["sudo", "ufw", "enable"],
        ["sudo", "defaults", "write",
         "/Library/Preferences/com.apple.alf", "globalstate", "-int", "1"],
        ["netsh", "advfirewall", "set", "allprofiles", "state", "on"],
    ),

    "delete_file": (
        ["rm", "-f", "__PATH__"],
        ["rm", "-f", "__PATH__"],
        ["powershell", "-NoProfile", "-Command",
         "Remove-Item '__PATH__' -Force -ErrorAction SilentlyContinue"],
    ),
    "delete_directory": (
        ["rm", "-rf", "__PATH__"],
        ["rm", "-rf", "__PATH__"],
        ["powershell", "-NoProfile", "-Command",
         "Remove-Item '__PATH__' -Recurse -Force -ErrorAction SilentlyContinue"],
    ),

    "reload_camera_driver": (
        ["bash", "-c", "sudo modprobe -r uvcvideo && sudo modprobe uvcvideo && echo 'Camera driver reloaded'"],
        ["bash", "-c", "echo 'macOS camera driver reload not needed; reset TCC instead'"],
        ["powershell", "-NoProfile", "-Command",
         "pnputil /restart-device (Get-PnpDevice | Where-Object {$_.FriendlyName -match 'camera'}).InstanceId"],
    ),
    "add_user_to_video_group": (
        ["bash", "-c", "sudo usermod -aG video $(whoami) && echo 'Added to video group. Please log out and back in.'"],
        ["bash", "-c", "echo 'macOS does not use video group'"],
        ["powershell", "-NoProfile", "-Command", "echo 'Windows does not use video group'"],
    ),
    "kill_camera_process": (
        ["bash", "-c", "fuser -k /dev/video* 2>/dev/null && echo 'Killed processes using camera' || echo 'No camera locks to kill'"],
        ["bash", "-c", "lsof +c 0 2>/dev/null | grep -i video | awk '{print $2}' | xargs kill -9 2>/dev/null && echo 'Killed camera processes' || echo 'None'"],
        ["powershell", "-NoProfile", "-Command",
         "Get-Process | Where-Object {$_.Modules.ModuleName -like '*camera*'} | Stop-Process -Force"],
    ),

    "download_file": (
        ["bash", "-c",
         "mkdir -p \"$(dirname '__PATH__')\" && "
         "wget -q --show-progress --timeout=120 --tries=3 -O '__PATH__' '__URL__' && "
         "echo 'Downloaded to __PATH__'"],
        ["bash", "-c",
         "mkdir -p \"$(dirname '__PATH__')\" && "
         "curl -L --max-time 120 --retry 3 -o '__PATH__' '__URL__' && "
         "echo 'Downloaded to __PATH__'"],
        ["powershell", "-NoProfile", "-Command",
         "New-Item -ItemType Directory -Force -Path (Split-Path '__PATH__') | Out-Null; "
         "Invoke-WebRequest -Uri '__URL__' -OutFile '__PATH__' -TimeoutSec 120 -UseBasicParsing; "
         "Write-Output 'Downloaded to __PATH__'"],
    ),

    "install_from_file": (
        ["bash", "-c",
         "case '__PATH__' in "
         "*.deb) sudo apt-get install -y '__PATH__' 2>/dev/null || sudo dpkg -i '__PATH__';; "
         "*.rpm) sudo rpm -ivh '__PATH__';; "
         "*.sh)  sudo bash '__PATH__';; "
         "*.run) sudo chmod +x '__PATH__' && sudo '__PATH__';; "
         "*) echo 'Unknown file type: __PATH__'; exit 1;; "
         "esac"],
        ["bash", "-c",
         "case '__PATH__' in "
         "*.pkg) sudo installer -pkg '__PATH__' -target /;; "
         "*.dmg) MOUNT=$(hdiutil attach '__PATH__' | grep /Volumes | awk '{print $NF}') && "
                "echo \"Mounted at $MOUNT\" && "
                "APP=$(find \"$MOUNT\" -maxdepth 1 -name '*.app' 2>/dev/null | head -1) && "
                "if [ -n \"$APP\" ]; then cp -r \"$APP\" /Applications/ && echo 'Installed to /Applications'; fi && "
                "hdiutil detach \"$MOUNT\" -quiet && echo 'Unmounted';; "
         "*.sh)  sudo bash '__PATH__';; "
         "*) echo 'Unknown file type: __PATH__'; exit 1;; "
         "esac"],
        ["powershell", "-NoProfile", "-Command",
         "$p='__PATH__'; "
         "if ($p -match '\\.msi$') { Start-Process msiexec.exe -ArgumentList '/i',$p,'/quiet','/norestart' -Wait } "
         "elseif ($p -match '\\.exe$') { Start-Process $p -ArgumentList '/S','/silent','/quiet' -Wait } "
         "elseif ($p -match '\\.ps1$') { & powershell -ExecutionPolicy Bypass -File $p } "
         "else { Write-Error 'Unknown file type' }"],
    ),

    "open_browser": (
        ["bash", "-c", "xdg-open '__URL__' 2>/dev/null || sensible-browser '__URL__' 2>/dev/null || echo 'No browser found; visit __URL__ manually'"],
        ["bash", "-c", "open '__URL__'"],
        ["powershell", "-NoProfile", "-Command", "Start-Process '__URL__'"],
    ),

    "reset_app_prefs": (
        ["find", os.path.expanduser("~/.config"), "-name", "__APP__*", "-delete"],
        ["find", os.path.expanduser("~/Library/Preferences"), "-name", "__APP__*", "-delete"],
        ["powershell", "-NoProfile", "-Command",
         "Remove-Item 'HKCU:\\Software\\__APP__' -Recurse -Force -ErrorAction SilentlyContinue"],
    ),
}


BLOCKED_TOKENS = {
    "rm -rf /", "format", "mkfs", "dd if=/dev/zero", "dd if=/dev/random",
    "wipefs", "shred /dev", "del /s /q c:\\windows", ":(){:|:&};:",
    "$(rm", "`rm", "shutdown", "reboot", "halt", "init 0", "init 6",
    "chmod 777 /", "chown root /", "sudo rm -rf /*",
    "Remove-Item C:\\ -Recurse", "> /dev/sda",
}

PROTECTED_PATHS = {
    "/", "/etc", "/boot", "/usr", "/bin", "/sbin", "/lib",
    "C:\\Windows", "C:\\System32", "C:\\Program Files",
    "/System", "/Library/System", "/usr/bin", "/usr/sbin",
}


def _web_search(query: str, max_results: int = 6) -> Tuple[int, str, str]:
    if not query:
        return 1, "", "web_search requires a 'QUERY' argument"

    results = []

    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            for hit in ddgs.text(query, max_results=max_results):
                results.append({
                    "title":   hit.get("title", ""),
                    "url":     hit.get("href", ""),
                    "snippet": hit.get("body", "")[:300],
                })
    except ImportError:
        pass
    except Exception as e:
        log.warning("ddgs search failed: %s", e)

    if not results:
        try:
            import urllib.request, urllib.parse
            url = "https://api.duckduckgo.com/?q={}&format=json&no_html=1&skip_disambig=1".format(
                urllib.parse.quote_plus(query)
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            if data.get("AbstractText"):
                results.append({
                    "title":   data.get("Heading", ""),
                    "url":     data.get("AbstractURL", ""),
                    "snippet": data["AbstractText"][:300],
                })
            for topic in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(topic, dict) and topic.get("FirstURL"):
                    results.append({
                        "title":   topic.get("Text", "")[:80],
                        "url":     topic["FirstURL"],
                        "snippet": topic.get("Text", "")[:200],
                    })
        except Exception as e:
            log.warning("DDG API fallback failed: %s", e)

    if not results:
        note = ("No results found. Install the ddgs package on the agent machine "
                "(`pip install ddgs`) for better search results.")
        return 0, json.dumps({"query": query, "results": [], "note": note}), ""

    output = json.dumps({"query": query, "result_count": len(results), "results": results}, indent=2)
    log.info("web_search(%r) → %d results", query, len(results))
    return 0, output, ""


def _is_blocked(cmd: list) -> bool:
    cmd_str = " ".join(str(t) for t in cmd).lower()
    return any(b.lower() in cmd_str for b in BLOCKED_TOKENS)


def _is_protected_path(path: str) -> bool:
    p = Path(path).resolve()
    for protected in PROTECTED_PATHS:
        try:
            p.relative_to(Path(protected).resolve())
            return True
        except ValueError:
            continue
    return False


def _resolve_cmd(template: list, args: dict) -> list:
    result = []
    for token in template:
        t = str(token)
        for key, val in args.items():
            placeholder = f"__{key.upper()}__"
            if placeholder in t:
                t = t.replace(placeholder, str(val))
        result.append(t)
    return result


def _pick_os(spec: Tuple[List, List, List]) -> List:
    linux_cmd, darwin_cmd, windows_cmd = spec
    if _OS == "Windows":
        return list(windows_cmd)
    if _OS == "Darwin":
        return list(darwin_cmd)
    return list(linux_cmd)


def execute(
    command: str,
    args: Optional[dict] = None,
    timeout: int = 120,
    allow_tier2: bool = False,
) -> Tuple[int, str, str]:
    args = args or {}

    if command == "web_search":
        query = args.get("QUERY") or args.get("query") or ""
        return _web_search(query)

    if command in TIER1:
        spec = TIER1[command]
    elif command in TIER2:
        if not allow_tier2:
            return 1, "", (
                f"Command '{command}' is a Tier-2 fix operation and requires "
                "explicit approval (allow_tier2=True in an agentic session)."
            )
        spec = TIER2[command]
    else:
        return 1, "", f"Unknown command: '{command}'"

    cmd = _resolve_cmd(_pick_os(spec), args)

    if not cmd:
        return 0, f"Command '{command}' is not applicable on {_OS}.", ""

    # On Linux, make every top-level `sudo` non-interactive so the agent never
    # hangs waiting for a password when running headlessly under systemd.
    # Sudoers must grant NOPASSWD for the relevant commands; without that the
    # call fails immediately with a clear error instead of blocking forever.
    if _OS == "Linux" and cmd[0] == "sudo" and "-n" not in cmd:
        cmd.insert(1, "-n")

    if command in ("delete_file", "delete_directory", "clear_app_cache", "reset_app_prefs"):
        path = args.get("PATH") or args.get("path") or args.get("CACHE_PATH") or ""
        if path and _is_protected_path(path):
            return 1, "", f"Blocked: path '{path}' is system-protected."

    if _is_blocked(cmd):
        log.error("Blocked command attempt: %s", cmd)
        return 1, "", f"Blocked by security policy: {cmd}"

    log.info("Executing %s [%s]: %s", command, _OS, " ".join(cmd[:6]))

    try:
        if _OS == "Windows" and not cmd[0].lower() in ("powershell", "netsh", "ipconfig",
                                                        "ping", "nslookup", "tracert",
                                                        "chkdsk", "winget", "pnputil",
                                                        "net", "route", "chkdsk"):
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command"] + cmd

        run_kwargs = dict(capture_output=True, text=True, timeout=timeout)
        if _OS == "Windows":
            run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(cmd, **run_kwargs)
        log.info("Command %s exit=%d", command, result.returncode)
        return result.returncode, result.stdout[:20_000], result.stderr[:4_000]

    except subprocess.TimeoutExpired:
        log.warning("Command %s timed out after %ss", command, timeout)
        return 124, "", f"Timed out after {timeout}s"
    except Exception as e:
        log.error("Command %s failed: %s", command, e)
        return 1, "", str(e)


def execute_script(
    script_content: str,
    script_type: str = "auto",
    args: Optional[dict] = None,
    timeout: int = 300,
) -> Tuple[int, str, str]:
    if script_type == "auto":
        script_type = "powershell" if _OS == "Windows" else "bash"

    if _is_blocked(script_content.split()):
        return 1, "", "Script blocked by security policy."

    suffix_map = {"bash": ".sh", "powershell": ".ps1", "python": ".py"}
    suffix = suffix_map.get(script_type, ".sh")

    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(script_content)
        script_path = f.name

    try:
        if script_type == "bash":
            cmd = ["bash", script_path]
        elif script_type == "powershell":
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-File", script_path]
        elif script_type == "python":
            cmd = ["python3" if _OS != "Windows" else "python", script_path]
        else:
            return 1, "", f"Unknown script_type: {script_type}"

        run_kwargs = dict(capture_output=True, text=True, timeout=timeout)
        if _OS == "Windows":
            run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(cmd, **run_kwargs)
        return result.returncode, result.stdout[:20_000], result.stderr[:4_000]
    except subprocess.TimeoutExpired:
        return 124, "", f"Script timed out after {timeout}s"
    except Exception as e:
        return 1, "", str(e)
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def execute_auto(
    command: str,
    args: Optional[dict] = None,
    timeout: int = 120,
) -> Tuple[int, str, str]:
    args = args or {}

    if command == "shell":
        cmd_str = args.get("command", "")
        if not cmd_str:
            return 1, "", "No command provided"
        log.info("AUTO shell [%s]: %s", _OS, cmd_str[:120])
        try:
            if _OS == "Windows":
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd_str],
                    capture_output=True, text=True, timeout=timeout,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                result = subprocess.run(
                    cmd_str, shell=True, executable="/bin/bash",
                    capture_output=True, text=True, timeout=timeout,
                )
            log.info("AUTO shell exit=%d", result.returncode)
            return result.returncode, result.stdout[:50_000], result.stderr[:10_000]
        except subprocess.TimeoutExpired:
            return 124, "", f"Timed out after {timeout}s"
        except Exception as e:
            return 1, "", str(e)

    elif command == "read_file":
        path = Path(args.get("path", ""))
        try:
            content = path.read_text(errors="replace")
            return 0, content[:100_000], ""
        except Exception as e:
            return 1, "", str(e)

    elif command == "write_file":
        path = Path(args.get("path", ""))
        content = args.get("content", "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return 0, f"Wrote {len(content)} bytes to {path}", ""
        except Exception as e:
            return 1, "", str(e)

    elif command == "append_file":
        path = Path(args.get("path", ""))
        content = args.get("content", "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                f.write(content)
            return 0, f"Appended {len(content)} bytes to {path}", ""
        except Exception as e:
            return 1, "", str(e)

    elif command == "list_dir":
        path = Path(args.get("path", "."))
        try:
            entries = []
            for e in sorted(path.iterdir()):
                try:
                    stat = e.stat()
                    kind = "d" if e.is_dir() else "f"
                    entries.append(f"{kind} {stat.st_size:>12,}  {e.name}")
                except OSError:
                    entries.append(f"? {'?':>12}  {e.name}")
            return 0, "\n".join(entries) or "(empty)", ""
        except Exception as e:
            return 1, "", str(e)

    elif command == "create_dir":
        path = Path(args.get("path", ""))
        try:
            path.mkdir(parents=True, exist_ok=True)
            return 0, f"Created directory: {path}", ""
        except Exception as e:
            return 1, "", str(e)

    elif command == "delete_path":
        path = Path(args.get("path", ""))
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            return 0, f"Deleted: {path}", ""
        except Exception as e:
            return 1, "", str(e)

    elif command == "move_path":
        src = Path(args.get("src", ""))
        dst = Path(args.get("dst", ""))
        try:
            shutil.move(str(src), str(dst))
            return 0, f"Moved {src} → {dst}", ""
        except Exception as e:
            return 1, "", str(e)

    elif command == "copy_path":
        src = Path(args.get("src", ""))
        dst = Path(args.get("dst", ""))
        try:
            if src.is_dir():
                shutil.copytree(str(src), str(dst))
            else:
                shutil.copy2(str(src), str(dst))
            return 0, f"Copied {src} → {dst}", ""
        except Exception as e:
            return 1, "", str(e)

    elif command in ("web_search", "web_search_auto"):
        query = args.get("query") or args.get("QUERY") or ""
        return _web_search(query)

    elif command == "download":
        url  = args.get("url") or args.get("URL") or ""
        path = args.get("path") or args.get("PATH") or ""
        try:
            if _OS == "Windows":
                cmd_str = f'Invoke-WebRequest -Uri "{url}" -OutFile "{path}" -UseBasicParsing'
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", cmd_str],
                    capture_output=True, text=True, timeout=300,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            elif shutil.which("wget"):
                result = subprocess.run(
                    ["wget", "-q", "-O", path, url],
                    capture_output=True, text=True, timeout=300,
                )
            else:
                result = subprocess.run(
                    ["curl", "-L", "-o", path, url],
                    capture_output=True, text=True, timeout=300,
                )
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            return 1, "", str(e)

    return execute(command, args, timeout=timeout, allow_tier2=True)


# ─────────────────────────────────────────────────────────────────────────────
#  OFFLINE QUEUE  (from agent/offline_queue.py)
# ─────────────────────────────────────────────────────────────────────────────

_QUEUE_PATH = Path(os.getenv("AGENT_QUEUE_PATH", str(_CACHE_DIR / "offline_queue.db")))

_QUEUE_DDL = """
CREATE TABLE IF NOT EXISTS pending_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    attempts    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pending_tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    status      TEXT    DEFAULT 'queued'
);
"""


@contextmanager
def _queue_db():
    _QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_QUEUE_PATH), check_same_thread=False)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_QUEUE_DDL)
        con.commit()
        yield con
    finally:
        con.close()


def enqueue_result(task_id: str, payload: Dict[str, Any]) -> None:
    with _queue_db() as con:
        con.execute(
            "INSERT INTO pending_results (task_id, payload, created_at) VALUES (?, ?, ?)",
            (task_id, json.dumps(payload), datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
    log.debug("Queued offline result for task %s", task_id)


def enqueue_task(task: Dict[str, Any]) -> None:
    task_id = task.get("task_id", "?")
    with _queue_db() as con:
        con.execute(
            "INSERT INTO pending_tasks (task_id, payload, created_at) VALUES (?, ?, ?)",
            (task_id, json.dumps(task), datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
    log.debug("Queued offline task %s for later execution", task_id)


def get_pending_results(limit: int = 50) -> List[Dict]:
    with _queue_db() as con:
        rows = con.execute(
            "SELECT id, task_id, payload FROM pending_results ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"_row_id": r["id"], "task_id": r["task_id"], **json.loads(r["payload"])} for r in rows]


def delete_result(row_id: int) -> None:
    with _queue_db() as con:
        con.execute("DELETE FROM pending_results WHERE id = ?", (row_id,))
        con.commit()


def get_pending_tasks(limit: int = 20) -> List[Dict]:
    with _queue_db() as con:
        rows = con.execute(
            "SELECT id, payload FROM pending_tasks WHERE status='queued' ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"_row_id": r["id"], **json.loads(r["payload"])} for r in rows]


def mark_task_done(row_id: int) -> None:
    with _queue_db() as con:
        con.execute("UPDATE pending_tasks SET status='done' WHERE id=?", (row_id,))
        con.commit()


async def drain_to_websocket(ws) -> int:
    pending = get_pending_results()
    if not pending:
        return 0

    log.info("Draining %d offline result(s) to backend", len(pending))
    flushed = 0
    for item in pending:
        row_id = item.pop("_row_id")
        try:
            await ws.send(json.dumps(item))
            delete_result(row_id)
            flushed += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            log.warning("Could not flush result %d: %s — will retry later", row_id, e)
            break

    if flushed:
        log.info("Flushed %d offline result(s)", flushed)
    return flushed


async def drain_pending_tasks(handle_task_fn) -> int:
    pending = get_pending_tasks()
    if not pending:
        return 0

    log.info("Executing %d offline-queued task(s)", len(pending))
    executed = 0
    for item in pending:
        row_id = item.pop("_row_id")
        try:
            await handle_task_fn(item, ws=None)
            mark_task_done(row_id)
            executed += 1
        except Exception as e:
            log.warning("Offline task %s failed: %s", item.get("task_id"), e)

    return executed


def queue_stats() -> Dict[str, int]:
    with _queue_db() as con:
        results_cnt = con.execute("SELECT COUNT(*) FROM pending_results").fetchone()[0]
        tasks_cnt = con.execute(
            "SELECT COUNT(*) FROM pending_tasks WHERE status='queued'"
        ).fetchone()[0]
    return {"pending_results": results_cnt, "pending_tasks": tasks_cnt}


# ─────────────────────────────────────────────────────────────────────────────
#  REPORTER  (from agent/reporter.py)
# ─────────────────────────────────────────────────────────────────────────────

_REPORT_FILE    = _CACHE_DIR / "last_daily_report.json"
_SENT_FLAG_FILE = _CACHE_DIR / "last_report_sent_date.txt"


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def report_already_sent_today() -> bool:
    if not _SENT_FLAG_FILE.exists():
        return False
    try:
        return _SENT_FLAG_FILE.read_text().strip() == _today_str()
    except OSError:
        return False


def mark_report_sent():
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _SENT_FLAG_FILE.write_text(_today_str())
    except OSError as e:
        log.warning("Could not write sent flag: %s", e)


async def send_pending_report(
    api_url: str,
    api_key: str,
    device_id: str,
    force: bool = False,
) -> bool:
    if not force and report_already_sent_today():
        log.debug("Daily report already sent today — skipping")
        return True

    if not _REPORT_FILE.exists():
        log.debug("No cached report found at %s", _REPORT_FILE)
        return False

    try:
        report = json.loads(_REPORT_FILE.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Could not read cached report: %s", e)
        return False

    base = api_url.replace("wss://", "https://").replace("ws://", "http://").rstrip("/")
    url  = f"{base}/api/agent/daily-report"

    headers: dict = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=report, headers=headers)
            if resp.status_code in (200, 201, 202):
                log.info("Daily report uploaded successfully (status=%d)", resp.status_code)
                mark_report_sent()
                return True
            else:
                log.warning("Daily report upload failed: HTTP %d — %s",
                            resp.status_code, resp.text[:200])
                return False
    except Exception as e:
        log.warning("Daily report upload error (will retry next connection): %s", e)
        return False


async def run_and_send(
    api_url: str,
    api_key: str,
    device_id: str,
    user_id: str,
) -> bool:
    log.info("Starting scheduled daily scan for device_id=%s", device_id)
    run_daily_scan(device_id=device_id, user_id=user_id)
    return await send_pending_report(api_url, api_key, device_id)


# ─────────────────────────────────────────────────────────────────────────────
#  DAILY MONITOR  (from agent/monitor.py)
# ─────────────────────────────────────────────────────────────────────────────

_LAST_REPORT_FILE = _CACHE_DIR / "last_daily_report.json"

LOW_DISK_PCT = float(os.getenv("MON_LOW_DISK_PCT", "10"))
HIGH_MEM_PCT = float(os.getenv("MON_HIGH_MEM_PCT", "85"))
HIGH_CPU_PCT = float(os.getenv("MON_HIGH_CPU_PCT", "90"))
LOW_BATT_PCT = float(os.getenv("MON_LOW_BATT_PCT", "20"))


def _mon_run(cmd: list, timeout: int = 15) -> str:
    try:
        if _OS == "Windows":
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()
    except Exception:
        return ""


def _mon_run_ps(script: str, timeout: int = 20) -> str:
    return _mon_run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)


def _check_disk() -> Dict:
    partitions = []
    issues = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            continue
        free_pct = 100 - usage.percent
        entry = {
            "mountpoint": part.mountpoint,
            "device":     part.device,
            "total_gb":   round(usage.total / 1024**3, 1),
            "used_gb":    round(usage.used  / 1024**3, 1),
            "free_gb":    round(usage.free  / 1024**3, 1),
            "used_pct":   round(usage.percent, 1),
            "free_pct":   round(free_pct, 1),
            "status":     "critical" if free_pct < 5 else "warning" if free_pct < LOW_DISK_PCT else "ok",
        }
        partitions.append(entry)
        if free_pct < LOW_DISK_PCT:
            issues.append(f"{part.mountpoint} only {free_pct:.1f}% free ({entry['free_gb']} GB)")
    return {"partitions": partitions, "issues": issues}


def _check_memory() -> Dict:
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    used_pct = mem.percent
    issues = []
    if used_pct > HIGH_MEM_PCT:
        issues.append(f"RAM at {used_pct:.1f}% ({mem.used // 1024**3} GB used of {mem.total // 1024**3} GB)")
    return {
        "total_gb":     round(mem.total / 1024**3, 1),
        "used_gb":      round(mem.used  / 1024**3, 1),
        "used_pct":     round(used_pct, 1),
        "swap_used_gb": round(swap.used / 1024**3, 1),
        "status":       "warning" if used_pct > HIGH_MEM_PCT else "ok",
        "issues":       issues,
    }


def _check_cpu() -> Dict:
    cpu_pct = psutil.cpu_percent(interval=3)
    count   = psutil.cpu_count(logical=True)
    issues  = []
    if cpu_pct > HIGH_CPU_PCT:
        issues.append(f"CPU at {cpu_pct:.1f}% — possible runaway process")
    try:
        top_procs = sorted(psutil.process_iter(["pid", "name", "cpu_percent"]),
                           key=lambda p: p.info.get("cpu_percent") or 0, reverse=True)[:5]
        top = [{"pid": p.info["pid"], "name": p.info["name"],
                "cpu_pct": round(p.info.get("cpu_percent") or 0, 1)} for p in top_procs]
    except Exception:
        top = []
    return {
        "cpu_count":     count,
        "cpu_pct":       round(cpu_pct, 1),
        "status":        "warning" if cpu_pct > HIGH_CPU_PCT else "ok",
        "top_processes": top,
        "issues":        issues,
    }


def _check_battery() -> Dict:
    try:
        batt = psutil.sensors_battery()
        if batt is None:
            return {"present": False}
        issues = []
        if not batt.power_plugged and batt.percent < LOW_BATT_PCT:
            issues.append(f"Battery low: {batt.percent:.0f}% and not charging")
        return {
            "present": True,
            "percent": round(batt.percent, 1),
            "plugged": batt.power_plugged,
            "status":  "warning" if issues else "ok",
            "issues":  issues,
        }
    except Exception:
        return {"present": False}


def _check_services() -> Dict:
    failed: List[str] = []

    if _OS == "Linux":
        out = _mon_run(["systemctl", "list-units", "--type=service",
                        "--state=failed", "--no-legend", "--no-pager"])
        failed = [line.split()[0] for line in out.splitlines() if line.strip()]

    elif _OS == "Darwin":
        out = _mon_run(["launchctl", "list"])
        for line in out.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 3:
                exit_code = parts[1].strip()
                label     = parts[2].strip()
                if exit_code not in ("-", "0") and label.startswith("com.apple."):
                    failed.append(label)

    elif _OS == "Windows":
        out = _mon_run_ps(
            "Get-Service | Where-Object {$_.StartType -eq 'Automatic' -and "
            "$_.Status -ne 'Running'} | Select-Object -ExpandProperty DisplayName"
        )
        failed = [l.strip() for l in out.splitlines() if l.strip()]

    issues = [f"Service failed: {s}" for s in failed[:10]]
    return {"failed": failed[:20], "issues": issues}


def _check_drivers() -> Dict:
    errors: List[str] = []

    if _OS == "Linux":
        details = _mon_run(["dmesg", "--level=err,crit", "-T"], timeout=10)
        if details:
            lines = [l for l in details.splitlines() if l.strip()][:20]
            if lines:
                errors.append(f"{len(lines)} kernel error(s) in dmesg")

    elif _OS == "Darwin":
        details = _mon_run(["log", "show", "--predicate",
                            "subsystem == 'com.apple.iokit' AND messageType == 17",
                            "--last", "24h", "--style", "compact"], timeout=20)
        lines = [l for l in details.splitlines() if l.strip()][:10]
        if lines:
            errors.append(f"{len(lines)} IOKit error(s) in last 24h")

    elif _OS == "Windows":
        out = _mon_run_ps(
            "Get-PnpDevice | Where-Object {$_.Status -ne 'OK'} | "
            "Select-Object FriendlyName,Status | ConvertTo-Json -Compress"
        )
        try:
            devs = json.loads(out) if out else []
            if isinstance(devs, dict):
                devs = [devs]
            for d in devs:
                errors.append(f"Device error: {d.get('FriendlyName','?')} ({d.get('Status','?')})")
        except Exception:
            pass

    return {"errors": errors[:20], "issues": errors[:10]}


def _check_network_mon() -> Dict:
    adapters = []
    issues   = []
    try:
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        for iface, s in stats.items():
            if iface.lower().startswith("lo"):
                continue
            ips = [a.address for a in addrs.get(iface, [])
                   if ":" not in a.address and a.address != "127.0.0.1"]
            entry = {"name": iface, "up": s.isup, "speed": s.speed, "ips": ips}
            adapters.append(entry)
            if not s.isup:
                issues.append(f"Network adapter {iface!r} is down")
    except Exception:
        pass
    return {"adapters": adapters, "issues": issues}


def _check_security_mon() -> Dict:
    issues: List[str] = []
    details: Dict[str, Any] = {}

    if _OS == "Darwin":
        fw = _mon_run(["defaults", "read", "/Library/Preferences/com.apple.alf", "globalstate"])
        details["firewall"] = fw.strip() == "1"
        if fw.strip() == "0":
            issues.append("macOS Firewall is disabled")
        fv = _mon_run(["fdesetup", "status"])
        details["filevault"] = "FileVault is On" in fv
        if "FileVault is Off" in fv:
            issues.append("FileVault disk encryption is disabled")

    elif _OS == "Linux":
        ufw = _mon_run(["ufw", "status"])
        details["firewall"] = "Status: active" in ufw
        if "inactive" in ufw:
            issues.append("UFW firewall is inactive")

    elif _OS == "Windows":
        out = _mon_run_ps(
            "Get-MpComputerStatus | Select-Object AMServiceEnabled,RealTimeProtectionEnabled | "
            "ConvertTo-Json -Compress"
        )
        try:
            st = json.loads(out) if out else {}
            details["defender_service"] = st.get("AMServiceEnabled", False)
            details["realtime_protection"] = st.get("RealTimeProtectionEnabled", False)
            if not st.get("RealTimeProtectionEnabled"):
                issues.append("Windows Defender real-time protection is disabled")
        except Exception:
            pass

    return {"details": details, "issues": issues}


def _check_updates_mon() -> Dict:
    updates: List[str] = []

    if _OS == "Darwin":
        out = _mon_run(["softwareupdate", "-l"], timeout=30)
        for line in out.splitlines():
            if line.strip().startswith("*"):
                updates.append(line.strip().lstrip("* "))

    elif _OS == "Linux":
        _mon_run(["apt-get", "update", "-qq"], timeout=30)
        out = _mon_run(["apt-get", "--just-print", "upgrade"], timeout=20)
        for line in out.splitlines():
            if line.startswith("Inst "):
                updates.append(line.split()[1])

    elif _OS == "Windows":
        out = _mon_run_ps("winget upgrade --include-unknown | Select-String '^[A-Za-z]'", timeout=60)
        lines = [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("-")]
        updates = lines[:30]

    issues = [f"{len(updates)} software update(s) pending"] if updates else []
    return {"pending": updates[:30], "count": len(updates), "issues": issues}


def _system_info_mon() -> Dict:
    uname = platform.uname()
    return {
        "os":       _OS,
        "hostname": platform.node(),
        "platform": platform.platform(),
        "arch":     uname.machine,
        "python":   platform.python_version(),
        "uptime_h": round((datetime.now().timestamp() - psutil.boot_time()) / 3600, 1),
    }


def run_daily_scan(device_id: str = "", user_id: str = "") -> Dict[str, Any]:
    log.info("Starting daily system scan (OS=%s)", _OS)
    scan_time = datetime.now(timezone.utc).isoformat()

    report: Dict[str, Any] = {
        "schema_version": 3,
        "device_id":      device_id,
        "user_id":        user_id,
        "scan_time":      scan_time,
        "system":         _system_info_mon(),
        "disk":           _check_disk(),
        "memory":         _check_memory(),
        "cpu":            _check_cpu(),
        "battery":        _check_battery(),
        "services":       _check_services(),
        "drivers":        _check_drivers(),
        "network":        _check_network_mon(),
        "security":       _check_security_mon(),
        "updates":        _check_updates_mon(),
    }

    all_issues: List[str] = []
    for section in ["disk", "memory", "cpu", "battery", "services",
                    "drivers", "network", "security", "updates"]:
        all_issues.extend(report[section].get("issues", []))
    report["all_issues"]  = all_issues
    report["issue_count"] = len(all_issues)

    log.info("Daily scan complete — %d issue(s) found", len(all_issues))

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _LAST_REPORT_FILE.write_text(json.dumps(report, indent=2, default=str))
        log.info("Report cached at %s", _LAST_REPORT_FILE)
    except Exception as e:
        log.warning("Could not cache report locally: %s", e)

    return report


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN — WebSocket loop  (from agent/main.py)
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


async def handle_tool_call(msg: dict, ws) -> None:
    session_id  = msg.get("session_id", "")
    call_id     = msg.get("call_id", "")
    command     = msg.get("command", "")
    args        = msg.get("args") or {}
    allow_tier2 = bool(msg.get("allow_tier2", True))
    script      = msg.get("script")
    script_type = msg.get("script_type", "auto")

    log.info("tool_call [session=%s call=%s]: %s args=%s",
             session_id[:8], call_id[:8], command, args)

    server_auto_mode = bool(msg.get("auto_mode", False))
    use_auto = AUTO_MODE and server_auto_mode

    try:
        if script:
            exit_code, stdout, stderr = execute_script(script, script_type=script_type, args=args)
        elif command == "diagnostic":
            data = run_diagnostics()
            exit_code, stdout, stderr = 0, json.dumps(data, default=str), ""
        elif command == "ping":
            data = ping(args.get("host", "8.8.8.8"))
            exit_code = 0 if data.get("reachable") else 1
            stdout, stderr = json.dumps(data), ""
        elif use_auto:
            exit_code, stdout, stderr = execute_auto(command, args)
        else:
            exit_code, stdout, stderr = execute(command, args, allow_tier2=allow_tier2)

    except Exception as e:
        log.error("tool_call error [%s]: %s", command, e)
        exit_code, stdout, stderr = 1, "", str(e)

    result = {
        "type":         "tool_result",
        "session_id":   session_id,
        "call_id":      call_id,
        "exit_code":    exit_code,
        "output":       stdout[:20_000],
        "stderr":       stderr[:4_000],
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await ws.send(json.dumps(result))
    except Exception as e:
        log.error("Could not send tool_result for call_id=%s: %s", call_id, e)


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
        device_info["auto_mode"] = AUTO_MODE
        await ws.send(json.dumps({"type": "register", "device": device_info}))
        log.info("Registered: device_id=%s os=%s host=%s auto_mode=%s",
                 DEVICE_ID, platform.system(), platform.node(), AUTO_MODE)

        await send_pending_report(API_URL, API_KEY, DEVICE_ID)

        stats = queue_stats()
        if stats.get("pending_results", 0) > 0:
            await drain_to_websocket(ws)
        if stats.get("pending_tasks", 0) > 0:
            await drain_pending_tasks(handle_task)

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
                await handle_task(msg, ws)

            elif msg_type == "tool_call":
                asyncio.create_task(handle_tool_call(msg, ws))

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


async def run_with_reconnect():
    stop_event = asyncio.Event()

    def _signal_handler():
        log.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
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


async def _run_daily_scan_mode():
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


# ─────────────────────────────────────────────────────────────────────────────
#  CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

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
        AUTO_MODE = True
        os.environ["AGENT_AUTO_MODE"] = "1"
        log.info("AUTO MODE ENABLED — AI has full system access on this machine")

    if args.scan:
        asyncio.run(_run_daily_scan_mode())
    else:
        asyncio.run(run_with_reconnect())
