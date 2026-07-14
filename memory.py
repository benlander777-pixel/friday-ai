"""
F.R.I.D.A.Y. Memory Module
Stores preferences, conversation summaries, routines, and facts locally using SQLite.
No data ever leaves the machine.
"""

import sqlite3
import json
import os
import time
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "friday_memory.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    c = conn.cursor()

    # Facts FRIDAY knows about the user
    c.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            category  TEXT NOT NULL,
            key       TEXT NOT NULL UNIQUE,
            value     TEXT NOT NULL,
            created   REAL DEFAULT (strftime('%s','now')),
            updated   REAL DEFAULT (strftime('%s','now'))
        )
    """)

    # Named playlists / music preferences
    c.execute("""
        CREATE TABLE IF NOT EXISTS playlists (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL UNIQUE,
            query     TEXT NOT NULL,
            created   REAL DEFAULT (strftime('%s','now'))
        )
    """)

    # App usage tracking
    c.execute("""
        CREATE TABLE IF NOT EXISTS app_usage (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name  TEXT NOT NULL,
            hour      INTEGER,
            day_of_week INTEGER,
            count     INTEGER DEFAULT 1,
            last_used REAL DEFAULT (strftime('%s','now')),
            UNIQUE(app_name, hour, day_of_week)
        )
    """)

    # Scheduled reminders
    c.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            message     TEXT NOT NULL,
            remind_at   REAL NOT NULL,
            repeat_days TEXT DEFAULT NULL,
            fired       INTEGER DEFAULT 0,
            created     REAL DEFAULT (strftime('%s','now'))
        )
    """)

    # Conversation summaries (compressed long-term memory)
    c.execute("""
        CREATE TABLE IF NOT EXISTS summaries (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            summary   TEXT NOT NULL,
            created   REAL DEFAULT (strftime('%s','now'))
        )
    """)

    # Daily briefing cache
    c.execute("""
        CREATE TABLE IF NOT EXISTS briefing_cache (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            date      TEXT NOT NULL UNIQUE,
            content   TEXT NOT NULL,
            created   REAL DEFAULT (strftime('%s','now'))
        )
    """)

    conn.commit()
    conn.close()
    print("[Memory] Database initialised.")


# ── FACTS ─────────────────────────────────────────────────────────────────────

def remember_fact(category: str, key: str, value: str):
    """Store or update a fact about the user."""
    conn = get_db()
    conn.execute("""
        INSERT INTO facts (category, key, value, updated)
        VALUES (?, ?, ?, strftime('%s','now'))
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=strftime('%s','now')
    """, (category, key, value))
    conn.commit()
    conn.close()


