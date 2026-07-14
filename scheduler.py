"""
F.R.I.D.A.Y. Scheduler Module
Runs scheduled tasks: play music, clean system, launch apps, custom commands.
All stored in SQLite, survives restarts, runs in background thread.
"""

import sqlite3
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Callable

import memory

DB_PATH = memory.DB_PATH

# ── DB SETUP ──────────────────────────────────────────────────────────────────

def init_scheduler_db():
    conn = memory.get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            task_type    TEXT NOT NULL,
            task_data    TEXT NOT NULL,
            schedule     TEXT NOT NULL,
            next_run     REAL NOT NULL,
            enabled      INTEGER DEFAULT 1,
            last_run     REAL DEFAULT NULL,
            run_count    INTEGER DEFAULT 0,
            created      REAL DEFAULT (strftime('%s','now'))
        )
    """)
    conn.commit()
    conn.close()

# ── SCHEDULE TYPES ────────────────────────────────────────────────────────────
# schedule is a JSON dict:
# {"type": "daily",    "time": "08:00"}
# {"type": "weekly",   "time": "08:00", "days": [0,1,2,3,4]}  -- 0=Mon
# {"type": "interval", "minutes": 60}
# {"type": "once",     "datetime": "2025-01-15 09:00"}

def _parse_next_run(schedule: dict, from_time: float = None) -> float:
    """Calculate the next run timestamp from a schedule dict."""
    now = from_time or time.time()
    dt_now = datetime.fromtimestamp(now)
    stype = schedule.get("type", "once")

    if stype == "once":
        dt_str = schedule.get("datetime", "")
        try:
            return datetime.strptime(dt_str, "%Y-%m-%d %H:%M").timestamp()
        except Exception:
            return now + 60

    elif stype == "daily":
        time_str = schedule.get("time", "08:00")
        h, m = map(int, time_str.split(":"))
        candidate = dt_now.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate.timestamp() <= now:
            candidate += timedelta(days=1)
        return candidate.timestamp()

    elif stype == "weekly":
        time_str = schedule.get("time", "08:00")
        days = schedule.get("days", [0])  # list of weekday ints
        h, m = map(int, time_str.split(":"))
        # Find next occurrence among allowed days
        best = None
        for offset in range(8):
            candidate = (dt_now + timedelta(days=offset)).replace(
                hour=h, minute=m, second=0, microsecond=0
            )
            if candidate.weekday() in days and candidate.timestamp() > now:
                if best is None or candidate.timestamp() < best:
                    best = candidate.timestamp()
                break
        return best or (now + 7 * 86400)

    elif stype == "interval":
        minutes = schedule.get("minutes", 60)
        return now + minutes * 60

    return now + 86400


# ── CRUD ──────────────────────────────────────────────────────────────────────

def add_task(name: str, task_type: str, task_data: dict, schedule: dict) -> int:
    """Add a scheduled task. Returns the new task ID."""
    next_run = _parse_next_run(schedule)
    conn = memory.get_db()
    cur = conn.execute("""
        INSERT INTO scheduled_tasks (name, task_type, task_data, schedule, next_run)
        VALUES (?, ?, ?, ?, ?)
    """, (name, task_type, json.dumps(task_data), json.dumps(schedule), next_run))
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    print(f"[Scheduler] Task added: '{name}' (id={task_id}), next run: {datetime.fromtimestamp(next_run).strftime('%Y-%m-%d %H:%M')}")
    return task_id


def remove_task(task_id: int):
    conn = memory.get_db()
    conn.execute("DELETE FROM scheduled_tasks WHERE id=?", (task_id,))
    conn.commit()
    conn.close()


def toggle_task(task_id: int, enabled: bool):
    conn = memory.get_db()
    conn.execute("UPDATE scheduled_tasks SET enabled=? WHERE id=?", (1 if enabled else 0, task_id))
    conn.commit()
    conn.close()


def list_tasks() -> list:
    conn = memory.get_db()
    rows = conn.execute("""
        SELECT id, name, task_type, task_data, schedule, next_run, enabled, last_run, run_count
        FROM scheduled_tasks ORDER BY next_run
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        schedule = json.loads(r["schedule"])
        result.append({
            "id":        r["id"],
            "name":      r["name"],
            "task_type": r["task_type"],
            "task_data": json.loads(r["task_data"]),
            "schedule":  schedule,
            "schedule_human": _human_schedule(schedule),
            "next_run":  datetime.fromtimestamp(r["next_run"]).strftime("%Y-%m-%d %H:%M") if r["next_run"] else "—",
            "last_run":  datetime.fromtimestamp(r["last_run"]).strftime("%Y-%m-%d %H:%M") if r["last_run"] else "Never",
            "run_count": r["run_count"],
            "enabled":   bool(r["enabled"]),
        })
    return result


def _human_schedule(schedule: dict) -> str:
    """Convert schedule dict to readable string."""
    stype = schedule.get("type", "once")
    t = schedule.get("time", "")
    days_map = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

    if stype == "once":
        return f"Once at {schedule.get('datetime','?')}"
    elif stype == "daily":
        return f"Every day at {t}"
    elif stype == "weekly":
        days = [days_map[d] for d in schedule.get("days", [])]
        return f"Every {', '.join(days)} at {t}"
    elif stype == "interval":
        mins = schedule.get("minutes", 60)
        if mins < 60:
            return f"Every {mins} minutes"
        elif mins == 60:
            return "Every hour"
        else:
            return f"Every {mins//60}h {mins%60}m" if mins % 60 else f"Every {mins//60} hours"
    return "Unknown schedule"


