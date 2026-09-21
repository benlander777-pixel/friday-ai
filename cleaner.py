"""
F.R.I.D.A.Y. File System Cleaner
Scans, summarises, then waits for confirmation before touching anything.
"""

import os, hashlib, fnmatch, stat

# ── PROTECTED PATHS — FRIDAY will never touch these ──────────────────────────
PROTECTED = [
    # Windows system
    r"C:\Windows",
    r"C:\Windows\System32",
    r"C:\Windows\SysWOW64",
    r"C:\Windows\WinSxS",
    r"C:\Windows\Boot",
    r"C:\Windows\System",
    r"C:\Windows\SoftwareDistribution",   # handled separately, carefully
    # Program installs
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    # Games
    r"C:\Games",
    r"C:\SteamLibrary",
    r"C:\Steam",
    os.path.expandvars(r"%ProgramFiles(x86)%\Steam"),
    os.path.expandvars(r"%ProgramFiles%\Steam"),
    os.path.expandvars(r"%LOCALAPPDATA%\EpicGamesLauncher"),
    os.path.expandvars(r"%ProgramFiles%\Epic Games"),
    os.path.expandvars(r"%ProgramFiles(x86)%\GOG Galaxy"),
    os.path.expandvars(r"%ProgramFiles%\GOG Galaxy"),
    # User critical
    os.path.expandvars(r"%USERPROFILE%\Documents"),
    os.path.expandvars(r"%USERPROFILE%\Pictures"),
    os.path.expandvars(r"%USERPROFILE%\Videos"),
    os.path.expandvars(r"%USERPROFILE%\Music"),
    os.path.expandvars(r"%USERPROFILE%\OneDrive"),
    # App data
    os.path.expandvars(r"%APPDATA%\Spotify"),
    os.path.expandvars(r"%APPDATA%\discord"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
]

# Normalise to lowercase for comparison
PROTECTED_NORM = [os.path.normpath(p).lower() for p in PROTECTED if p]


def is_protected(path: str) -> bool:
    """Return True if path is inside any protected directory."""
    norm = os.path.normpath(path).lower()
    for p in PROTECTED_NORM:
        if norm == p or norm.startswith(p + os.sep):
            return True
    return False


# ── JUNK TARGETS — safe to delete ────────────────────────────────────────────

TEMP_DIRS = [
    os.environ.get("TEMP", ""),
    os.environ.get("TMP", ""),
    os.path.expandvars(r"%LOCALAPPDATA%\Temp"),
    os.path.expandvars(r"%WINDIR%\Temp"),
]

BROWSER_CACHE_DIRS = [
    # Chrome
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache"),
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Code Cache"),
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\GPUCache"),
    # Edge
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Code Cache"),
    # Firefox
    os.path.expandvars(r"%LOCALAPPDATA%\Mozilla\Firefox\Profiles"),
]

JUNK_PATTERNS = [
    "*.tmp", "*.temp", "~$*", "*.log", "*.bak", "*.old",
    "*.crdownload", "*.part", "*.dmp", "Thumbs.db",
    "desktop.ini", ".DS_Store", "*.~*",
]

# ── DUPLICATE DETECTION ────────────────────────────────────────────────────────

def file_hash(path: str, chunk=65536) -> str:
    """MD5 hash of file contents."""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                block = f.read(chunk)
                if not block:
                    break
                h.update(block)
        return h.hexdigest()
    except Exception:
        return ""


def find_duplicates(scan_dirs: list) -> dict:
    """
    Returns {hash: [path1, path2, ...]} for files with >1 copy.
    Skips protected paths and system files.
    """
    seen = {}
    for scan_dir in scan_dirs:
        if not os.path.exists(scan_dir) or is_protected(scan_dir):
            continue
        for root, dirs, files in os.walk(scan_dir):
            # Prune protected subdirs in-place
            dirs[:] = [d for d in dirs if not is_protected(os.path.join(root, d))]
            for fname in files:
                fpath = os.path.join(root, fname)
                if is_protected(fpath):
                    continue
                try:
                    size = os.path.getsize(fpath)
                    if size == 0:
                        continue
                    h = file_hash(fpath)
                    if h:
                        seen.setdefault(h, []).append(fpath)
                except Exception:
                    pass
    return {h: paths for h, paths in seen.items() if len(paths) > 1}


# ── SCAN (returns summary, does NOT delete anything) ─────────────────────────

def scan_system() -> dict:
    """
    Scans the system and returns a summary of what CAN be cleaned.
    Nothing is deleted until confirm_clean() is called.
    """
    summary = {
        "temp_files":    {"count": 0, "size_mb": 0, "paths": []},
        "browser_cache": {"count": 0, "size_mb": 0, "paths": []},
        "junk_files":    {"count": 0, "size_mb": 0, "paths": []},
        "duplicates":    {"count": 0, "size_mb": 0, "groups": {}},
        "recycle_bin":   {"size_mb": 0},
        "error_dumps":   {"count": 0, "size_mb": 0, "paths": []},
    }

    # ── Temp files ──
    for temp_dir in TEMP_DIRS:
        if not temp_dir or not os.path.exists(temp_dir):
            continue
        if is_protected(temp_dir):
            continue
        for root, dirs, files in os.walk(temp_dir):
            dirs[:] = [d for d in dirs if not is_protected(os.path.join(root, d))]
            for f in files:
                fp = os.path.join(root, f)
                try:
                    sz = os.path.getsize(fp)
                    summary["temp_files"]["count"] += 1
                    summary["temp_files"]["size_mb"] += sz / (1024**2)
                    summary["temp_files"]["paths"].append(fp)
                except Exception:
                    pass

    # ── Browser cache ──
    for cache_dir in BROWSER_CACHE_DIRS:
        if not os.path.exists(cache_dir) or is_protected(cache_dir):
            continue
        for root, dirs, files in os.walk(cache_dir):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    sz = os.path.getsize(fp)
                    summary["browser_cache"]["count"] += 1
                    summary["browser_cache"]["size_mb"] += sz / (1024**2)
                    summary["browser_cache"]["paths"].append(fp)
                except Exception:
                    pass

    # ── Junk files on Desktop and Downloads ──
    junk_scan_dirs = [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Downloads"),
    ]
    for scan_dir in junk_scan_dirs:
        if not os.path.exists(scan_dir):
            continue
        for root, dirs, files in os.walk(scan_dir):
            dirs[:] = [d for d in dirs if not is_protected(os.path.join(root, d))]
            for f in files:
                fp = os.path.join(root, f)
                if any(fnmatch.fnmatch(f.lower(), pat.lower()) for pat in JUNK_PATTERNS):
                    try:
                        sz = os.path.getsize(fp)
                        summary["junk_files"]["count"] += 1
                        summary["junk_files"]["size_mb"] += sz / (1024**2)
                        summary["junk_files"]["paths"].append(fp)
                    except Exception:
                        pass

    # ── Error dumps ──
    dump_dirs = [
        os.path.expandvars(r"%LOCALAPPDATA%\CrashDumps"),
        os.path.expandvars(r"%WINDIR%\Minidump"),
        os.path.expandvars(r"%WINDIR%\MEMORY.DMP"),
    ]
    for dump_dir in dump_dirs:
        if not os.path.exists(dump_dir):
            continue
        if os.path.isfile(dump_dir):
            try:
                sz = os.path.getsize(dump_dir)
                summary["error_dumps"]["count"] += 1
                summary["error_dumps"]["size_mb"] += sz / (1024**2)
                summary["error_dumps"]["paths"].append(dump_dir)
            except Exception:
                pass
            continue
        for root, dirs, files in os.walk(dump_dir):
            for f in files:
                if f.endswith((".dmp", ".mdmp")):
                    fp = os.path.join(root, f)
                    try:
                        sz = os.path.getsize(fp)
                        summary["error_dumps"]["count"] += 1
                        summary["error_dumps"]["size_mb"] += sz / (1024**2)
                        summary["error_dumps"]["paths"].append(fp)
                    except Exception:
                        pass

    # ── Duplicates (Downloads + Desktop only — safe scope) ──
    dup_dirs = [
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Desktop"),
    ]
    dupes = find_duplicates(dup_dirs)
    for h, paths in dupes.items():
        # Keep the newest file, flag the rest as removable
        paths_sorted = sorted(paths, key=lambda p: os.path.getmtime(p), reverse=True)
        to_remove = paths_sorted[1:]  # keep [0], remove the rest
        for p in to_remove:
            try:
                sz = os.path.getsize(p)
                summary["duplicates"]["count"] += 1
                summary["duplicates"]["size_mb"] += sz / (1024**2)
            except Exception:
                pass
        summary["duplicates"]["groups"][h] = {
            "keep": paths_sorted[0],
            "remove": to_remove,
        }

    # Round sizes
    for key in summary:
        if "size_mb" in summary[key]:
            summary[key]["size_mb"] = round(summary[key]["size_mb"], 1)

    # Total
    total_mb = sum(
        summary[k]["size_mb"] for k in summary if "size_mb" in summary[k]
    )
    summary["total_mb"] = round(total_mb, 1)

    return summary


def _safe_remove(path: str) -> bool:
    """Remove a file, handling read-only flags."""
    try:
        if not os.path.exists(path):
            return True
        if is_protected(path):
            return False
        try:
            os.remove(path)
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            os.remove(path)
        return True
    except Exception:
        return False


def _safe_rmtree(path: str) -> int:
    """Remove a directory tree, returns number of files deleted."""
    removed = 0
    if not os.path.exists(path) or is_protected(path):
        return 0
    for root, dirs, files in os.walk(path, topdown=False):
        dirs[:] = [d for d in dirs if not is_protected(os.path.join(root, d))]
        for f in files:
            fp = os.path.join(root, f)
            if not is_protected(fp) and _safe_remove(fp):
                removed += 1
        try:
            os.rmdir(root)
        except Exception:
            pass
    return removed


# ── EXECUTE CLEAN (called after user confirms) ────────────────────────────────

def execute_clean(scan_result: dict) -> dict:
    """
    Takes the scan summary and actually performs the deletions.
    Returns a report of what was done.
    """
    report = {
        "temp_deleted":    0,
        "cache_deleted":   0,
        "junk_deleted":    0,
        "dumps_deleted":   0,
        "dupes_deleted":   0,
        "errors":          0,
        "freed_mb":        0.0,
    }

    freed_bytes = 0

    # ── Temp files ──
    for fp in scan_result.get("temp_files", {}).get("paths", []):
        if is_protected(fp):
            continue
        try:
            sz = os.path.getsize(fp)
            if _safe_remove(fp):
                report["temp_deleted"] += 1
                freed_bytes += sz
        except Exception:
            report["errors"] += 1

    # ── Browser cache dirs ──
    for cache_dir in BROWSER_CACHE_DIRS:
        if os.path.exists(cache_dir) and not is_protected(cache_dir):
            n = _safe_rmtree(cache_dir)
            report["cache_deleted"] += n

    # ── Junk files ──
    for fp in scan_result.get("junk_files", {}).get("paths", []):
        if is_protected(fp):
            continue
        try:
            sz = os.path.getsize(fp)
            if _safe_remove(fp):
                report["junk_deleted"] += 1
                freed_bytes += sz
        except Exception:
            report["errors"] += 1

    # ── Error dumps ──
    for fp in scan_result.get("error_dumps", {}).get("paths", []):
        if is_protected(fp):
            continue
        try:
            sz = os.path.getsize(fp)
            if _safe_remove(fp):
                report["dumps_deleted"] += 1
                freed_bytes += sz
        except Exception:
            report["errors"] += 1

    # ── Duplicates ──
    for h, group in scan_result.get("duplicates", {}).get("groups", {}).items():
        for fp in group.get("remove", []):
            if is_protected(fp):
                continue
            try:
                sz = os.path.getsize(fp)
                if _safe_remove(fp):
                    report["dupes_deleted"] += 1
                    freed_bytes += sz
            except Exception:
                report["errors"] += 1

    # ── Empty Recycle Bin via PowerShell ──
    try:
        import subprocess
        subprocess.run(
            ["powershell", "-Command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
            capture_output=True, timeout=15
        )
    except Exception:
        pass

    report["freed_mb"] = round(freed_bytes / (1024**2), 1)
    return report


def format_scan_summary(scan: dict) -> str:
    """Human-readable scan summary for FRIDAY to speak/display."""
    lines = ["Here's what I found, Boss:"]
    if scan["temp_files"]["count"]:
        lines.append(f"  • {scan['temp_files']['count']} temp files ({scan['temp_files']['size_mb']} MB)")
    if scan["browser_cache"]["count"]:
        lines.append(f"  • {scan['browser_cache']['count']} browser cache files ({scan['browser_cache']['size_mb']} MB)")
    if scan["junk_files"]["count"]:
        lines.append(f"  • {scan['junk_files']['count']} junk files ({scan['junk_files']['size_mb']} MB)")
    if scan["error_dumps"]["count"]:
        lines.append(f"  • {scan['error_dumps']['count']} crash dump files ({scan['error_dumps']['size_mb']} MB)")
    if scan["duplicates"]["count"]:
        lines.append(f"  • {scan['duplicates']['count']} duplicate files ({scan['duplicates']['size_mb']} MB)")
    lines.append(f"\nTotal recoverable: {scan['total_mb']} MB")
    lines.append("\nShall I go ahead and clean it all up?")
    return "\n".join(lines)


def format_clean_report(report: dict) -> str:
    """Human-readable report after cleaning."""
    total = (report["temp_deleted"] + report["cache_deleted"] +
             report["junk_deleted"] + report["dumps_deleted"] + report["dupes_deleted"])
    lines = [f"All done, Boss. Freed {report['freed_mb']} MB."]
    if report["temp_deleted"]:    lines.append(f"  • {report['temp_deleted']} temp files removed")
    if report["cache_deleted"]:   lines.append(f"  • {report['cache_deleted']} browser cache files cleared")
    if report["junk_deleted"]:    lines.append(f"  • {report['junk_deleted']} junk files deleted")
    if report["dumps_deleted"]:   lines.append(f"  • {report['dumps_deleted']} crash dumps removed")
    if report["dupes_deleted"]:   lines.append(f"  • {report['dupes_deleted']} duplicate files eliminated")
    lines.append("Recycle Bin emptied. System is clean.")
    return "\n".join(lines)
