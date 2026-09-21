"""
F.R.I.D.A.Y. Routines Module
Multi-step task chains: "morning routine" runs several actions in sequence.
Stored in SQLite, triggerable by voice or schedule.
"""

import sqlite3
import json
import time
import threading
from typing import Callable

import memory

_action_cb: Callable = None
_alert_cb:  Callable = None


def set_callbacks(action_fn: Callable, alert_fn: Callable):
    global _action_cb, _alert_cb
    _action_cb = action_fn
    _alert_cb  = alert_fn


def init_routines_db():
    conn = memory.get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS routines (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            steps       TEXT NOT NULL,
            created     REAL DEFAULT (strftime('%s','now')),
            last_run    REAL DEFAULT NULL,
            run_count   INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def add_routine(name: str, steps: list, description: str = "") -> int:
    """
    steps = list of action dicts, e.g.:
    [
        {"type": "volume", "level": 60},
        {"type": "play_music", "query": "morning chill"},
        {"type": "launch_app", "app": "chrome"},
        {"type": "speak", "message": "Good morning! Have a great day."},
    ]
    Optional: {"delay": 2} as a step means pause 2 seconds
    """
    conn = memory.get_db()
    cur = conn.execute(
        "INSERT INTO routines (name, description, steps) VALUES (?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET steps=excluded.steps, description=excluded.description",
        (name.lower().strip(), description, json.dumps(steps))
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    print(f"[Routines] Saved routine '{name}' with {len(steps)} steps.")
    return rid


def get_routine(name: str) -> dict | None:
    conn = memory.get_db()
    row = conn.execute(
        "SELECT * FROM routines WHERE name=?", (name.lower().strip(),)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id":          row["id"],
        "name":        row["name"],
        "description": row["description"],
        "steps":       json.loads(row["steps"]),
        "last_run":    row["last_run"],
        "run_count":   row["run_count"],
    }


def get_routine_by_id(rid: int) -> dict | None:
    conn = memory.get_db()
    row = conn.execute("SELECT * FROM routines WHERE id=?", (rid,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id":          row["id"],
        "name":        row["name"],
        "description": row["description"],
        "steps":       json.loads(row["steps"]),
        "last_run":    row["last_run"],
        "run_count":   row["run_count"],
    }


def update_routine_by_id(rid: int, name: str = None, steps: list = None, description: str = None):
    conn = memory.get_db()
    if name is not None:
        conn.execute("UPDATE routines SET name=? WHERE id=?", (name.lower().strip(), rid))
    if steps is not None:
        conn.execute("UPDATE routines SET steps=? WHERE id=?", (json.dumps(steps), rid))
    if description is not None:
        conn.execute("UPDATE routines SET description=? WHERE id=?", (description, rid))
    conn.commit()
    conn.close()


def list_routines() -> list:
    conn = memory.get_db()
    rows = conn.execute(
        "SELECT id, name, description, steps, run_count, last_run FROM routines ORDER BY name"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        from datetime import datetime
        result.append({
            "id":          r["id"],
            "name":        r["name"],
            "description": r["description"],
            "steps":       json.loads(r["steps"]),
            "run_count":   r["run_count"],
            "last_run":    datetime.fromtimestamp(r["last_run"]).strftime("%Y-%m-%d %H:%M")
                           if r["last_run"] else "Never",
        })
    return result


def delete_routine(name: str):
    conn = memory.get_db()
    conn.execute("DELETE FROM routines WHERE name=?", (name.lower().strip(),))
    conn.commit()
    conn.close()


def delete_routine_by_id(rid: int):
    conn = memory.get_db()
    conn.execute("DELETE FROM routines WHERE id=?", (rid,))
    conn.commit()
    conn.close()


def run_routine(name: str) -> dict:
    """
    Execute a routine by name.
    Runs steps sequentially in a background thread.
    Returns immediately with status.
    """
    routine = get_routine(name)
    if not routine:
        return {"success": False, "message": f"No routine named '{name}' found, Boss."}

    def _execute():
        steps = routine["steps"]
        total = len(steps)
        if _alert_cb:
            _alert_cb(
                "ROUTINE STARTED",
                f"Running routine '{routine['name']}' — {total} steps.",
                speak=False
            )

        for i, step in enumerate(steps, 1):
            try:
                if step.get("type") == "delay":
                    secs = step.get("seconds", 2)
                    time.sleep(secs)
                    continue

                if step.get("type") == "speak":
                    if _alert_cb:
                        _alert_cb(routine["name"], step.get("message", ""), speak=True)
                    continue

                if _action_cb:
                    result = _action_cb(step)
                    print(f"[Routines] Step {i}/{total}: {step.get('type')} → {result.get('message','')}")

                time.sleep(1)   # small gap between steps

            except Exception as e:
                print(f"[Routines] Step {i} error: {e}")

        # Update run stats
        conn = memory.get_db()
        conn.execute(
            "UPDATE routines SET last_run=strftime('%s','now'), run_count=run_count+1 WHERE name=?",
            (routine["name"],)
        )
        conn.commit()
        conn.close()

        if _alert_cb:
            _alert_cb("ROUTINE COMPLETE", f"'{routine['name']}' finished.", speak=False)

    t = threading.Thread(target=_execute, daemon=True)
    t.start()

    steps_desc = ", ".join(s.get("type","?").replace("_"," ") for s in routine["steps"] if s.get("type") != "delay")
    return {
        "success": True,
        "message": f"Running routine '{routine['name']}': {steps_desc}."
    }


def run_routine_by_id(rid: int) -> dict:
    conn = memory.get_db()
    row = conn.execute("SELECT name FROM routines WHERE id=?", (rid,)).fetchone()
    conn.close()
    if not row:
        return {"success": False, "message": "Routine not found."}
    return run_routine(row["name"])


# ── PRESET ROUTINES ───────────────────────────────────────────────────────────

def install_presets():
    """Install sensible default routines if none exist."""
    existing = list_routines()
    if existing:
        return  # Don't overwrite user's routines

    # Morning routine
    add_routine("morning", [
        {"type": "volume",     "level": 40},
        {"type": "speak",      "message": "Good morning, Boss. Starting your morning routine."},
        {"type": "play_music", "query": "morning chill playlist"},
        {"type": "launch_app", "app": "chrome"},
        {"type": "delay", "seconds": 2},
    ], description="Starts music, opens Chrome, sets volume")

    # Work mode
    add_routine("work mode", [
        {"type": "volume",     "level": 30},
        {"type": "speak",      "message": "Activating work mode. Stay focused, Boss."},
        {"type": "launch_app", "app": "vscode"},
        {"type": "play_music", "query": "focus lofi beats"},
    ], description="Opens VSCode with focus music")

    # Wind down
    add_routine("wind down", [
        {"type": "volume",     "level": 25},
        {"type": "speak",      "message": "Winding down for the evening. Good work today, Boss."},
        {"type": "play_music", "query": "evening relaxing playlist"},
    ], description="Evening wind-down music")

    # Gaming mode
    add_routine("gaming", [
        {"type": "volume",     "level": 70},
        {"type": "speak",      "message": "Gaming mode activated. Good luck, Boss."},
        {"type": "launch_app", "app": "steam"},
        {"type": "play_music", "query": "gaming hype playlist"},
    ], description="Launches Steam with hype music")

    print("[Routines] Preset routines installed.")


# Init
init_routines_db()
install_presets()
