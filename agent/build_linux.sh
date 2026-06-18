#!/usr/bin/env bash
# Build the EasyMyTicket agent binary for Linux and package it as a .deb
# Run from the project root: bash agent/build_linux.sh
set -euo pipefail

VERSION="${1:-1.0.0}"
ARCH="amd64"
PACKAGE_NAME="easymyticket-agent"
BUILD_DIR="dist/linux"
DEB_DIR="${BUILD_DIR}/deb"

echo "==> Installing agent dependencies"
pip install -r agent/requirements.txt pyinstaller

echo "==> Building binary with PyInstaller"
pyinstaller agent/build.spec \
  --distpath "${BUILD_DIR}/bin" \
  --workpath "${BUILD_DIR}/build" \
  --clean --noconfirm

BINARY="${BUILD_DIR}/bin/easymyticket-agent"
if [ ! -f "$BINARY" ]; then
  echo "ERROR: Binary not found at $BINARY"
  exit 1
fi
echo "==> Binary built: $BINARY ($(du -sh "$BINARY" | cut -f1))"

# ── Package as .deb ──────────────────────────────────────────────────────────
echo "==> Creating .deb package"

mkdir -p "${DEB_DIR}/DEBIAN"
mkdir -p "${DEB_DIR}/usr/local/bin"
mkdir -p "${DEB_DIR}/etc/easymyticket"
mkdir -p "${DEB_DIR}/lib/systemd/system"

cp "$BINARY" "${DEB_DIR}/usr/local/bin/easymyticket-agent"
chmod 755 "${DEB_DIR}/usr/local/bin/easymyticket-agent"

# Systemd service file
cat > "${DEB_DIR}/lib/systemd/system/easymyticket-agent.service" <<'EOF'
[Unit]
Description=EasyMyTicket Desktop Remediation Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/easymyticket-agent
Restart=always
RestartSec=10
EnvironmentFile=-/etc/easymyticket/agent.env
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Daily scan timer
cat > "${DEB_DIR}/lib/systemd/system/easymyticket-scan.service" <<'EOF'
[Unit]
Description=EasyMyTicket Daily Health Scan
After=network-online.target

[Service]
Type=oneshot
User=root
ExecStart=/usr/local/bin/easymyticket-agent --scan
EnvironmentFile=-/etc/easymyticket/agent.env
EOF

cat > "${DEB_DIR}/lib/systemd/system/easymyticket-scan.timer" <<'EOF'
[Unit]
Description=Run EasyMyTicket scan daily at 06:00

[Timer]
OnCalendar=*-*-* 06:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Default env config
cat > "${DEB_DIR}/etc/easymyticket/agent.env" <<'EOF'
# EasyMyTicket Agent Configuration
# Edit these values before enabling the service
AGENT_API_URL=wss://your-api.example.com
AGENT_API_KEY=your-api-key-here
AGENT_MONITOR_USER_ID=your-user-id
# AGENT_DEVICE_ID is auto-generated on first run
EOF

# Debian control file
cat > "${DEB_DIR}/DEBIAN/control" <<EOF
Package: ${PACKAGE_NAME}
Version: ${VERSION}
Architecture: ${ARCH}
Maintainer: EasyMyTicket <support@easymyticket.com>
Description: EasyMyTicket Desktop Remediation Agent
 Provides real-time IT support integration, daily health monitoring,
 and automated remediation for the EasyMyTicket platform.
Depends: systemd
EOF

# Post-install script
cat > "${DEB_DIR}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
systemctl daemon-reload
systemctl enable easymyticket-agent.service
systemctl enable easymyticket-scan.timer
systemctl start easymyticket-scan.timer
echo "EasyMyTicket agent installed. Edit /etc/easymyticket/agent.env and run:"
echo "  systemctl start easymyticket-agent"
EOF
chmod 755 "${DEB_DIR}/DEBIAN/postinst"

DEB_FILE="${BUILD_DIR}/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --build "${DEB_DIR}" "${DEB_FILE}"
echo "==> .deb package: ${DEB_FILE} ($(du -sh "$DEB_FILE" | cut -f1))"
