"""
F.R.I.D.A.Y. Email & Calendar Module
Connects to Outlook via win32com (installed with pywin32).
Read emails, summarise inbox, create calendar events, check today's schedule.
Falls back gracefully if Outlook is not installed.
"""

from datetime import datetime, timedelta

OUTLOOK_AVAILABLE = False

try:
    import win32com.client
    import pythoncom
    OUTLOOK_AVAILABLE = True
except ImportError:
    pass


def _get_outlook():
    """Get Outlook application instance."""
    if not OUTLOOK_AVAILABLE:
        return None
    try:
        pythoncom.CoInitialize()
        return win32com.client.Dispatch("Outlook.Application")
    except Exception as e:
        print(f"[Email] Outlook connect error: {e}")
        return None


def _get_namespace():
    """Get Outlook MAPI namespace."""
    ol = _get_outlook()
    if not ol:
        return None
    try:
        return ol.GetNamespace("MAPI")
    except Exception as e:
        print(f"[Email] Namespace error: {e}")
        return None


# ── EMAIL ─────────────────────────────────────────────────────────────────────

def get_unread_emails(max_count: int = 10) -> list:
    """Get unread emails from inbox."""
    if not OUTLOOK_AVAILABLE:
        return []
    ns = _get_namespace()
    if not ns:
        return []
    try:
        inbox = ns.GetDefaultFolder(6)  # 6 = Inbox
        messages = inbox.Items
        messages.Sort("[ReceivedTime]", True)  # newest first

        emails = []
        for msg in messages:
            if len(emails) >= max_count:
                break
            try:
                if msg.UnRead:
                    emails.append({
                        "subject":  msg.Subject or "(No subject)",
                        "sender":   msg.SenderName or "Unknown",
                        "email":    msg.SenderEmailAddress or "",
                        "received": msg.ReceivedTime.strftime("%Y-%m-%d %H:%M") if msg.ReceivedTime else "",
                        "preview":  (msg.Body or "")[:200].strip().replace("\n", " "),
                        "unread":   True,
                    })
            except Exception:
                continue
        return emails
    except Exception as e:
        print(f"[Email] Get unread error: {e}")
        return []


def get_recent_emails(max_count: int = 10) -> list:
    """Get recent emails (read + unread)."""
    if not OUTLOOK_AVAILABLE:
        return []
    ns = _get_namespace()
    if not ns:
        return []
    try:
        inbox = ns.GetDefaultFolder(6)
        messages = inbox.Items
        messages.Sort("[ReceivedTime]", True)

        emails = []
        for msg in messages:
            if len(emails) >= max_count:
                break
            try:
                emails.append({
                    "subject":  msg.Subject or "(No subject)",
                    "sender":   msg.SenderName or "Unknown",
                    "email":    msg.SenderEmailAddress or "",
                    "received": msg.ReceivedTime.strftime("%Y-%m-%d %H:%M") if msg.ReceivedTime else "",
                    "preview":  (msg.Body or "")[:200].strip().replace("\n", " "),
                    "unread":   msg.UnRead,
                })
            except Exception:
                continue
        return emails
    except Exception as e:
        print(f"[Email] Get recent error: {e}")
        return []


def get_email_summary() -> str:
    """Returns a natural language summary of the inbox."""
    if not OUTLOOK_AVAILABLE:
        return "Outlook is not installed or not accessible."

    unread = get_unread_emails(5)
    if not unread:
        return "Your inbox is clear, Boss. No unread emails."

    lines = [f"You have {len(unread)} unread email{'s' if len(unread)>1 else ''}, Boss:"]
    for e in unread[:5]:
        lines.append(f"  • From {e['sender']}: \"{e['subject']}\"")

    return "\n".join(lines)


