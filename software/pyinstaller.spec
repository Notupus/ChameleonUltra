# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

# Get all binary files from script/bin
bin_dir = os.path.join('script', 'bin')
binaries = []
if os.path.exists(bin_dir):
    for f in os.listdir(bin_dir):
        src = os.path.join(bin_dir, f)
        if os.path.isfile(src):
            binaries.append((src, 'bin'))

a = Analysis(
    ['script/chameleon_cli_main.py'],
    pathex=['script'],
    binaries=binaries,
    datas=[],
    hiddenimports=[
        'chameleon_cli_unit',
        'chameleon_cmd',
        'chameleon_com',
        'chameleon_enum',
        'chameleon_utils',
        'crypto1',
        'hardnested_utils',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='chameleon_cli_main',
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
)
