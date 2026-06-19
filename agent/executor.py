"""
EasyMyTicket Desktop Agent — Sandboxed Command Executor
=======================================================
Supports Linux, macOS (Darwin), and Windows.

Two tiers:
  TIER_1 — Diagnostic / read-only:  run immediately, no approval needed.
  TIER_2 — Fix / write operations:  require is_fix_approved=True flag from
            the agentic session manager (human gate or high-confidence LLM).

Command spec format:
    (linux_cmd, darwin_cmd, windows_cmd)
  Each is a list of tokens. __ARG__ placeholders are substituted from `args`.
"""
import json
import logging
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_OS = platform.system()   # "Linux" | "Darwin" | "Windows"


# ─────────────────────────────────────────────────────────────────────────────
#  Command registry
#  Each entry: (linux_tokens, darwin_tokens, windows_tokens)
#  Use __ARG_name__ for payload substitution.
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
        ["airport", "-I"],       # /System/Library/PrivateFrameworks/.../airport
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
    "diagnostic": ([], [], []),   # handled specially — triggers run_all_diagnostics()
    "ping_gateway": (
        ["ping", "-c", "4", "8.8.8.8"],
        ["ping", "-c", "4", "8.8.8.8"],
        ["ping", "-n", "4", "8.8.8.8"],
    ),
}


# ── TIER 2 — Fix / write operations (require approval in non-agentic mode) ───

TIER2: Dict[str, Tuple[List, List, List]] = {

    # Temp/cache cleanup
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

    # DNS
    "flush_dns": (
        ["sudo", "systemd-resolve", "--flush-caches"],
        ["sudo", "dscacheutil", "-flushcache"],
        ["ipconfig", "/flushdns"],
    ),

    # Service management
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

    # Bluetooth specific
    "restart_bluetooth": (
        ["sudo", "systemctl", "restart", "bluetooth"],
        ["sudo", "pkill", "-f", "bluetoothd"],         # launchd auto-restarts it
        ["powershell", "-NoProfile", "-Command", "Restart-Service bthserv -Force"],
    ),
    "reset_bluetooth_prefs": (
        [],                                             # Linux: no plist equivalent
        ["sudo", "rm", "-f",
         "/Library/Preferences/com.apple.Bluetooth.plist"],
        ["powershell", "-NoProfile", "-Command",
         "Remove-Item 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\bthport\\Parameters\\Devices' "
         "-Recurse -Force -ErrorAction SilentlyContinue"],
    ),

    # Network
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

    # Printing
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

    # Packages / updates
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

    # Drivers
    "scan_and_update_drivers": (
        ["sudo", "dmesg", "--level=err,crit"],
        ["system_profiler", "SPHardwareDataType"],
        ["pnputil", "/scan-devices"],
    ),

    # Security
    "run_av_scan": (
        ["clamscan", "--recursive", "--infected", os.path.expanduser("~")],
        ["mrt"],                                        # macOS Malware Removal Tool
        ["powershell", "-NoProfile", "-Command",
         "Start-MpScan -ScanType QuickScan"],
    ),
    "enable_firewall": (
        ["sudo", "ufw", "enable"],
        ["sudo", "defaults", "write",
         "/Library/Preferences/com.apple.alf", "globalstate", "-int", "1"],
        ["netsh", "advfirewall", "set", "allprofiles", "state", "on"],
    ),

    # File operations (with specific safe paths only — validated below)
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

    # Camera / webcam fixes
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

    # Reset preferences (safe — deletes app plist, not system files)
    "reset_app_prefs": (
        ["find", os.path.expanduser("~/.config"), "-name", "__APP__*", "-delete"],
        ["find", os.path.expanduser("~/Library/Preferences"), "-name", "__APP__*", "-delete"],
        ["powershell", "-NoProfile", "-Command",
         "Remove-Item 'HKCU:\\Software\\__APP__' -Recurse -Force -ErrorAction SilentlyContinue"],
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
#  Absolute blocklist — tokens that must NEVER appear in any command
# ─────────────────────────────────────────────────────────────────────────────

BLOCKED_TOKENS = {
    "rm -rf /", "format", "mkfs", "dd if=/dev/zero", "dd if=/dev/random",
    "wipefs", "shred /dev", "del /s /q c:\\windows", ":(){:|:&};:",
    "$(rm", "`rm", "shutdown", "reboot", "halt", "init 0", "init 6",
    "chmod 777 /", "chown root /", "sudo rm -rf /*",
    "Remove-Item C:\\ -Recurse", "> /dev/sda",
}

# Paths that are absolutely off-limits for delete/modify commands
PROTECTED_PATHS = {
    "/", "/etc", "/boot", "/usr", "/bin", "/sbin", "/lib",
    "C:\\Windows", "C:\\System32", "C:\\Program Files",
    "/System", "/Library/System", "/usr/bin", "/usr/sbin",
}


def _is_blocked(cmd: list) -> bool:
    cmd_str = " ".join(str(t) for t in cmd).lower()
    return any(b.lower() in cmd_str for b in BLOCKED_TOKENS)


def _is_protected_path(path: str) -> bool:
    """Reject operations on system-critical paths."""
    p = Path(path).resolve()
    for protected in PROTECTED_PATHS:
        try:
            p.relative_to(Path(protected).resolve())
            return True
        except ValueError:
            continue
    return False


def _resolve_cmd(template: list, args: dict) -> list:
    """Substitute __ARG_name__ placeholders, keeping tokens that have no placeholder."""
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


# ─────────────────────────────────────────────────────────────────────────────
#  Execution
# ─────────────────────────────────────────────────────────────────────────────

def execute(
    command: str,
    args: Optional[dict] = None,
    timeout: int = 120,
    allow_tier2: bool = False,
) -> Tuple[int, str, str]:
    """
    Execute a named command from TIER1 or TIER2.

    Args:
        command:      Name from TIER1 or TIER2 dict.
        args:         Payload substitutions (e.g. {"service": "nginx"}).
        timeout:      Max seconds to wait for the process.
        allow_tier2:  Set True only in agentic-session context (not one-shot).

    Returns:
        (exit_code, stdout, stderr)
    """
    args = args or {}

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

    # Path safety check for destructive commands
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
            # Wrap non-native commands in PowerShell on Windows
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
    """
    Execute a script provided as a string (used by agentic session for novel fixes).
    script_type: "bash" | "powershell" | "python" | "auto"
    """
    if script_type == "auto":
        script_type = "powershell" if _OS == "Windows" else "bash"

    # Reject scripts with blocked tokens
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


def list_available_commands() -> dict:
    """Return all available commands grouped by tier (useful for LLM system prompt)."""
    return {
        "tier1_diagnostic": sorted(TIER1.keys()),
        "tier2_fix": sorted(TIER2.keys()),
    }
