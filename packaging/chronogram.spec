# PyInstaller recipe for the double-clickable app (PLAN.md task 13).
#
# Build from the repository root, on the platform you are building for
# (PyInstaller does not cross-compile):
#
#   .venv/bin/pyinstaller packaging/chronogram.spec --noconfirm
#
# One-folder build on purpose: it starts faster than one-file and upsets
# antivirus software less. ffmpeg stays external and is detected on PATH.

import os
import sys

from PyInstaller.utils.hooks import collect_all

sys.path.insert(0, os.path.join(SPECPATH, ".."))  # noqa: F821 - SPECPATH is a PyInstaller global
from chronogram_tg import __version__  # noqa: E402

APP_NAME = "Chronogram TG"
ICON = os.path.join(SPECPATH, "icon.icns" if sys.platform == "darwin" else "icon.ico")  # noqa: F821

# CustomTkinter ships theme files PyInstaller's scanner does not see.
datas, binaries, hiddenimports = collect_all("customtkinter")
# The app icon shown inside the window (gui/app.py reads it next to the code).
datas.append((os.path.join(SPECPATH, "..", "chronogram_tg", "assets"), "chronogram_tg/assets"))  # noqa: F821

a = Analysis(
    [os.path.join(SPECPATH, "launch.py")],  # noqa: F821
    pathex=[os.path.join(SPECPATH, "..")],  # noqa: F821
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=APP_NAME,
    icon=ICON,
    console=False,  # a window, not a console; the CLI stays a source-tree tool
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=ICON,
        bundle_identifier="com.lunadevel.chronogram-tg",
        info_plist={
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
        },
    )
