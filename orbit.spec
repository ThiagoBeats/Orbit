# -*- mode: python ; coding: utf-8 -*-
# Build: .venv\Scripts\pyinstaller orbit.spec --noconfirm  ->  dist\Orbit\Orbit.exe
a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("orbit/ui/web", "orbit/ui/web")],
    hiddenimports=["win32com.client", "pythoncom"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Orbit",
    console=False,
    icon="orbit/ui/web/img/orbit-icon.ico",
)
coll = COLLECT(exe, a.binaries, a.datas, name="Orbit")