def recall_fact(key: str) -> str | None:
    """Retrieve a stored fact."""
    conn = get_db()
    row = conn.execute("SELECT value FROM facts WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def recall_category(category: str) -> dict:
    """Get all facts in a category."""
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM facts WHERE category=?", (category,)).fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def forget_fact(key: str):
    conn = get_db()
    conn.execute("DELETE FROM facts WHERE key=?", (key,))
    conn.commit()
    conn.close()


def get_all_facts() -> list:
    conn = get_db()
    rows = conn.execute("SELECT category, key, value FROM facts ORDER BY category, key").fetchall()
    conn.close()
    return [{"category": r["category"], "key": r["key"], "value": r["value"]} for r in rows]


# ── PLAYLISTS ─────────────────────────────────────────────────────────────────

def save_playlist(name: str, query: str):
    """Save a named playlist mapping."""
    conn = get_db()
    conn.execute("""
        INSERT INTO playlists (name, query)
        VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET query=excluded.query
    """, (name.lower().strip(), query))
    conn.commit()
    conn.close()


def get_playlist(name: str) -> str | None:
    """Get the Spotify query for a named playlist."""
    conn = get_db()
    row = conn.execute("SELECT query FROM playlists WHERE name=?", (name.lower().strip(),)).fetchone()
    conn.close()
    return row["query"] if row else None


def list_playlists() -> list:
    conn = get_db()
    rows = conn.execute("SELECT name, query FROM playlists").fetchall()
    conn.close()
    return [{"name": r["name"], "query": r["query"]} for r in rows]


# ── APP USAGE TRACKING ────────────────────────────────────────────────────────

def track_app_usage(app_name: str):
    """Record that an app was launched — used for smart suggestions."""
    now = datetime.now()
    hour = now.hour
    dow  = now.weekday()  # 0=Monday
    conn = get_db()
    conn.execute("""
        INSERT INTO app_usage (app_name, hour, day_of_week, count, last_used)
        VALUES (?, ?, ?, 1, strftime('%s','now'))
        ON CONFLICT(app_name, hour, day_of_week)
        DO UPDATE SET count=count+1, last_used=strftime('%s','now')
    """, (app_name.lower(), hour, dow))
    conn.commit()
    conn.close()


def get_app_suggestions() -> list:
    """
    Returns apps the user commonly opens at this time of day / day of week.
    Only suggests if count >= 3 (genuine habit, not coincidence).
    """
    now = datetime.now()
    hour = now.hour
    dow  = now.weekday()
    conn = get_db()
    rows = conn.execute("""
        SELECT app_name, count FROM app_usage
        WHERE hour=? AND day_of_week=? AND count >= 3
        ORDER BY count DESC LIMIT 3
    """, (hour, dow)).fetchall()
    conn.close()
    return [r["app_name"] for r in rows]


# ── REMINDERS ────────────────────────────────────────────────────────────────

def add_reminder(message: str, remind_at: float, repeat_days: list = None):
    """Add a reminder. repeat_days = list of weekday ints e.g. [0,1,2,3,4] for weekdays."""
    conn = get_db()
    conn.execute("""
        INSERT INTO reminders (message, remind_at, repeat_days)
        VALUES (?, ?, ?)
    """, (message, remind_at, json.dumps(repeat_days) if repeat_days else None))
    conn.commit()
    conn.close()


def get_due_reminders() -> list:
    """Returns reminders that are due now and haven't fired."""
    now = time.time()
    conn = get_db()
    rows = conn.execute("""
        SELECT id, message, remind_at, repeat_days
        FROM reminders WHERE remind_at <= ? AND fired = 0
    """, (now,)).fetchall()

    due = []
    for r in rows:
        due.append({"id": r["id"], "message": r["message"]})
        repeat = json.loads(r["repeat_days"]) if r["repeat_days"] else None
        if repeat:
            # Reschedule for next occurrence
            next_time = r["remind_at"] + 86400  # advance by 1 day, then align
            conn.execute("UPDATE reminders SET remind_at=?, fired=0 WHERE id=?", (next_time, r["id"]))
        else:
            conn.execute("UPDATE reminders SET fired=1 WHERE id=?", (r["id"],))

    conn.commit()
    conn.close()
    return due


def list_reminders() -> list:
    conn = get_db()
    rows = conn.execute("""
        SELECT id, message, remind_at, repeat_days, fired
        FROM reminders ORDER BY remind_at
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            "id":      r["id"],
            "message": r["message"],
            "time":    datetime.fromtimestamp(r["remind_at"]).strftime("%Y-%m-%d %H:%M"),
            "repeat":  json.loads(r["repeat_days"]) if r["repeat_days"] else None,
            "fired":   bool(r["fired"]),
        })
    return result


def delete_reminder(reminder_id: int):
    conn = get_db()
    conn.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
    conn.commit()
    conn.close()


# ── CONVERSATION SUMMARY ──────────────────────────────────────────────────────

def save_summary(summary: str):
    conn = get_db()
    conn.execute("INSERT INTO summaries (summary) VALUES (?)", (summary,))
    conn.commit()
    conn.close()


def get_recent_summaries(limit: int = 5) -> list:
    conn = get_db()
    rows = conn.execute("""
        SELECT summary FROM summaries ORDER BY created DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [r["summary"] for r in rows]


# ── BRIEFING CACHE ────────────────────────────────────────────────────────────

def cache_briefing(content: str):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    conn.execute("""
        INSERT INTO briefing_cache (date, content)
        VALUES (?, ?)
        ON CONFLICT(date) DO UPDATE SET content=excluded.content
    """, (today, content))
    conn.commit()
    conn.close()


def get_cached_briefing() -> str | None:
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    row = conn.execute("SELECT content FROM briefing_cache WHERE date=?", (today,)).fetchone()
    conn.close()
    return row["content"] if row else None


# ── MEMORY CONTEXT (injected into AI prompt) ─────────────────────────────────

def build_memory_context() -> str:
    """
    Builds a compact string of relevant memory to inject into the AI prompt,
    so FRIDAY remembers things across sessions.
    """
    lines = []

    facts = get_all_facts()
    if facts:
        lines.append("What I know about the user:")
        for f in facts[:20]:  # cap at 20 facts to keep prompt short
            lines.append(f"  - {f['key']}: {f['value']}")

    playlists = list_playlists()
    if playlists:
        lines.append("Named playlists the user has saved:")
        for p in playlists:
            lines.append(f"  - '{p['name']}' → search: {p['query']}")

    summaries = get_recent_summaries(3)
    if summaries:
        lines.append("Recent conversation context:")
        for s in summaries:
            lines.append(f"  - {s}")

    suggestions = get_app_suggestions()
    if suggestions:
        lines.append(f"Apps user typically opens at this time: {', '.join(suggestions)}")

    return "\n".join(lines) if lines else ""


# Initialise on import
init_db()
