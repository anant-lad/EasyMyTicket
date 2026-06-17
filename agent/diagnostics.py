"""
Read-only system diagnostics — cross-platform (Windows / macOS / Linux).
All functions return serialisable dicts suitable for JSON transport.
"""
import os
import platform
import subprocess
import logging

import psutil

log = logging.getLogger(__name__)

_OS = platform.system()   # 'Windows' | 'Darwin' | 'Linux'


def get_system_info() -> dict:
    """CPU, memory, disk, OS version."""
    try:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "os":          platform.system(),
            "os_version":  platform.version(),
            "hostname":    platform.node(),
            "cpu_count":   psutil.cpu_count(),
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_total_gb": round(vm.total / 1e9, 2),
            "memory_used_pct": vm.percent,
            "disk_total_gb":  round(disk.total / 1e9, 2),
            "disk_free_gb":   round(disk.free / 1e9, 2),
            "disk_used_pct":  disk.percent,
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


def run_all() -> dict:
    """Collect a full diagnostic bundle."""
    return {
        "system":    get_system_info(),
        "network":   get_network_info(),
        "processes": get_running_processes(),
        "errors":    get_recent_errors(),
    }
