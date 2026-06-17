"""
EasyMyTicket Desktop Agent — Daily Morning System Monitor
==========================================================
Runs ONCE per day at startup (triggered by OS scheduler: systemd timer /
launchd / Windows Scheduled Task set to 06:00).

Responsibilities:
  1. Perform a full system health scan (disk, memory, CPU, services, drivers,
     network, security, software updates, AV, battery).
  2. Save the scan result locally as JSON.
  3. Attempt to POST the report to the server; if offline, retry when the
     agent next connects (reporter.py handles the retry).

Run directly:
    python -m agent.monitor          # run scan now, print report, exit
"""
import json
import logging
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    import psutil
except ImportError:
    print("Missing: pip install psutil")
    sys.exit(1)

log = logging.getLogger("agent.monitor")

_OS = platform.system()          # "Linux" | "Darwin" | "Windows"
_CACHE_DIR = Path(os.getenv("AGENT_CACHE_DIR", Path.home() / ".easymyticket"))
_LAST_REPORT_FILE = _CACHE_DIR / "last_daily_report.json"

# ── Thresholds (env-overridable) ──────────────────────────────────────────────
LOW_DISK_PCT  = float(os.getenv("MON_LOW_DISK_PCT",  "10"))   # % free
HIGH_MEM_PCT  = float(os.getenv("MON_HIGH_MEM_PCT",  "85"))   # % used
HIGH_CPU_PCT  = float(os.getenv("MON_HIGH_CPU_PCT",  "90"))   # % used (sustained)
LOW_BATT_PCT  = float(os.getenv("MON_LOW_BATT_PCT",  "20"))   # % charge


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run(cmd: list, timeout: int = 15) -> str:
    """Run a command and return stdout; empty string on any error."""
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


def _run_ps(script: str, timeout: int = 20) -> str:
    """Run a PowerShell script snippet (Windows only)."""
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)


# ─────────────────────────────────────────────────────────────────────────────
#  Individual checks (all return dicts)
# ─────────────────────────────────────────────────────────────────────────────

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
        "total_gb":  round(mem.total / 1024**3, 1),
        "used_gb":   round(mem.used  / 1024**3, 1),
        "used_pct":  round(used_pct, 1),
        "swap_used_gb": round(swap.used / 1024**3, 1),
        "status":    "warning" if used_pct > HIGH_MEM_PCT else "ok",
        "issues":    issues,
    }


def _check_cpu() -> Dict:
    # 3-second sample — reasonable for a once-daily scan
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
        "cpu_count": count,
        "cpu_pct":   round(cpu_pct, 1),
        "status":    "warning" if cpu_pct > HIGH_CPU_PCT else "ok",
        "top_processes": top,
        "issues":    issues,
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
            "present":    True,
            "percent":    round(batt.percent, 1),
            "plugged":    batt.power_plugged,
            "status":     "warning" if issues else "ok",
            "issues":     issues,
        }
    except Exception:
        return {"present": False}


def _check_services() -> Dict:
    failed: List[str] = []

    if _OS == "Linux":
        out = _run(["systemctl", "list-units", "--type=service",
                    "--state=failed", "--no-legend", "--no-pager"])
        failed = [line.split()[0] for line in out.splitlines() if line.strip()]

    elif _OS == "Darwin":
        # launchd: list services that exited with non-zero
        out = _run(["launchctl", "list"])
        for line in out.splitlines()[1:]:   # skip header
            parts = line.split("\t")
            if len(parts) >= 3:
                exit_code = parts[1].strip()
                label     = parts[2].strip()
                if exit_code not in ("-", "0") and label.startswith("com.apple."):
                    failed.append(label)

    elif _OS == "Windows":
        out = _run_ps(
            "Get-Service | Where-Object {$_.StartType -eq 'Automatic' -and "
            "$_.Status -ne 'Running'} | Select-Object -ExpandProperty DisplayName"
        )
        failed = [l.strip() for l in out.splitlines() if l.strip()]

    issues = [f"Service failed: {s}" for s in failed[:10]]
    return {"failed": failed[:20], "issues": issues}


