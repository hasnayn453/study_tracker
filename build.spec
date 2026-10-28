# -*- coding: utf-8 -*-
"""
PyInstaller spec for Study Tracker.

Build a one-folder or one-file standalone app:

    # Windows (.exe)
    pyinstaller build.spec --name StudyTracker --distpath dist/win

    # macOS (.app bundle)
    pyinstaller build.spec --name StudyTracker --distpath dist/mac

Notes:
  * On macOS you must codesign/notarize the .app for camera & screen
    recording permissions to be grantable by the user.
  * Add `--windowed` (default here) so no console window appears.
"""

import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Core
        "mss",
        "PIL",
        "pystray",
        "cryptography",
        "pygetwindow",
        "requests",
        "cv2",
        # Optional heavy deps (included if installed)
        "mediapipe",
        # Optional
        "psutil",
        "boto3",
        # macOS idle detection + pystray backend
        "Quartz",
        "Foundation",
        "AppKit",
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

# Collect mediapipe's protobuf/data files if present.
try:
    a.binaries += collect_submodules("mediapipe")
except Exception:
    pass

# Platform-specific console handling.
if sys.platform.startswith("win"):
    app = BUNDLE if False else None
    exe = EXE(
        a,
        name="StudyTracker",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,  # background / tray only
        icon=None,      # set to "assets/icon.ico" if you have one
    )
elif sys.platform == "darwin":
    app = BUNDLE(
        a,
        name="StudyTracker.app",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        icon=None,  # set to "assets/icon.icns" if you have one
        bundle_identifier="com.example.studytracker",
        info_plist={
            "NSHumanReadableDisplayName": "Study Tracker",
            "NSCameraUsageDescription": "Study Tracker needs camera access to detect desk presence.",
            "NSMicrophoneUsageDescription": "",
            "NSAppleEventsUsageDescription": "Study Tracker reads the active window title.",
            "NSScreenCaptureUsageDescription": "Study Tracker captures occasional low-res screenshots.",
        },
    )
else:
    exe = EXE(a, name="studytracker", console=False)

COLLECT = None
