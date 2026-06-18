#!/usr/bin/env bash
# Build the EasyMyTicket agent binary for macOS and package as a .pkg installer
# Run from the project root: bash agent/build_macos.sh
set -euo pipefail

VERSION="${1:-1.0.0}"
BUILD_DIR="dist/macos"

echo "==> Installing agent dependencies"
pip install -r agent/requirements.txt pyinstaller

echo "==> Building binary with PyInstaller"
pyinstaller agent/build.spec \
  --distpath "${BUILD_DIR}/bin" \
  --workpath "${BUILD_DIR}/build" \
  --clean --noconfirm

BINARY="${BUILD_DIR}/bin/easymyticket-agent"
echo "==> Binary built: $BINARY"

# ── Build .pkg ────────────────────────────────────────────────────────────────
echo "==> Creating .pkg installer"

STAGING="${BUILD_DIR}/staging"
mkdir -p "${STAGING}/usr/local/bin"
mkdir -p "${STAGING}/Library/LaunchDaemons"

cp "$BINARY" "${STAGING}/usr/local/bin/easymyticket-agent"
chmod 755 "${STAGING}/usr/local/bin/easymyticket-agent"

# LaunchDaemon: persistent WebSocket agent
cat > "${STAGING}/Library/LaunchDaemons/com.easymyticket.agent.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.easymyticket.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/easymyticket-agent</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>AGENT_API_URL</key>
    <string>wss://your-api.example.com</string>
    <key>AGENT_API_KEY</key>
    <string>your-api-key-here</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/var/log/easymyticket-agent.log</string>
  <key>StandardErrorPath</key>
  <string>/var/log/easymyticket-agent.log</string>
</dict>
</plist>
EOF

# LaunchDaemon: daily scan at 06:00
cat > "${STAGING}/Library/LaunchDaemons/com.easymyticket.scan.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.easymyticket.scan</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/easymyticket-agent</string>
    <string>--scan</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>6</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/var/log/easymyticket-scan.log</string>
  <key>StandardErrorPath</key>
  <string>/var/log/easymyticket-scan.log</string>
</dict>
</plist>
EOF

# Build the .pkg
PKG_FILE="${BUILD_DIR}/easymyticket-agent-${VERSION}.pkg"
pkgbuild \
  --root "${STAGING}" \
  --identifier "com.easymyticket.agent" \
  --version "${VERSION}" \
  --install-location "/" \
  "${PKG_FILE}" 2>/dev/null || {
    # pkgbuild not available — tar fallback for CI
    echo "pkgbuild not found — creating tar.gz instead"
    tar -czf "${BUILD_DIR}/easymyticket-agent-${VERSION}-macos.tar.gz" -C "${BUILD_DIR}" bin
  }

echo "==> macOS package ready at: ${BUILD_DIR}/"
