"""
F.R.I.D.A.Y. Briefing & Health Alert Module
- Daily briefing: weather + time + smart greeting
- PC health: proactive alerts when CPU/RAM/disk spike
- Reminder checker: fires due reminders
"""

import time
import threading
import requests
import psutil
from datetime import datetime

import memory

# ── CONFIG ────────────────────────────────────────────────────────────────────
# Free weather API — no key needed for basic use (wttr.in)
WEATHER_URL = "https://wttr.in/?format=%C+%t+%h+humidity&m"

# Health thresholds
CPU_ALERT_THRESHOLD    = 90   # % sustained for CPU_ALERT_DURATION seconds
CPU_ALERT_DURATION     = 30   # seconds CPU must stay high before alerting
RAM_ALERT_THRESHOLD    = 90   # %
DISK_ALERT_THRESHOLD   = 90   # %
ALERT_COOLDOWN         = 300  # seconds between same-type alerts

# ── STATE ──────────────────────────────────────────────────────────────────────
_alert_callback   = None   # set by server.py — fn(title, message, speak=True)
_cpu_high_since   = None
_last_alerts      = {}     # {alert_type: timestamp}
_monitor_running  = False


def set_alert_callback(fn):
    """Register the function FRIDAY calls to fire an alert."""
    global _alert_callback
    _alert_callback = fn


def _fire_alert(alert_type: str, title: str, message: str, speak: bool = True):
    """Fire an alert if cooldown has passed."""
    global _last_alerts
    now = time.time()
    last = _last_alerts.get(alert_type, 0)
    if now - last < ALERT_COOLDOWN:
        return
    _last_alerts[alert_type] = now
    if _alert_callback:
        _alert_callback(title, message, speak)


# ── WEATHER ───────────────────────────────────────────────────────────────────

def get_weather() -> str:
    """Fetch current weather from wttr.in (no API key needed)."""
    # Check if user has set a location in memory
    location = memory.recall_fact("location") or ""
    url = f"https://wttr.in/{location}?format=%C,+%t,+%h+humidity&m"
    try:
        r = requests.get(url, timeout=6)
        if r.status_code == 200:
            return r.text.strip()
    except Exception:
        pass
    return "Weather unavailable"


# ── DAILY BRIEFING ────────────────────────────────────────────────────────────

def build_daily_briefing() -> str:
    """
    Builds a morning briefing string.
    Returns cached version if already generated today.
    """
    cached = memory.get_cached_briefing()
    if cached:
        return cached

    now  = datetime.now()
    hour = now.hour
    day  = now.strftime("%A, %B %d")

    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    name = memory.recall_fact("name")
    address = f", {name}" if name else ", Boss"

    weather = get_weather()

    reminders = memory.list_reminders()
    today_str = now.strftime("%Y-%m-%d")
    due_today = [r for r in reminders if r["time"].startswith(today_str) and not r["fired"]]

    suggestions = memory.get_app_suggestions()

    lines = [f"{greeting}{address}. Today is {day}."]
    lines.append(f"Current weather: {weather}.")

    # Calendar events
    try:
        import email_cal as outlook
        if outlook.is_available():
            events = outlook.get_todays_events()
            if events:
                lines.append(f"You have {len(events)} calendar event{'s' if len(events)>1 else ''} today:")
                for e in events[:3]:
                    lines.append(f"  {e['start']} — {e['subject']}")
            # Unread emails
            unread = outlook.get_unread_emails(3)
            if unread:
                lines.append(f"You have {len(unread)} unread email{'s' if len(unread)>1 else ''}.")
                for e in unread[:2]:
                    lines.append(f"  From {e['sender']}: {e['subject']}")
    except Exception:
        pass

    if due_today:
        lines.append(f"You have {len(due_today)} reminder{'s' if len(due_today)>1 else ''} today.")
        for r in due_today[:2]:
            lines.append(f"  {r['message']} at {r['time'][11:]}")

    if suggestions:
        app_list = ", ".join(suggestions)
        lines.append(f"You usually open {app_list} around this time.")

    briefing = " ".join(lines)
    memory.cache_briefing(briefing)
    return briefing


# ── PC HEALTH MONITOR ─────────────────────────────────────────────────────────

def _monitor_loop():
    """Background thread — checks system health every 10 seconds."""
    global _cpu_high_since, _monitor_running

    while _monitor_running:
        try:
            cpu  = psutil.cpu_percent(interval=2)
            mem  = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/").percent

            # CPU sustained high
            if cpu >= CPU_ALERT_THRESHOLD:
                if _cpu_high_since is None:
                    _cpu_high_since = time.time()
                elif time.time() - _cpu_high_since >= CPU_ALERT_DURATION:
                    _fire_alert(
                        "cpu_high",
                        "CPU OVERLOAD",
                        f"Boss, your CPU has been at {round(cpu)}% for over {CPU_ALERT_DURATION} seconds. "
                        f"You may want to check what's running."
                    )
                    _cpu_high_since = None  # reset after alert
            else:
                _cpu_high_since = None

            # RAM high
            if mem >= RAM_ALERT_THRESHOLD:
                _fire_alert(
                    "ram_high",
                    "MEMORY WARNING",
                    f"RAM usage is at {round(mem)}%, Boss. "
                    f"Consider closing some applications."
                )

            # Disk almost full
            if disk >= DISK_ALERT_THRESHOLD:
                _fire_alert(
                    "disk_full",
                    "STORAGE WARNING",
                    f"Your drive is {round(disk)}% full. "
                    f"Want me to scan for junk files and free up some space?"
                )

            # Check due reminders
            due = memory.get_due_reminders()
            for reminder in due:
                _fire_alert(
                    f"reminder_{reminder['id']}",
                    "REMINDER",
                    reminder["message"],
                    speak=True
                )

        except Exception as e:
            print(f"[Health Monitor] Error: {e}")

        time.sleep(10)


def start_monitor():
    """Start the background health monitor thread."""
    global _monitor_running
    if _monitor_running:
        return
    _monitor_running = True
    t = threading.Thread(target=_monitor_loop, daemon=True)
    t.start()
    print("[Health Monitor] Started.")


def stop_monitor():
    global _monitor_running
    _monitor_running = False
