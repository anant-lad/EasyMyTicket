#!/usr/bin/env bash
# EasyMyTicket Agent — Linux installer
# Installs:
#   1. A systemd service  (persistent WebSocket, auto-restart)
#   2. A systemd timer    (daily scan at 06:00 local time)
#
# Usage:
#   sudo AGENT_API_URL=wss://api.yourdomain.com \
#        AGENT_API_KEY=<key> \
#        bash install_linux.sh

set -euo pipefail

AGENT_API_URL="${AGENT_API_URL:?AGENT_API_URL env var is required}"
AGENT_API_KEY="${AGENT_API_KEY:?AGENT_API_KEY env var is required}"
INSTALL_DIR="/opt/easymyticket-agent"
PYTHON_BIN="$(which python3)"
SERVICE_WS="easymyticket-agent"
SERVICE_SCAN="easymyticket-daily-scan"
LOG_DIR="/var/log/easymyticket"

echo "==> Installing EasyMyTicket Agent to $INSTALL_DIR"

mkdir -p "$INSTALL_DIR" "$LOG_DIR"

# ── Copy source ───────────────────────────────────────────────────────────────
cp -r "$(dirname "$0")/.." "$INSTALL_DIR/src"

# ── Install Python dependencies ───────────────────────────────────────────────
"$PYTHON_BIN" -m pip install --quiet websockets psutil httpx

# ── systemd service: persistent WebSocket ─────────────────────────────────────
cat > "/etc/systemd/system/${SERVICE_WS}.service" << EOF
[Unit]
Description=EasyMyTicket Desktop Remediation Agent (WebSocket)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nobody
WorkingDirectory=$INSTALL_DIR/src
Environment="AGENT_API_URL=$AGENT_API_URL"
Environment="AGENT_API_KEY=$AGENT_API_KEY"
Environment="AGENT_CACHE_DIR=/var/cache/easymyticket"
ExecStart=$PYTHON_BIN -m agent.main
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# ── systemd service: daily scan (one-shot) ────────────────────────────────────
cat > "/etc/systemd/system/${SERVICE_SCAN}.service" << EOF
[Unit]
Description=EasyMyTicket Daily System Health Scan
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=nobody
WorkingDirectory=$INSTALL_DIR/src
Environment="AGENT_API_URL=$AGENT_API_URL"
Environment="AGENT_API_KEY=$AGENT_API_KEY"
Environment="AGENT_CACHE_DIR=/var/cache/easymyticket"
ExecStart=$PYTHON_BIN -m agent.main --scan
StandardOutput=journal
StandardError=journal
EOF

# ── systemd timer: fire daily scan at 06:00 ───────────────────────────────────
cat > "/etc/systemd/system/${SERVICE_SCAN}.timer" << EOF
[Unit]
Description=EasyMyTicket Daily Scan Timer (06:00)

[Timer]
OnCalendar=*-*-* 06:00:00
AccuracySec=5min
Persistent=true          # run missed scan if machine was off at 06:00

[Install]
WantedBy=timers.target
EOF

mkdir -p /var/cache/easymyticket

systemctl daemon-reload

# WebSocket agent: enable + start
systemctl enable "$SERVICE_WS"
systemctl start  "$SERVICE_WS"

# Daily scan timer: enable + start
systemctl enable "${SERVICE_SCAN}.timer"
systemctl start  "${SERVICE_SCAN}.timer"

echo "✅  EasyMyTicket Agent installed (Linux)"
echo "    WebSocket agent  : sudo systemctl status $SERVICE_WS"
echo "    Daily scan timer : sudo systemctl status ${SERVICE_SCAN}.timer"
echo "    Next scan        : systemctl list-timers $SERVICE_SCAN"
echo "    Logs             : sudo journalctl -u $SERVICE_WS -f"
