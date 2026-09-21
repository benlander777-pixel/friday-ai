"""
F.R.I.D.A.Y. Network Monitor Module
- Internet speed and ping
- Connected devices on local network
- Intrusion detection (new unknown devices)
- Connection drop alerts
"""

import subprocess
import socket
import time
import threading
import re
import requests

import memory
from platform_utils import IS_WINDOWS, which_first, run_silent

_alert_cb   = None
_net_running = False
_known_devices: set = set()
_last_online = True

PING_HOST    = "8.8.8.8"
ALERT_COOLDOWN = 300  # 5 min between same alerts
_last_alerts: dict = {}


def set_alert_callback(fn):
    global _alert_cb
    _alert_cb = fn


def _fire(atype: str, title: str, msg: str, speak: bool = True):
    now = time.time()
    if now - _last_alerts.get(atype, 0) < ALERT_COOLDOWN:
        return
    _last_alerts[atype] = now
    if _alert_cb:
        _alert_cb(title, msg, speak)


# ── PING ──────────────────────────────────────────────────────────────────────

def ping(host: str = PING_HOST) -> float | None:
    """Returns ping in ms, or None if unreachable."""
    try:
        if IS_WINDOWS:
            cmd = ["ping", "-n", "1", "-w", "2000", host]
        else:
            cmd = ["ping", "-c", "1", "-W", "2", host]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        match = re.search(r"Average = (\d+)ms", result.stdout)   # Windows summary line
        if match:
            return float(match.group(1))
        match = re.search(r"time[=<]\s*([\d.]+)\s*ms", result.stdout)   # Windows/Linux per-reply line
        if match:
            return float(match.group(1))
        return None
    except Exception:
        return None


def is_online() -> bool:
    try:
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return True
    except Exception:
        return False


# ── SPEED TEST ────────────────────────────────────────────────────────────────

def test_speed() -> dict:
    """
    Basic speed test using a small file download from a public CDN.
    Returns {download_mbps, ping_ms}
    """
    result = {"download_mbps": None, "ping_ms": None, "error": None}

    # Ping
    result["ping_ms"] = ping()

    # Download speed — fetch a ~5MB test file
    try:
        url = "https://speed.cloudflare.com/__down?bytes=5000000"
        start = time.time()
        r = requests.get(url, timeout=20, stream=True)
        total = 0
        for chunk in r.iter_content(chunk_size=65536):
            total += len(chunk)
        elapsed = time.time() - start
        if elapsed > 0:
            mbps = round((total * 8) / (elapsed * 1_000_000), 2)
            result["download_mbps"] = mbps
    except Exception as e:
        result["error"] = str(e)

    return result


# ── CONNECTED DEVICES ─────────────────────────────────────────────────────────

def get_connected_devices() -> list:
    """
    List devices on the local network via the neighbor/ARP table.
    Windows: `arp -a`. Linux: `ip neigh show` (falls back to `arp -a` if
    iproute2 isn't installed, though it ships standard on virtually every
    modern distro including Arch).
    Returns list of {ip, mac, known}
    """
    devices = []
    try:
        if IS_WINDOWS:
            result = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10)
            for line in result.stdout.splitlines():
                match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+([\w-]{17})\s+(\w+)", line)
                if match:
                    ip, mac, t = match.group(1), match.group(2).upper(), match.group(3)
                    if t == "dynamic" and not ip.endswith(".255"):
                        devices.append({"ip": ip, "mac": mac, "known": mac in _get_known_macs()})
        elif which_first("ip"):
            result = run_silent(["ip", "neigh", "show"], timeout=10)
            if result:
                for line in result.stdout.splitlines():
                    match = re.search(
                        r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}).*?lladdr\s+([0-9a-fA-F:]{17})\s+(\w+)",
                        line
                    )
                    if match:
                        ip, mac, state = match.group(1), match.group(2).upper(), match.group(3)
                        if state not in ("FAILED", "INCOMPLETE") and not ip.endswith(".255"):
                            devices.append({"ip": ip, "mac": mac, "known": mac in _get_known_macs()})
        else:
            result = run_silent(["arp", "-a"], timeout=10)
            if result:
                for line in result.stdout.splitlines():
                    match = re.search(r"\(([\d.]+)\)\s+at\s+([0-9a-fA-F:]{17})", line)
                    if match:
                        ip, mac = match.group(1), match.group(2).upper()
                        if not ip.endswith(".255"):
                            devices.append({"ip": ip, "mac": mac, "known": mac in _get_known_macs()})
    except Exception as e:
        print(f"[Network] Device scan error: {e}")

    return devices


def _get_known_macs() -> set:
    """Get MACs that have been saved as trusted."""
    known = memory.recall_fact("trusted_macs")
    if known:
        import json
        try:
            return set(json.loads(known))
        except Exception:
            return set()
    return set()


def trust_device(mac: str):
    """Mark a device MAC as trusted."""
    import json
    macs = _get_known_macs()
    macs.add(mac.upper())
    memory.remember_fact("network", "trusted_macs", json.dumps(list(macs)))


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "Unknown"


def get_network_summary() -> dict:
    return {
        "online":   is_online(),
        "local_ip": get_local_ip(),
        "ping_ms":  ping(),
        "devices":  get_connected_devices(),
    }


# ── BACKGROUND MONITOR ────────────────────────────────────────────────────────

def _monitor_loop():
    global _net_running, _known_devices, _last_online

    # Load known devices from memory
    _known_devices = _get_known_macs()

    while _net_running:
        try:
            # Connection check
            online = is_online()
            if not online and _last_online:
                _fire("offline", "CONNECTION LOST",
                      "Boss, your internet connection has gone down.", speak=True)
            elif online and not _last_online:
                _fire("online", "CONNECTION RESTORED",
                      "Internet connection restored, Boss.", speak=False)
            _last_online = online

            # Device scan for intruders
            if online:
                devices = get_connected_devices()
                known_macs = _get_known_macs()
                for d in devices:
                    if d["mac"] not in known_macs and d["mac"] not in _known_devices:
                        _fire(
                            f"new_device_{d['mac']}",
                            "NEW DEVICE DETECTED",
                            f"Unknown device joined your network, Boss. IP: {d['ip']}, MAC: {d['mac']}. "
                            f"Tell me to trust it if it's yours.",
                            speak=True
                        )
                        _known_devices.add(d["mac"])

            # High ping alert
            p = ping()
            if p and p > 200:
                _fire("high_ping", "HIGH LATENCY",
                      f"Your ping is {round(p)}ms, Boss. Network may be congested.", speak=False)

        except Exception as e:
            print(f"[Network Monitor] Error: {e}")

        time.sleep(30)   # check every 30 seconds


def start_monitor():
    global _net_running
    if _net_running:
        return
    _net_running = True
    t = threading.Thread(target=_monitor_loop, daemon=True)
    t.start()
    print("[Network Monitor] Started.")


def stop_monitor():
    global _net_running
    _net_running = False