def _check_drivers() -> Dict:
    errors: List[str] = []
    details = ""

    if _OS == "Linux":
        details = _run(["dmesg", "--level=err,crit", "-T"], timeout=10)
        if details:
            lines = [l for l in details.splitlines() if l.strip()][:20]
            if lines:
                errors.append(f"{len(lines)} kernel error(s) in dmesg")

    elif _OS == "Darwin":
        # system_profiler gives hardware overview; look for errors in kernel log
        details = _run(["log", "show", "--predicate",
                        "subsystem == 'com.apple.iokit' AND messageType == 17",
                        "--last", "24h", "--style", "compact"], timeout=20)
        lines = [l for l in details.splitlines() if l.strip()][:10]
        if lines:
            errors.append(f"{len(lines)} IOKit error(s) in last 24h")

    elif _OS == "Windows":
        out = _run_ps(
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

    issues = errors[:10]
    return {"errors": errors[:20], "issues": issues}


def _check_network() -> Dict:
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
            entry = {
                "name":  iface,
                "up":    s.isup,
                "speed": s.speed,
                "ips":   ips,
            }
            adapters.append(entry)
            if not s.isup:
                issues.append(f"Network adapter {iface!r} is down")
    except Exception:
        pass
    return {"adapters": adapters, "issues": issues}


def _check_bluetooth() -> Dict:
    result: Dict[str, Any] = {}
    issues: List[str] = []

    if _OS == "Darwin":
        out = _run(["/usr/bin/system_profiler", "SPBluetoothDataType"], timeout=15)
        result["raw"] = out[:2000]
        if "State: Off" in out or "Bluetooth: Not Available" in out:
            issues.append("Bluetooth is Off or unavailable")
        elif "State: On" in out:
            result["state"] = "on"

    elif _OS == "Linux":
        out = _run(["bluetoothctl", "show"], timeout=10)
        result["raw"] = out[:1000]
        if "Powered: no" in out:
            issues.append("Bluetooth powered off")
        elif "Powered: yes" in out:
            result["state"] = "on"

    elif _OS == "Windows":
        out = _run_ps(
            "Get-PnpDevice -Class Bluetooth | Select FriendlyName,Status | ConvertTo-Json -Compress"
        )
        result["raw"] = out[:1000]
        try:
            devs = json.loads(out) if out else []
            if isinstance(devs, dict):
                devs = [devs]
            for d in devs:
                if d.get("Status", "OK") != "OK":
                    issues.append(f"Bluetooth device error: {d.get('FriendlyName','?')}")
        except Exception:
            pass

    result["issues"] = issues
    return result


def _check_security() -> Dict:
    issues: List[str] = []
    details: Dict[str, Any] = {}

    if _OS == "Darwin":
        # Firewall
        fw = _run(["defaults", "read", "/Library/Preferences/com.apple.alf", "globalstate"])
        details["firewall"] = fw.strip() == "1"
        if fw.strip() == "0":
            issues.append("macOS Firewall is disabled")

        # FileVault (disk encryption)
        fv = _run(["fdesetup", "status"])
        details["filevault"] = "FileVault is On" in fv
        if "FileVault is Off" in fv:
            issues.append("FileVault disk encryption is disabled")

        # Gatekeeper
        gk = _run(["spctl", "--status"])
        details["gatekeeper"] = "assessments enabled" in gk
        if "disabled" in gk:
            issues.append("Gatekeeper is disabled — unverified apps may run")

    elif _OS == "Linux":
        # ufw
        ufw = _run(["ufw", "status"])
        details["firewall"] = "Status: active" in ufw
        if "inactive" in ufw:
            issues.append("UFW firewall is inactive")

        # ClamAV
        clam = _run(["clamscan", "--version"])
        details["av_installed"] = bool(clam)
        if not clam:
            issues.append("ClamAV not installed")

    elif _OS == "Windows":
        # Windows Defender
        out = _run_ps(
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

        # BitLocker
        bl = _run_ps("Get-BitLockerVolume -MountPoint C: | Select-Object -ExpandProperty ProtectionStatus")
        details["bitlocker"] = bl.strip() == "On"
        if bl.strip() == "Off":
            issues.append("BitLocker disk encryption is Off on C:")

    return {"details": details, "issues": issues}


def _check_updates() -> Dict:
    updates: List[str] = []

    if _OS == "Darwin":
        out = _run(["softwareupdate", "-l"], timeout=30)
        for line in out.splitlines():
            if line.strip().startswith("*"):
                updates.append(line.strip().lstrip("* "))

    elif _OS == "Linux":
        # apt (Debian/Ubuntu)
        _run(["apt-get", "update", "-qq"], timeout=30)
        out = _run(["apt-get", "--just-print", "upgrade"], timeout=20)
        for line in out.splitlines():
            if line.startswith("Inst "):
                updates.append(line.split()[1])

    elif _OS == "Windows":
        out = _run_ps("winget upgrade --include-unknown | Select-String '^[A-Za-z]'", timeout=60)
        lines = [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("-")]
        updates = lines[:30]

    issues = [f"{len(updates)} software update(s) pending"] if updates else []
    return {"pending": updates[:30], "count": len(updates), "issues": issues}


def _check_av_status() -> Dict:
    """Quick AV scan for common malware indicators (not a full scan — just status)."""
    details: Dict[str, Any] = {}
    issues: List[str] = []

    if _OS == "Darwin":
        # XProtect last update
        xp = _run(["system_profiler", "SPInstallHistoryDataType"])
        details["xprotect"] = "XProtect" in xp
        # MRT status
        mrt = _run(["ls", "-la", "/Library/Apple/System/Library/CoreServices/MRT.app"])
        details["mrt_present"] = bool(mrt)
        if not details.get("xprotect"):
            issues.append("XProtect signatures may be outdated")

    elif _OS == "Linux":
        last_update = _run(["freshclam", "--version"])
        details["clamav"] = bool(last_update)
        if not last_update:
            issues.append("ClamAV definitions may be outdated — run freshclam")

    elif _OS == "Windows":
        out = _run_ps(
            "Get-MpComputerStatus | Select-Object "
            "AntivirusSignatureLastUpdated,QuickScanAge,FullScanAge | ConvertTo-Json -Compress"
        )
        try:
            st = json.loads(out) if out else {}
            details.update(st)
            age = st.get("QuickScanAge", 999)
            if isinstance(age, (int, float)) and age > 7:
                issues.append(f"Windows Defender last scanned {age} days ago")
        except Exception:
            pass

    return {"details": details, "issues": issues}


def _system_info() -> Dict:
    uname = platform.uname()
    return {
        "os":       _OS,
        "hostname": platform.node(),
        "platform": platform.platform(),
        "arch":     uname.machine,
        "python":   platform.python_version(),
        "uptime_h": round((datetime.now().timestamp() - psutil.boot_time()) / 3600, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Main scan function
# ─────────────────────────────────────────────────────────────────────────────

def run_daily_scan(device_id: str = "", user_id: str = "") -> Dict[str, Any]:
    """
    Run the full once-daily health scan and return a structured report dict.
    Takes ~15-30 seconds depending on OS and network checks.
    """
    log.info("Starting daily system scan (OS=%s)", _OS)
    scan_time = datetime.now(timezone.utc).isoformat()

    report: Dict[str, Any] = {
        "schema_version": 3,
        "device_id":      device_id,
        "user_id":        user_id,
        "scan_time":      scan_time,
        "system":         _system_info(),
        "disk":           _check_disk(),
        "memory":         _check_memory(),
        "cpu":            _check_cpu(),
        "battery":        _check_battery(),
        "services":       _check_services(),
        "drivers":        _check_drivers(),
        "network":        _check_network(),
        "bluetooth":      _check_bluetooth(),
        "security":       _check_security(),
        "updates":        _check_updates(),
        "av":             _check_av_status(),
    }

    # Aggregate all issues for quick server-side inspection
    all_issues: List[str] = []
    for section in ["disk", "memory", "cpu", "battery", "services",
                    "drivers", "network", "bluetooth", "security", "updates", "av"]:
        all_issues.extend(report[section].get("issues", []))
    report["all_issues"]  = all_issues
    report["issue_count"] = len(all_issues)

    log.info("Daily scan complete — %d issue(s) found", len(all_issues))

    # Persist locally (reporter.py uploads this)
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _LAST_REPORT_FILE.write_text(json.dumps(report, indent=2, default=str))
        log.info("Report cached at %s", _LAST_REPORT_FILE)
    except Exception as e:
        log.warning("Could not cache report locally: %s", e)

    return report


# ─────────────────────────────────────────────────────────────────────────────
#  CLI entry point  (python -m agent.monitor)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    device_id = os.getenv("AGENT_DEVICE_ID", "local-dev")
    user_id   = os.getenv("AGENT_MONITOR_USER_ID", "unknown")
    report    = run_daily_scan(device_id=device_id, user_id=user_id)
    print(json.dumps(report, indent=2, default=str))