def get_due_tasks() -> list:
    """Return tasks that are due to run right now."""
    now = time.time()
    conn = memory.get_db()
    rows = conn.execute("""
        SELECT id, name, task_type, task_data, schedule
        FROM scheduled_tasks
        WHERE enabled=1 AND next_run <= ?
    """, (now,)).fetchall()
    conn.close()
    return [
        {
            "id":        r["id"],
            "name":      r["name"],
            "task_type": r["task_type"],
            "task_data": json.loads(r["task_data"]),
            "schedule":  json.loads(r["schedule"]),
        }
        for r in rows
    ]


def mark_task_ran(task_id: int, schedule: dict):
    """Update last_run, run_count, and calculate next_run."""
    now = time.time()
    stype = schedule.get("type", "once")

    if stype == "once":
        # One-shot — disable it
        conn = memory.get_db()
        conn.execute("""
            UPDATE scheduled_tasks
            SET last_run=?, run_count=run_count+1, enabled=0
            WHERE id=?
        """, (now, task_id))
        conn.commit()
        conn.close()
    else:
        next_run = _parse_next_run(schedule, from_time=now)
        conn = memory.get_db()
        conn.execute("""
            UPDATE scheduled_tasks
            SET last_run=?, run_count=run_count+1, next_run=?
            WHERE id=?
        """, (now, next_run, task_id))
        conn.commit()
        conn.close()


# ── TASK TYPES ────────────────────────────────────────────────────────────────
# task_type:  play_music | launch_app | clean_desktop | scan_filesystem
#             clean_confirmed | volume | speak | chat_command

# ── BACKGROUND RUNNER ─────────────────────────────────────────────────────────

_action_callback: Callable = None   # set by server.py — fn(action_dict) -> dict
_alert_callback:  Callable = None   # set by server.py — fn(title, msg, speak)
_running = False


def set_callbacks(action_fn: Callable, alert_fn: Callable):
    global _action_callback, _alert_callback
    _action_callback = action_fn
    _alert_callback  = alert_fn


def _run_task(task: dict):
    """Execute a single scheduled task."""
    ttype = task["task_type"]
    tdata = task["task_data"]
    name  = task["name"]

    print(f"[Scheduler] Running task: '{name}' ({ttype})")

    if _alert_callback:
        _alert_callback("SCHEDULED TASK", f"Running scheduled task: {name}", speak=False)

    if _action_callback:
        if ttype == "play_music":
            _action_callback({"type": "play_music", "query": tdata.get("query", "")})
        elif ttype == "launch_app":
            _action_callback({"type": "launch_app", "app": tdata.get("app", "")})
        elif ttype == "clean_desktop":
            _action_callback({"type": "clean_desktop"})
        elif ttype == "scan_filesystem":
            result = _action_callback({"type": "scan_filesystem"})
            # Auto-confirm if task says so
            if tdata.get("auto_confirm") and result.get("success"):
                _action_callback({"type": "confirm_clean"})
                if _alert_callback:
                    _alert_callback("SYSTEM CLEAN", "Scheduled system clean complete, Boss.", speak=True)
        elif ttype == "volume":
            _action_callback({"type": "volume", "level": tdata.get("level", 50)})
        elif ttype == "speak":
            if _alert_callback:
                _alert_callback(name, tdata.get("message", ""), speak=True)


def _scheduler_loop():
    global _running
    while _running:
        try:
            due = get_due_tasks()
            for task in due:
                try:
                    _run_task(task)
                except Exception as e:
                    print(f"[Scheduler] Task '{task['name']}' error: {e}")
                finally:
                    mark_task_ran(task["id"], task["schedule"])
        except Exception as e:
            print(f"[Scheduler] Loop error: {e}")
        time.sleep(15)  # check every 15 seconds


def start_scheduler():
    global _running
    if _running:
        return
    init_scheduler_db()
    _running = True
    t = threading.Thread(target=_scheduler_loop, daemon=True)
    t.start()
    print("[Scheduler] Started.")


def stop_scheduler():
    global _running
    _running = False


# ── NATURAL LANGUAGE HELPERS ──────────────────────────────────────────────────

DAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "weekdays": [0,1,2,3,4], "weekends": [5,6],
    "every day": [0,1,2,3,4,5,6], "daily": [0,1,2,3,4,5,6],
}

def parse_schedule_from_text(text: str) -> dict:
    """
    Very basic NL schedule parser.
    Examples:
      "every day at 8am"         → daily 08:00
      "every weekday at 9:30am"  → weekly Mon-Fri 09:30
      "every sunday at noon"     → weekly Sun 12:00
      "every 2 hours"            → interval 120 min
      "every 30 minutes"         → interval 30 min
    """
    text = text.lower().strip()

    # Interval
    import re
    m = re.search(r'every\s+(\d+)\s+(hour|minute|min)', text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        minutes = n * 60 if "hour" in unit else n
        return {"type": "interval", "minutes": minutes}

    # Time extraction
    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', text)
    if time_match:
        h = int(time_match.group(1))
        m_val = int(time_match.group(2) or 0)
        period = time_match.group(3) or ""
        if period == "pm" and h != 12:
            h += 12
        elif period == "am" and h == 12:
            h = 0
        time_str = f"{h:02d}:{m_val:02d}"
    else:
        time_str = "08:00"

    # Special times
    if "noon" in text or "12pm" in text:
        time_str = "12:00"
    if "midnight" in text:
        time_str = "00:00"

    # Day matching
    for keyword, days in DAYS.items():
        if keyword in text:
            if isinstance(days, list):
                if days == [0,1,2,3,4,5,6]:
                    return {"type": "daily", "time": time_str}
                return {"type": "weekly", "time": time_str, "days": days}
            else:
                return {"type": "weekly", "time": time_str, "days": [days]}

    # Default: daily
    return {"type": "daily", "time": time_str}
