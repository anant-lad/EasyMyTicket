#!/usr/bin/env bash
# EasyMyTicket Agent — Linux installer
# Installs:
#   1. A systemd service  (persistent WebSocket, auto-restart)
#   2. A systemd timer    (daily scan at 06:00 local time)
#   3. A dedicated system user  easymyticket  (no login, no home dir)
#   4. A sudoers drop-in granting NOPASSWD for the safe fix commands
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
AGENT_USER="easymyticket"

echo "==> Installing EasyMyTicket Agent to $INSTALL_DIR"

# ── Dedicated system user ─────────────────────────────────────────────────────
if ! id "$AGENT_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin \
            --comment "EasyMyTicket Agent" "$AGENT_USER"
    echo "    Created system user: $AGENT_USER"
fi

# Add agent user to video group so it can access /dev/video* for camera diagnostics
if getent group video &>/dev/null; then
    usermod -aG video "$AGENT_USER"
    echo "    Added $AGENT_USER to video group"
fi

# ── Install directory ─────────────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR"
cp -r "$(dirname "$0")/.." "$INSTALL_DIR/src"
chown -R "$AGENT_USER:$AGENT_USER" "$INSTALL_DIR"

mkdir -p /var/cache/easymyticket
chown "$AGENT_USER:$AGENT_USER" /var/cache/easymyticket

# ── Python dependencies ───────────────────────────────────────────────────────
"$PYTHON_BIN" -m pip install --quiet websockets psutil httpx v4l2-utils 2>/dev/null || true
# v4l2-ctl via apt if pip doesn't have it
if ! command -v v4l2-ctl &>/dev/null; then
    apt-get install -y -q v4l2-utils 2>/dev/null || true
fi

# ── sudoers drop-in: NOPASSWD for safe fix commands ──────────────────────────
# The agent uses `sudo -n <cmd>` for TIER2 operations. Without NOPASSWD those
# fail immediately. This drop-in grants exactly the commands the agent needs,
# scoped to the agent user only.
cat > "/etc/sudoers.d/easymyticket-agent" <<'SUDOERS'
# EasyMyTicket agent — NOPASSWD for safe remediation commands only
# Do NOT add broad wildcards — each entry is explicit.
Defaults:easymyticket !requiretty

# systemd service management
easymyticket ALL=(root) NOPASSWD: /bin/systemctl restart *, /bin/systemctl stop *, /bin/systemctl start *

# Network
easymyticket ALL=(root) NOPASSWD: /sbin/ip link set * down, /sbin/ip link set * up
easymyticket ALL=(root) NOPASSWD: /sbin/dhclient *
easymyticket ALL=(root) NOPASSWD: /usr/sbin/dhclient *
easymyticket ALL=(root) NOPASSWD: /usr/bin/systemd-resolve --flush-caches

# Camera driver reload
easymyticket ALL=(root) NOPASSWD: /sbin/modprobe uvcvideo, /sbin/modprobe -r uvcvideo
easymyticket ALL=(root) NOPASSWD: /usr/sbin/modprobe uvcvideo, /usr/sbin/modprobe -r uvcvideo

# User management (add to video group)
easymyticket ALL=(root) NOPASSWD: /usr/sbin/usermod -aG video *

# Package management
easymyticket ALL=(root) NOPASSWD: /usr/bin/apt-get install -y *, /usr/bin/apt-get upgrade -y

# Firewall
easymyticket ALL=(root) NOPASSWD: /usr/sbin/ufw enable, /usr/sbin/ufw disable, /usr/sbin/ufw status

# dmesg (needed for driver_errors / camera_dmesg_errors)
easymyticket ALL=(root) NOPASSWD: /bin/dmesg
easymyticket ALL=(root) NOPASSWD: /usr/bin/dmesg

# smartctl
easymyticket ALL=(root) NOPASSWD: /usr/sbin/smartctl -H *

# Print management
easymyticket ALL=(root) NOPASSWD: /usr/bin/cancel -a
SUDOERS
chmod 440 "/etc/sudoers.d/easymyticket-agent"
echo "    Sudoers drop-in written: /etc/sudoers.d/easymyticket-agent"

# ── systemd service: persistent WebSocket ────────────────────────────────────
cat > "/etc/systemd/system/${SERVICE_WS}.service" <<EOF
[Unit]
Description=EasyMyTicket Desktop Remediation Agent (WebSocket)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$AGENT_USER
Group=$AGENT_USER
WorkingDirectory=$INSTALL_DIR/src
Environment="AGENT_API_URL=$AGENT_API_URL"
Environment="AGENT_API_KEY=$AGENT_API_KEY"
Environment="AGENT_CACHE_DIR=/var/cache/easymyticket"
Environment="AGENT_AUTO_MODE=1"
ExecStart=$PYTHON_BIN $INSTALL_DIR/src/agent/easymyticket_agent.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# ── systemd service: daily scan (one-shot) ───────────────────────────────────
cat > "/etc/systemd/system/${SERVICE_SCAN}.service" <<EOF
[Unit]
Description=EasyMyTicket Daily System Health Scan
After=network-online.target

[Service]
Type=oneshot
User=$AGENT_USER
Group=$AGENT_USER
WorkingDirectory=$INSTALL_DIR/src
Environment="AGENT_API_URL=$AGENT_API_URL"
Environment="AGENT_API_KEY=$AGENT_API_KEY"
Environment="AGENT_CACHE_DIR=/var/cache/easymyticket"
Environment="AGENT_AUTO_MODE=1"
ExecStart=$PYTHON_BIN $INSTALL_DIR/src/agent/easymyticket_agent.py --scan
StandardOutput=journal
StandardError=journal
EOF

# ── systemd timer: fire daily scan at 06:00 ──────────────────────────────────
cat > "/etc/systemd/system/${SERVICE_SCAN}.timer" <<EOF
[Unit]
Description=EasyMyTicket Daily Scan Timer (06:00)

[Timer]
OnCalendar=*-*-* 06:00:00
AccuracySec=5min
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_WS"
systemctl start  "$SERVICE_WS"
systemctl enable "${SERVICE_SCAN}.timer"
systemctl start  "${SERVICE_SCAN}.timer"

echo ""
echo "✅  EasyMyTicket Agent installed (Linux)"
echo "    Running as user    : $AGENT_USER (video group: $(groups $AGENT_USER 2>/dev/null | grep -o video || echo 'not added — video group missing'))"
echo "    WebSocket agent    : sudo systemctl status $SERVICE_WS"
echo "    Daily scan timer   : sudo systemctl status ${SERVICE_SCAN}.timer"
echo "    Logs               : sudo journalctl -u $SERVICE_WS -f"
echo "    Sudoers            : /etc/sudoers.d/easymyticket-agent"
