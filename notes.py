"""
F.R.I.D.A.Y. Notes Module
Create, search, list, delete notes locally.
Optional: sync to Outlook tasks/calendar.
"""

import sqlite3
import os
import time
from datetime import datetime
import memory

def init_notes_db():
    conn = memory.get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            title    TEXT NOT NULL,
            body     TEXT NOT NULL,
            tags     TEXT DEFAULT '',
            pinned   INTEGER DEFAULT 0,
            created  REAL DEFAULT (strftime('%s','now')),
            updated  REAL DEFAULT (strftime('%s','now'))
        )
    """)
    conn.commit()
    conn.close()


def add_note(title: str, body: str, tags: list = None) -> int:
    conn = memory.get_db()
    cur = conn.execute(
        "INSERT INTO notes (title, body, tags) VALUES (?, ?, ?)",
        (title.strip(), body.strip(), ",".join(tags or []))
    )
    note_id = cur.lastrowid
    conn.commit()
    conn.close()
    print(f"[Notes] Added note '{title}' (id={note_id})")
    return note_id


def get_note(note_id: int) -> dict | None:
    conn = memory.get_db()
    row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_dict(row)


def list_notes(limit: int = 20, pinned_first: bool = True) -> list:
    conn = memory.get_db()
    order = "pinned DESC, updated DESC" if pinned_first else "updated DESC"
    rows = conn.execute(f"SELECT * FROM notes ORDER BY {order} LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def search_notes(query: str) -> list:
    conn = memory.get_db()
    q = f"%{query}%"
    rows = conn.execute(
        "SELECT * FROM notes WHERE title LIKE ? OR body LIKE ? OR tags LIKE ? ORDER BY updated DESC",
        (q, q, q)
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def update_note(note_id: int, title: str = None, body: str = None, tags: list = None):
    conn = memory.get_db()
    if title is not None:
        conn.execute("UPDATE notes SET title=?, updated=strftime('%s','now') WHERE id=?", (title, note_id))
    if body is not None:
        conn.execute("UPDATE notes SET body=?, updated=strftime('%s','now') WHERE id=?", (body, note_id))
    if tags is not None:
        conn.execute("UPDATE notes SET tags=?, updated=strftime('%s','now') WHERE id=?", (",".join(tags), note_id))
    conn.commit()
    conn.close()


def pin_note(note_id: int, pinned: bool = True):
    conn = memory.get_db()
    conn.execute("UPDATE notes SET pinned=? WHERE id=?", (1 if pinned else 0, note_id))
    conn.commit()
    conn.close()


def delete_note(note_id: int):
    conn = memory.get_db()
    conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
    conn.commit()
    conn.close()


def _row_to_dict(row) -> dict:
    return {
        "id":      row["id"],
        "title":   row["title"],
        "body":    row["body"],
        "tags":    row["tags"].split(",") if row["tags"] else [],
        "pinned":  bool(row["pinned"]),
        "created": datetime.fromtimestamp(row["created"]).strftime("%Y-%m-%d %H:%M"),
        "updated": datetime.fromtimestamp(row["updated"]).strftime("%Y-%m-%d %H:%M"),
    }


def get_notes_summary() -> str:
    notes = list_notes(5)
    if not notes:
        return "No notes saved yet, Boss."
    lines = [f"You have {len(list_notes(100))} note(s). Most recent:"]
    for n in notes[:5]:
        pin = "📌 " if n["pinned"] else ""
        lines.append(f"  • {pin}{n['title']}")
    return "\n".join(lines)


def sync_note_to_outlook(note_id: int) -> dict:
    """Sync a note to Outlook as a task."""
    note = get_note(note_id)
    if not note:
        return {"success": False, "message": "Note not found."}
    try:
        import email_cal as outlook
        if not outlook.is_available():
            return {"success": False, "message": "Outlook not available."}
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
        ol = win32com.client.Dispatch("Outlook.Application")
        task = ol.CreateItem(3)  # 3 = TaskItem
        task.Subject = note["title"]
        task.Body    = note["body"]
        task.Save()
        return {"success": True, "message": f"Note '{note['title']}' synced to Outlook Tasks."}
    except Exception as e:
        return {"success": False, "message": f"Sync error: {e}"}


# Init on import
init_notes_db()
