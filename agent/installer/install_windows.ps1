# EasyMyTicket Agent — Windows installer
# Installs:
#   1. A Scheduled Task that runs the WebSocket agent at logon (auto-restart)
#   2. A Scheduled Task that runs the daily health scan at 06:00 every day
#
# Usage (run as Administrator):
#   $env:AGENT_API_URL="wss://api.yourdomain.com"
#   $env:AGENT_API_KEY="<key>"
#   .\install_windows.ps1

param(
    [string]$ApiUrl     = $env:AGENT_API_URL,
    [string]$ApiKey     = $env:AGENT_API_KEY,
    [string]$InstallDir = "C:\EasyMyTicket\Agent"
)

if (-not $ApiUrl) { throw "AGENT_API_URL is required" }
if (-not $ApiKey) { throw "AGENT_API_KEY is required" }

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir     = "C:\EasyMyTicket\Logs"

Write-Host "==> Installing EasyMyTicket Agent to $InstallDir"

# ── Create directories ────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir     | Out-Null

# ── Copy source files ─────────────────────────────────────────────────────────
Copy-Item -Recurse -Force "$ScriptRoot\.." "$InstallDir\agent_src"

# ── Install Python dependencies ───────────────────────────────────────────────
python -m pip install --quiet websockets psutil httpx

# ── Write wrapper scripts ─────────────────────────────────────────────────────
# WebSocket agent
@"
import os, sys, asyncio
os.environ.setdefault('AGENT_API_URL', '$ApiUrl')
os.environ.setdefault('AGENT_API_KEY', '$ApiKey')
os.environ.setdefault('AGENT_CACHE_DIR', r'C:\EasyMyTicket\Cache')
sys.path.insert(0, r'$InstallDir\agent_src')
from agent.main import run_with_reconnect
asyncio.run(run_with_reconnect())
"@ | Out-File -Encoding UTF8 "$InstallDir\run_agent.py"

# Daily scan
@"
import os, sys, asyncio
os.environ.setdefault('AGENT_API_URL', '$ApiUrl')
os.environ.setdefault('AGENT_API_KEY', '$ApiKey')
os.environ.setdefault('AGENT_CACHE_DIR', r'C:\EasyMyTicket\Cache')
sys.path.insert(0, r'$InstallDir\agent_src')
from agent.main import _run_daily_scan_mode
asyncio.run(_run_daily_scan_mode())
"@ | Out-File -Encoding UTF8 "$InstallDir\run_scan.py"

New-Item -ItemType Directory -Force -Path "C:\EasyMyTicket\Cache" | Out-Null

# ── Scheduled Task: WebSocket agent (runs at logon, restarts on failure) ──────
$ActionWS  = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "`"$InstallDir\run_agent.py`"" `
    -WorkingDirectory $InstallDir

$TriggerWS = New-ScheduledTaskTrigger -AtLogOn

$SettingsWS = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Seconds 15) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName   "EasyMyTicketAgent" `
    -TaskPath   "\EasyMyTicket\" `
    -Action     $ActionWS `
    -Trigger    $TriggerWS `
    -Settings   $SettingsWS `
    -RunLevel   Highest `
    -Force | Out-Null

Start-ScheduledTask -TaskPath "\EasyMyTicket\" -TaskName "EasyMyTicketAgent"

# ── Scheduled Task: Daily scan at 06:00 ───────────────────────────────────────
$ActionScan = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "`"$InstallDir\run_scan.py`"" `
    -WorkingDirectory $InstallDir

# Trigger: every day at 06:00; if missed (machine was off), run on next start
$TriggerScan = New-ScheduledTaskTrigger -Daily -At "06:00"

$SettingsScan = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable $true    # run ASAP if the 06:00 window was missed

Register-ScheduledTask `
    -TaskName   "EasyMyTicketDailyScan" `
    -TaskPath   "\EasyMyTicket\" `
    -Action     $ActionScan `
    -Trigger    $TriggerScan `
    -Settings   $SettingsScan `
    -RunLevel   Highest `
    -Force | Out-Null

Write-Host ""
Write-Host "✅  EasyMyTicket Agent installed (Windows)"
Write-Host "    WebSocket agent  : Get-ScheduledTask -TaskPath '\EasyMyTicket\' -TaskName 'EasyMyTicketAgent'"
Write-Host "    Daily scan (06:00): Get-ScheduledTask -TaskPath '\EasyMyTicket\' -TaskName 'EasyMyTicketDailyScan'"
Write-Host "    Logs             : $LogDir"
Write-Host ""
Write-Host "    To uninstall:"
Write-Host "    Unregister-ScheduledTask -TaskPath '\EasyMyTicket\' -TaskName 'EasyMyTicketAgent' -Confirm:`$false"
Write-Host "    Unregister-ScheduledTask -TaskPath '\EasyMyTicket\' -TaskName 'EasyMyTicketDailyScan' -Confirm:`$false"
