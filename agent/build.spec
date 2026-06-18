# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for EasyMyTicket Desktop Agent
# Build: pyinstaller agent/build.spec

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['agent/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Bundle the offline queue module data dir placeholder
        ('agent', 'agent'),
    ],
    hiddenimports=[
        'websockets',
        'websockets.legacy.client',
        'websockets.legacy.server',
        'psutil',
        'httpx',
        'agent.diagnostics',
        'agent.executor',
        'agent.monitor',
        'agent.reporter',
        'agent.offline_queue',
        'sqlite3',
        'platform',
        'subprocess',
        'shutil',
        'json',
        'uuid',
        'asyncio',
        'pathlib',
        'datetime',
        'signal',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy ML packages not needed in the agent binary
        'torch', 'tensorflow', 'sklearn', 'pandas', 'numpy',
        'fastembed', 'langchain', 'langgraph', 'groq',
        'boto3', 'botocore', 'psycopg2',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='easymyticket-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
