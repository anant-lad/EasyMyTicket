#!/usr/bin/env bash
# EasyMyTicket Agent — macOS installer
# Installs:
#   1. A launchd agent that runs the WebSocket connection on login
#   2. A launchd agent that runs the daily scan at 06:00 every morning
#
# Usage:
#   AGENT_API_URL=wss://api.yourdomain.com \
#   AGENT_API_KEY=<key> \
#   bash install_macos.sh
#
# Requires: Python 3.9+ (brew install python if not present)

set -euo pipefail

AGENT_API_URL="${AGENT_API_URL:?AGENT_API_URL is required}"
AGENT_API_KEY="${AGENT_API_KEY:?AGENT_API_KEY is required}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.easymyticket/agent}"
PYTHON_BIN="$(which python3)"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
PLIST_WS="com.easymyticket.agent.plist"
PLIST_SCAN="com.easymyticket.dailyscan.plist"
LOG_DIR="$HOME/.easymyticket/logs"

echo "==> Installing EasyMyTicket Agent to $INSTALL_DIR"

# ── Create directories ────────────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR" "$LAUNCHD_DIR" "$LOG_DIR"

# ── Copy source ───────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cp -r "$SCRIPT_DIR" "$INSTALL_DIR/src"

# ── Install Python dependencies ───────────────────────────────────────────────
"$PYTHON_BIN" -m pip install --quiet --user websockets psutil httpx

# ── Write wrapper script (bakes in env vars) ──────────────────────────────────
cat > "$INSTALL_DIR/run_agent.py" << PYEOF
import os, sys
os.environ.setdefault('AGENT_API_URL',  '$AGENT_API_URL')
os.environ.setdefault('AGENT_API_KEY',  '$AGENT_API_KEY')
sys.path.insert(0, '$INSTALL_DIR/src')
from agent.main import run_with_reconnect
import asyncio
asyncio.run(run_with_reconnect())
PYEOF

cat > "$INSTALL_DIR/run_scan.py" << PYEOF
import os, sys, asyncio
os.environ.setdefault('AGENT_API_URL',  '$AGENT_API_URL')
os.environ.setdefault('AGENT_API_KEY',  '$AGENT_API_KEY')
sys.path.insert(0, '$INSTALL_DIR/src')
from agent.reporter import run_and_send
asyncio.run(run_and_send(
    api_url=os.environ['AGENT_API_URL'],
    api_key=os.environ['AGENT_API_KEY'],
    device_id=open(os.path.expanduser('~/.easymyticket/device_id.txt')).read().strip()
             if os.path.exists(os.path.expanduser('~/.easymyticket/device_id.txt'))
             else 'unknown',
    user_id=os.environ.get('USER', 'unknown'),
))
PYEOF

# ── launchd plist: persistent WebSocket agent ─────────────────────────────────
cat > "$LAUNCHD_DIR/$PLIST_WS" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.easymyticket.agent</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$INSTALL_DIR/run_agent.py</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>AGENT_API_URL</key>  <string>$AGENT_API_URL</string>
    <key>AGENT_API_KEY</key>  <string>$AGENT_API_KEY</string>
    <key>AGENT_CACHE_DIR</key><string>$HOME/.easymyticket</string>
  </dict>

  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>

  <key>StandardOutPath</key>
  <string>$LOG_DIR/agent.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/agent-err.log</string>

  <key>ThrottleInterval</key><integer>10</integer>
</dict>
</plist>
PLIST

# ── launchd plist: daily 06:00 scan ──────────────────────────────────────────
cat > "$LAUNCHD_DIR/$PLIST_SCAN" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.easymyticket.dailyscan</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$INSTALL_DIR/run_scan.py</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>AGENT_API_URL</key>  <string>$AGENT_API_URL</string>
    <key>AGENT_API_KEY</key>  <string>$AGENT_API_KEY</string>
    <key>AGENT_CACHE_DIR</key><string>$HOME/.easymyticket</string>
  </dict>

  <!-- Run every day at 06:00 local time -->
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>  <integer>6</integer>
    <key>Minute</key><integer>0</integer>
  </dict>

  <key>StandardOutPath</key>
  <string>$LOG_DIR/daily-scan.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/daily-scan-err.log</string>
</dict>
</plist>
PLIST

# ── Load both agents ──────────────────────────────────────────────────────────
launchctl unload "$LAUNCHD_DIR/$PLIST_WS"   2>/dev/null || true
launchctl unload "$LAUNCHD_DIR/$PLIST_SCAN" 2>/dev/null || true
launchctl load   "$LAUNCHD_DIR/$PLIST_WS"
launchctl load   "$LAUNCHD_DIR/$PLIST_SCAN"

echo "✅  EasyMyTicket Agent installed (macOS)"
echo "    WebSocket agent : launchctl list com.easymyticket.agent"
echo "    Daily scan (06:00): launchctl list com.easymyticket.dailyscan"
echo "    Logs: $LOG_DIR/"
echo ""
echo "    To uninstall:"
echo "    launchctl unload ~/Library/LaunchAgents/com.easymyticket.agent.plist"
echo "    launchctl unload ~/Library/LaunchAgents/com.easymyticket.dailyscan.plist"
