#!/usr/bin/env bash
# EasyMyTicket Agent — Ubuntu/Debian one-shot installer
#
# Usage (copy-paste on the user's machine):
#   curl -fsSL <url>/install_ubuntu.sh | sudo bash -s -- \
#       --api-url ws://YOUR_ALB/  --api-key YOUR_KEY --user-id USER001
#
# OR with env vars:
#   sudo AGENT_API_URL=ws://... AGENT_API_KEY=... bash install_ubuntu.sh

set -euo pipefail

# ── Parse arguments ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --api-url)  AGENT_API_URL="$2";  shift 2 ;;
        --api-key)  AGENT_API_KEY="$2";  shift 2 ;;
        --user-id)  AGENT_USER_ID="$2";  shift 2 ;;
        *) shift ;;
    esac
done

AGENT_API_URL="${AGENT_API_URL:-}"
AGENT_API_KEY="${AGENT_API_KEY:-}"
AGENT_USER_ID="${AGENT_USER_ID:-$(whoami)}"

# ── Interactive prompts if values missing ─────────────────────────────────────
if [[ -z "$AGENT_API_URL" ]]; then
    read -rp "Backend API URL (e.g. ws://your-alb/): " AGENT_API_URL
fi
if [[ -z "$AGENT_API_KEY" ]]; then
    read -rp "API Key: " AGENT_API_KEY
fi
if [[ -z "$AGENT_USER_ID" ]]; then
    read -rp "Your User ID (e.g. TECH001): " AGENT_USER_ID
fi

INSTALL_DIR="/opt/easymyticket-agent"
CACHE_DIR="/var/cache/easymyticket"
LOG_DIR="/var/log/easymyticket"
SERVICE_WS="easymyticket-agent"
SERVICE_SCAN="easymyticket-daily-scan"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_SRC="$(cd "$SCRIPT_DIR/.." && pwd)"  # parent of installer/

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  EasyMyTicket Agent — Ubuntu Installer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  API URL : $AGENT_API_URL"
echo "  User ID : $AGENT_USER_ID"
echo "  Install : $INSTALL_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── System dependencies ───────────────────────────────────────────────────────
echo "==> Checking system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv curl 2>/dev/null || true

# ── Install directory ─────────────────────────────────────────────────────────
echo "==> Installing agent to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR" "$CACHE_DIR" "$LOG_DIR"

# Copy agent source (entire agent + src directories needed)
rsync -a --delete "$AGENT_SRC/" "$INSTALL_DIR/" 2>/dev/null || \
    cp -r "$AGENT_SRC/." "$INSTALL_DIR/"

# ── Python virtual environment ────────────────────────────────────────────────
echo "==> Setting up Python virtualenv..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install --quiet \
    "websockets>=12.0" "psutil>=5.9.0" "httpx>=0.25.0" "requests>=2.31.0" "ddgs>=9.0.0"
PYTHON_BIN="$INSTALL_DIR/.venv/bin/python"

# ── Generate device ID ────────────────────────────────────────────────────────
DEVICE_ID=$(python3 -c "import uuid; print(str(uuid.uuid4()))" 2>/dev/null || cat /proc/sys/kernel/random/uuid)
echo "$DEVICE_ID" > "$CACHE_DIR/device_id.txt"
echo "==> Device ID: $DEVICE_ID"
echo "    (Share this with your IT admin to link tickets to this machine)"

# ── Write config ──────────────────────────────────────────────────────────────
cat > "$CACHE_DIR/config.ini" << 'CONF_TEMPLATE'
[agent]
api_url = AGENT_API_URL_PLACEHOLDER
api_key = AGENT_API_KEY_PLACEHOLDER
user_id = AGENT_USER_ID_PLACEHOLDER
device_id = DEVICE_ID_PLACEHOLDER
CONF_TEMPLATE
sed -i \
    -e "s|AGENT_API_URL_PLACEHOLDER|${AGENT_API_URL}|" \
    -e "s|AGENT_API_KEY_PLACEHOLDER|${AGENT_API_KEY}|" \
    -e "s|AGENT_USER_ID_PLACEHOLDER|${AGENT_USER_ID}|" \
    -e "s|DEVICE_ID_PLACEHOLDER|${DEVICE_ID}|" \
    "$CACHE_DIR/config.ini"
chmod 600 "$CACHE_DIR/config.ini"

# ── systemd service: persistent WebSocket daemon ──────────────────────────────
cat > "/etc/systemd/system/${SERVICE_WS}.service" << SVC
[Unit]
Description=EasyMyTicket Desktop Remediation Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
Environment="AGENT_API_URL=$AGENT_API_URL"
Environment="AGENT_API_KEY=$AGENT_API_KEY"
Environment="AGENT_DEVICE_ID=$DEVICE_ID"
Environment="AGENT_MONITOR_USER_ID=$AGENT_USER_ID"
Environment="AGENT_CACHE_DIR=$CACHE_DIR"
ExecStart=$PYTHON_BIN -m agent.main
Restart=always
RestartSec=15
StandardOutput=journal
StandardError=journal
SyslogIdentifier=easymyticket-agent

[Install]
WantedBy=multi-user.target
SVC

# ── systemd service: daily scan (one-shot, launched by timer) ─────────────────
cat > "/etc/systemd/system/${SERVICE_SCAN}.service" << SVC
[Unit]
Description=EasyMyTicket Daily System Health Scan
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$INSTALL_DIR
Environment="AGENT_API_URL=$AGENT_API_URL"
Environment="AGENT_API_KEY=$AGENT_API_KEY"
Environment="AGENT_DEVICE_ID=$DEVICE_ID"
Environment="AGENT_MONITOR_USER_ID=$AGENT_USER_ID"
Environment="AGENT_CACHE_DIR=$CACHE_DIR"
ExecStart=$PYTHON_BIN -m agent.main --scan
StandardOutput=journal
StandardError=journal
SyslogIdentifier=easymyticket-scan
SVC

# ── systemd timer: fire daily at 06:00 ───────────────────────────────────────
cat > "/etc/systemd/system/${SERVICE_SCAN}.timer" << TMR
[Unit]
Description=EasyMyTicket Daily Scan — 06:00

[Timer]
OnCalendar=*-*-* 06:00:00
AccuracySec=5min
Persistent=true

[Install]
WantedBy=timers.target
TMR

# ── Enable + start ────────────────────────────────────────────────────────────
echo "==> Starting services..."
systemctl daemon-reload
systemctl enable  "$SERVICE_WS"
systemctl restart "$SERVICE_WS"
systemctl enable  "${SERVICE_SCAN}.timer"
systemctl restart "${SERVICE_SCAN}.timer"

# ── Run first scan immediately ────────────────────────────────────────────────
echo "==> Running initial health scan..."
"$PYTHON_BIN" -m agent.main --scan 2>&1 | tail -5 || true

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅  EasyMyTicket Agent installed!"
echo ""
echo "  Device ID : $DEVICE_ID"
echo "  Config    : $CACHE_DIR/config.ini"
echo ""
echo "  Status    : sudo systemctl status $SERVICE_WS"
echo "  Logs      : sudo journalctl -u $SERVICE_WS -f"
echo "  Next scan : systemctl list-timers $SERVICE_SCAN"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
