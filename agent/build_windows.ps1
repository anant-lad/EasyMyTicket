# Build the EasyMyTicket agent binary for Windows and package as an installer
# Run from the project root: powershell -ExecutionPolicy Bypass -File agent\build_windows.ps1
param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$BuildDir = "dist\windows"

Write-Host "==> Installing agent dependencies" -ForegroundColor Cyan
pip install -r agent\requirements.txt pyinstaller

Write-Host "==> Building binary with PyInstaller" -ForegroundColor Cyan
pyinstaller agent\build.spec `
  --distpath "$BuildDir\bin" `
  --workpath "$BuildDir\build" `
  --clean --noconfirm

$Binary = "$BuildDir\bin\easymyticket-agent.exe"
if (-not (Test-Path $Binary)) {
    Write-Error "Binary not found at $Binary"
    exit 1
}
Write-Host "==> Binary built: $Binary" -ForegroundColor Green

# ── Create installer via NSIS (if available) ──────────────────────────────────
$NsisInstaller = "C:\Program Files (x86)\NSIS\makensis.exe"

if (Test-Path $NsisInstaller) {
    Write-Host "==> Building NSIS installer" -ForegroundColor Cyan

    $NsisScript = @"
!include "MUI2.nsh"

Name "EasyMyTicket Agent"
OutFile "$BuildDir\easymyticket-agent-$Version-setup.exe"
InstallDir "\$PROGRAMFILES64\EasyMyTicket"
RequestExecutionLevel admin

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Install"
  SetOutPath "\$INSTDIR"
  File "$Binary"
  File /r "$BuildDir\bin\*"

  ; Create config directory
  CreateDirectory "\$APPDATA\EasyMyTicket"

  ; Write default config
  FileOpen \$0 "\$APPDATA\EasyMyTicket\agent.env" w
  FileWrite \$0 "AGENT_API_URL=wss://your-api.example.com\$\r\$\n"
  FileWrite \$0 "AGENT_API_KEY=your-api-key-here\$\r\$\n"
  FileWrite \$0 "AGENT_MONITOR_USER_ID=your-user-id\$\r\$\n"
  FileClose \$0

  ; Register as Windows Service using sc.exe
  ExecWait 'sc create EasyMyTicketAgent binPath= "\$INSTDIR\easymyticket-agent.exe" start= auto DisplayName= "EasyMyTicket Agent"'
  ExecWait 'sc description EasyMyTicketAgent "EasyMyTicket desktop remediation and monitoring agent"'

  ; Scheduled Task for daily scan at 06:00
  ExecWait 'schtasks /Create /TN "EasyMyTicketDailyScan" /TR "\$INSTDIR\easymyticket-agent.exe --scan" /SC DAILY /ST 06:00 /RU SYSTEM /RL HIGHEST /F'

  WriteUninstaller "\$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  ExecWait 'sc stop EasyMyTicketAgent'
  ExecWait 'sc delete EasyMyTicketAgent'
  ExecWait 'schtasks /Delete /TN "EasyMyTicketDailyScan" /F'
  Delete "\$INSTDIR\easymyticket-agent.exe"
  Delete "\$INSTDIR\Uninstall.exe"
  RMDir "\$INSTDIR"
SectionEnd
"@
    $ScriptPath = "$BuildDir\installer.nsi"
    $NsisScript | Out-File -FilePath $ScriptPath -Encoding utf8
    & $NsisInstaller $ScriptPath
    Write-Host "==> NSIS installer built" -ForegroundColor Green
} else {
    Write-Host "==> NSIS not found — creating zip package instead" -ForegroundColor Yellow

    # Register as Windows Service using sc.exe (post-install step)
    $PostInstall = @"
@echo off
echo Registering EasyMyTicket Agent as Windows Service...
sc create EasyMyTicketAgent binPath= "%~dp0easymyticket-agent.exe" start= auto ^
  DisplayName= "EasyMyTicket Agent"
sc description EasyMyTicketAgent "EasyMyTicket desktop remediation and monitoring agent"
schtasks /Create /TN "EasyMyTicketDailyScan" /TR "%~dp0easymyticket-agent.exe --scan" ^
  /SC DAILY /ST 06:00 /RU SYSTEM /RL HIGHEST /F
sc start EasyMyTicketAgent
echo Done. Edit agent.env with your API credentials then restart the service.
"@
    $PostInstall | Out-File -FilePath "$BuildDir\bin\install_service.bat" -Encoding ascii

    Compress-Archive -Path "$BuildDir\bin\*" `
      -DestinationPath "$BuildDir\easymyticket-agent-$Version-windows.zip" -Force
    Write-Host "==> Zip package: $BuildDir\easymyticket-agent-$Version-windows.zip" -ForegroundColor Green
}

Write-Host "==> Build complete!" -ForegroundColor Green
