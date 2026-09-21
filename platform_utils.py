"""
F.R.I.D.A.Y. Platform Utilities
Small OS-detection and cross-platform helpers shared by server.py, screen.py,
cleaner.py, and network.py so each feature module can branch Windows vs
Linux behavior without duplicating the detection logic.
"""

import os
import platform
import shutil
import subprocess

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX   = platform.system() == "Linux"
IS_MAC     = platform.system() == "Darwin"


def which_first(*names) -> str | None:
    """Return the full path of the first binary found on PATH, or None."""
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def run_silent(cmd: list, timeout: int = 10) -> subprocess.CompletedProcess | None:
    """Run a command, swallowing errors from missing binaries. Returns None on failure."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def user_dir(name: str) -> str:
    """
    Resolve a well-known user folder (Desktop, Downloads, Documents, Pictures,
    Videos, Music) correctly per-OS.

    Windows: these always live directly under the user profile.
    Linux: respects the user's actual xdg-user-dirs configuration (which may
    point Desktop/Downloads/etc. somewhere other than ~/Desktop) via the
    `xdg-user-dir` command, falling back to ~/Name if that tool or the
    directory isn't set up.
    """
    home = os.path.expanduser("~")
    if IS_LINUX:
        xdg_key = {
            "Desktop": "DESKTOP", "Downloads": "DOWNLOAD", "Documents": "DOCUMENTS",
            "Pictures": "PICTURES", "Videos": "VIDEOS", "Music": "MUSIC",
        }.get(name)
        if xdg_key and shutil.which("xdg-user-dir"):
            result = run_silent(["xdg-user-dir", xdg_key])
            if result and result.returncode == 0 and result.stdout.strip():
                path = result.stdout.strip()
                if os.path.isdir(path):
                    return path
    return os.path.join(home, name)