def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email via Outlook."""
    if not OUTLOOK_AVAILABLE:
        return {"success": False, "message": "Outlook not available."}
    ol = _get_outlook()
    if not ol:
        return {"success": False, "message": "Could not connect to Outlook."}
    try:
        mail = ol.CreateItem(0)  # 0 = MailItem
        mail.To = to
        mail.Subject = subject
        mail.Body = body
        mail.Send()
        return {"success": True, "message": f"Email sent to {to}."}
    except Exception as e:
        return {"success": False, "message": f"Send error: {str(e)}"}


def search_emails(query: str, max_count: int = 5) -> list:
    """Search emails by subject or sender."""
    if not OUTLOOK_AVAILABLE:
        return []
    ns = _get_namespace()
    if not ns:
        return []
    try:
        inbox = ns.GetDefaultFolder(6)
        messages = inbox.Items
        messages.Sort("[ReceivedTime]", True)
        q = query.lower()
        results = []
        for msg in messages:
            if len(results) >= max_count:
                break
            try:
                if q in (msg.Subject or "").lower() or q in (msg.SenderName or "").lower():
                    results.append({
                        "subject":  msg.Subject or "(No subject)",
                        "sender":   msg.SenderName or "Unknown",
                        "received": msg.ReceivedTime.strftime("%Y-%m-%d %H:%M") if msg.ReceivedTime else "",
                        "preview":  (msg.Body or "")[:300].strip().replace("\n", " "),
                        "unread":   msg.UnRead,
                    })
            except Exception:
                continue
        return results
    except Exception as e:
        print(f"[Email] Search error: {e}")
        return []


# ── CALENDAR ──────────────────────────────────────────────────────────────────

def get_todays_events() -> list:
    """Get calendar events for today."""
    if not OUTLOOK_AVAILABLE:
        return []
    ns = _get_namespace()
    if not ns:
        return []
    try:
        calendar = ns.GetDefaultFolder(9)  # 9 = Calendar
        items = calendar.Items
        items.IncludeRecurrences = True
        items.Sort("[Start]")

        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        events = []
        for item in items:
            try:
                start = item.Start
                if hasattr(start, 'date'):
                    start_date = start.date()
                else:
                    start_date = datetime.strptime(str(start)[:10], "%Y-%m-%d").date()

                if start_date == today:
                    events.append({
                        "subject":  item.Subject or "Untitled",
                        "start":    str(item.Start)[11:16] if item.Start else "?",
                        "end":      str(item.End)[11:16] if item.End else "?",
                        "location": item.Location or "",
                        "body":     (item.Body or "")[:200],
                    })
            except Exception:
                continue

        return sorted(events, key=lambda e: e["start"])
    except Exception as e:
        print(f"[Calendar] Today events error: {e}")
        return []


def get_upcoming_events(days: int = 7) -> list:
    """Get events in the next N days."""
    if not OUTLOOK_AVAILABLE:
        return []
    ns = _get_namespace()
    if not ns:
        return []
    try:
        calendar = ns.GetDefaultFolder(9)
        items = calendar.Items
        items.IncludeRecurrences = True
        items.Sort("[Start]")

        today = datetime.now().date()
        end_date = today + timedelta(days=days)
        events = []

        for item in items:
            try:
                start = item.Start
                if hasattr(start, 'date'):
                    start_date = start.date()
                else:
                    start_date = datetime.strptime(str(start)[:10], "%Y-%m-%d").date()

                if today <= start_date <= end_date:
                    events.append({
                        "subject":  item.Subject or "Untitled",
                        "date":     str(start_date),
                        "start":    str(item.Start)[11:16],
                        "end":      str(item.End)[11:16] if item.End else "?",
                        "location": item.Location or "",
                    })
            except Exception:
                continue

        return sorted(events, key=lambda e: (e["date"], e["start"]))[:20]
    except Exception as e:
        print(f"[Calendar] Upcoming error: {e}")
        return []


def create_event(subject: str, start: str, end: str = None,
                 location: str = "", body: str = "") -> dict:
    """
    Create a calendar event.
    start/end format: "YYYY-MM-DD HH:MM"
    """
    if not OUTLOOK_AVAILABLE:
        return {"success": False, "message": "Outlook not available."}
    ol = _get_outlook()
    if not ol:
        return {"success": False, "message": "Could not connect to Outlook."}
    try:
        appt = ol.CreateItem(1)  # 1 = AppointmentItem
        appt.Subject  = subject
        appt.Location = location
        appt.Body     = body

        start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M")
        appt.Start = start_dt.strftime("%m/%d/%Y %H:%M")

        if end:
            end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M")
        else:
            end_dt = start_dt + timedelta(hours=1)
        appt.End = end_dt.strftime("%m/%d/%Y %H:%M")

        appt.Save()
        return {
            "success": True,
            "message": f"Event '{subject}' created for {start}."
        }
    except Exception as e:
        return {"success": False, "message": f"Calendar error: {str(e)}"}


def get_calendar_summary() -> str:
    """Natural language summary of today's calendar."""
    if not OUTLOOK_AVAILABLE:
        return "Outlook calendar not accessible."

    events = get_todays_events()
    if not events:
        return "Your calendar is clear today, Boss."

    lines = [f"You have {len(events)} event{'s' if len(events)>1 else ''} today:"]
    for e in events:
        loc = f" at {e['location']}" if e["location"] else ""
        lines.append(f"  • {e['start']} — {e['subject']}{loc}")

    return "\n".join(lines)


def is_available() -> bool:
    return OUTLOOK_AVAILABLE
