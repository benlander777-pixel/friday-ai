"""
F.R.I.D.A.Y. Backend Server
Requirements: pip install flask flask-cors requests psutil spotipy
"""

import os, glob, json, time, shutil, fnmatch, subprocess, threading, logging, webbrowser
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests as req

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("friday")

import config
import cleaner as fs_cleaner
import memory
import briefing as briefing_mod
import scheduler as task_scheduler
import email_cal as outlook
import screen as screen_mod
import notes as notes_mod
import news as news_mod
import network as net_mod
import routines as routines_mod
import prizepicks as pp_mod
import face_auth as face_mod
from platform_utils import IS_WINDOWS, IS_LINUX, which_first, run_silent, user_dir

# Holds the last scan result until user confirms
_pending_scan = None

# ── Alert callback (fires toasts + TTS from health monitor) ──────────────────
_alert_queue = []
_alert_lock  = threading.Lock()

def _handle_alert(title: str, message: str, speak: bool = True):
    with _alert_lock:
        _alert_queue.append({"title": title, "message": message, "speak": speak})

app = Flask(__name__, static_folder="static")
CORS(app)

@app.after_request
def add_csp_header(response):
    """Permissive CSP since this is a local-only desktop app."""
    response.headers["Content-Security-Policy"] = (
        "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:; "
        "connect-src * data: blob:; "
        "img-src * data: blob:; "
        "font-src * data:; "
        "media-src * data: blob:;"
    )
    return response

conversation_history = []

# ── Spotify ──────────────────────────────────────────────────────────────────
sp = None
sp_lock = threading.Lock()

def get_spotify():
    global sp
    with sp_lock:
        if sp is not None:
            return sp
        if not config.SPOTIFY_CLIENT_ID or not config.SPOTIFY_CLIENT_SECRET:
            print("[Spotify] Not configured — add SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET to .env")
            return None
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyOAuth

            # Delete stale cache so fresh token is fetched with new scopes
            cache = ".spotify_cache"

            auth = SpotifyOAuth(
                client_id     = config.SPOTIFY_CLIENT_ID,
                client_secret = config.SPOTIFY_CLIENT_SECRET,
                redirect_uri  = config.SPOTIFY_REDIRECT_URI,
                scope         = config.SPOTIFY_SCOPE,
                username      = config.SPOTIFY_USERNAME,
                cache_path    = cache,
                open_browser  = True,
            )
            sp = spotipy.Spotify(auth_manager=auth)
            user = sp.current_user()
            print(f"[Spotify] Connected as: {user['display_name']}")
            return sp
        except Exception as e:
            print(f"[Spotify] init error: {e}")
            sp = None
            return None


def get_best_device(client) -> str | None:
    """
    Returns the best device ID to use for playback.
    Priority: active device → computer device → first available device.
    """
    try:
        devices = client.devices().get("devices", [])
        print(f"[Spotify] Devices found: {[(d['name'], d['type'], d['is_active']) for d in devices]}")

        if not devices:
            # Spotify app might not be registered yet — open it and wait
            launch_cmd = None
            if IS_WINDOWS:
                sp_path = os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")
                if os.path.exists(sp_path):
                    launch_cmd = [sp_path]
            else:
                native = which_first("spotify")
                if native:
                    launch_cmd = [native]
                elif which_first("flatpak"):
                    launch_cmd = ["flatpak", "run", "com.spotify.Client"]

            if launch_cmd:
                print("[Spotify] Opening Spotify app...")
                subprocess.Popen(launch_cmd)
                time.sleep(4)
                devices = client.devices().get("devices", [])

        if not devices:
            return None

        # Prefer the currently active device
        for d in devices:
            if d["is_active"]:
                print(f"[Spotify] Using active device: {d['name']}")
                return d["id"]

        # Prefer a Computer type device over phone/TV
        for d in devices:
            if d["type"].lower() == "computer":
                print(f"[Spotify] Using computer device: {d['name']}")
                return d["id"]

        # Fall back to first available
        print(f"[Spotify] Using first device: {devices[0]['name']}")
        return devices[0]["id"]

    except Exception as e:
        print(f"[Spotify] Device detection error: {e}")
        return None


def spotify_play(query: str) -> dict:
    client = get_spotify()
    if not client:
        return {"success": False, "message": "Spotify not connected. Make sure Spotify is authorised."}
    try:
        device_id = get_best_device(client)

        if not device_id:
            return {
                "success": False,
                "message": (
                    "No Spotify device found, Boss. Make sure Spotify is open and "
                    "you've played something in it at least once to register the device."
                )
            }

        # Search — try track first, then artist, then playlist
        print(f"[Spotify] Searching for: {query}")
        results = client.search(q=query, limit=5, type="track,artist,playlist,album")

        uri  = None
        msg  = ""

        tracks = results.get("tracks", {}).get("items", [])
        if tracks:
            track = tracks[0]
            uri    = track["uri"]
            name   = track["name"]
            artist = track["artists"][0]["name"]
            msg    = f"Playing '{name}' by {artist} on Spotify."

        if not uri:
            playlists = results.get("playlists", {}).get("items", [])
            playlists = [p for p in playlists if p]  # filter None
            if playlists:
                uri = playlists[0]["uri"]
                msg = f"Playing playlist '{playlists[0]['name']}' on Spotify."

        if not uri:
            albums = results.get("albums", {}).get("items", [])
            if albums:
                uri = albums[0]["uri"]
                msg = f"Playing album '{albums[0]['name']}' on Spotify."

        if not uri:
            return {"success": False, "message": f"Couldn't find '{query}' on Spotify."}

        # Start playback
        print(f"[Spotify] Starting playback: {uri} on device {device_id}")
        if uri.startswith("spotify:track:"):
            client.start_playback(device_id=device_id, uris=[uri])
        else:
            client.start_playback(device_id=device_id, context_uri=uri)

        return {"success": True, "message": msg}

    except Exception as e:
        err = str(e)
        print(f"[Spotify] Playback error: {err}")

        # Common error: Premium required
        if "premium" in err.lower():
            return {"success": False, "message": "Spotify Premium is required for playback control, Boss."}

        # Device went inactive between detection and playback
        if "No active device" in err or "404" in err:
            return {
                "success": False,
                "message": "Spotify lost the device mid-request. Click play once in Spotify then try again, Boss."
            }

        return {"success": False, "message": f"Spotify error: {err}"}


def spotify_control(action: str) -> dict:
    client = get_spotify()
    if not client:
        return {"success": False, "message": "Spotify not connected."}
    try:
        device_id = get_best_device(client)
        if action == "pause":
            client.pause_playback(device_id=device_id)
            return {"success": True, "message": "Paused."}
        elif action == "resume":
            client.start_playback(device_id=device_id)
            return {"success": True, "message": "Resumed."}
        elif action == "next":
            client.next_track(device_id=device_id)
            return {"success": True, "message": "Skipped to next track."}
        elif action == "prev":
            client.previous_track(device_id=device_id)
            return {"success": True, "message": "Previous track."}
        elif action == "current":
            playing = client.current_playback()
            if playing and playing.get("item"):
                name   = playing["item"]["name"]
                artist = playing["item"]["artists"][0]["name"]
                return {"success": True, "message": f"Currently playing: '{name}' by {artist}."}
            return {"success": True, "message": "Nothing playing right now."}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ── AI Chat ───────────────────────────────────────────────────────────────────

def build_prompt(user_message: str, history: list) -> str:
    memory_ctx = memory.build_memory_context()
    memory_section = f"\n\nWhat I remember:\n{memory_ctx}" if memory_ctx else ""
    outlook_status = "Outlook available." if outlook.is_available() else "Outlook not installed."

    base = f"""You are FRIDAY, an advanced AI assistant modeled after Tony Stark's AI.
You are helpful, precise, and occasionally witty. Keep responses concise.
You have full control of the user's Windows computer.
{outlook_status}{memory_section}

Output ACTION lines AFTER your reply. Available actions:

COMPUTER CONTROL:
ACTION: {{"type": "launch_app",        "app": "chrome"}}
ACTION: {{"type": "open_url",          "url": "https://..."}}
ACTION: {{"type": "volume",            "level": 50}}
ACTION: {{"type": "search_files",      "query": "filename"}}
ACTION: {{"type": "screenshot"}}
ACTION: {{"type": "analyse_screen",    "prompt": "what is on the screen?"}}
ACTION: {{"type": "summarise_clipboard"}}
ACTION: {{"type": "system_command",    "command": "shutdown|restart|sleep|lock|hibernate"}}

MUSIC:
ACTION: {{"type": "play_music",        "query": "search term"}}
ACTION: {{"type": "music_control",     "action": "pause|resume|next|prev|current"}}
ACTION: {{"type": "save_playlist",     "name": "morning", "query": "chill morning"}}

CLEANING:
ACTION: {{"type": "clean_desktop"}}
ACTION: {{"type": "scan_filesystem"}}
ACTION: {{"type": "confirm_clean"}}

MEMORY:
ACTION: {{"type": "remember",          "category": "preference", "key": "name", "value": "Ben"}}
ACTION: {{"type": "add_reminder",      "message": "check emails", "time": "09:00", "date": "2025-01-01"}}

SCHEDULING:
ACTION: {{"type": "schedule_task",     "name": "Morning music", "task_type": "play_music", "task_data": {{"query": "chill"}}, "schedule": {{"type": "daily", "time": "08:00"}}}}

ROUTINES:
ACTION: {{"type": "run_routine",       "name": "morning"}}
ACTION: {{"type": "list_routines"}}

NOTES:
ACTION: {{"type": "add_note",          "title": "Meeting notes", "body": "discussed Q4 targets"}}
ACTION: {{"type": "search_notes",      "query": "meeting"}}
ACTION: {{"type": "list_notes"}}

NEWS:
ACTION: {{"type": "get_news",          "category": "all|fox|cyber|sports"}}

SPORTS BETTING (PrizePicks):
ACTION: {{"type": "get_projections",   "league": "NFL|NBA|MLB|NHL"}}
ACTION: {{"type": "get_parlays",       "leagues": ["NFL","NBA"], "legs": 3, "count": 3}}

NETWORK:
ACTION: {{"type": "network_status"}}
ACTION: {{"type": "speed_test"}}

EMAIL / CALENDAR:
ACTION: {{"type": "email_summary"}}
ACTION: {{"type": "calendar_summary"}}
ACTION: {{"type": "create_event",      "subject": "Meeting", "start": "2025-01-15 14:00", "end": "2025-01-15 15:00"}}
ACTION: {{"type": "send_email",        "to": "email@example.com", "subject": "Hi", "body": "message"}}


RULES:
- scan_filesystem first, then confirm_clean only after user says yes.
- Only send emails when user explicitly confirms recipient and content.
- For shutdown/restart, warn user and confirm before using system_command.
- Parlay suggestions are exploratory combinations from live lines, not predictions of outcomes.
- Always reply in character as FRIDAY. Occasionally call the user "Boss".
- Keep responses under 3 sentences unless detail is needed.
- Never output raw JSON outside ACTION lines."""

    history_text = ""
    for msg in history[-12:]:
        role = "User" if msg["role"] == "user" else "FRIDAY"
        history_text += f"{role}: {msg['content']}\n"

    return f"{base}\n\nConversation:\n{history_text}FRIDAY:"

# ============================================================
#  ADD THIS TO YOUR DESKTOP server.py
#  Add this route BEFORE the @app.route("/") line
#  This lets your Pi send security alerts to your desktop FRIDAY
# ============================================================

@app.route("/api/pi_alert", methods=["POST"])
def pi_alert():
    """Receive security alerts from FRIDAY Pi server."""
    data     = request.json or {}
    title    = data.get("title", "Pi Alert")
    message  = data.get("message", "")
    severity = data.get("severity", "info")
    source   = data.get("source", "Pi")

    log.warning(f"PI ALERT [{severity}] from {source}: {title} — {message[:100]}")

    with _alert_lock:
        _alert_queue.append({
            "title":   f"PI: {title}",
            "message": message,
            "speak":   severity in ("critical", "high"),
        })

    return jsonify({"success": True})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json or {}
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"response": "I didn't catch that, Boss.", "actions": []})

    conversation_history.append({"role": "user", "content": user_message})
    full_prompt = build_prompt(user_message, conversation_history)

    try:
        response = req.post(config.OLLAMA_URL, json={
            "model":   config.OLLAMA_MODEL,
            "prompt":  full_prompt,
            "stream":  False,
            "options": {"temperature": 0.7, "num_predict": 400},
        }, timeout=60)

        if response.status_code != 200:
            return jsonify({"response": "Neural network error. Check Ollama.", "actions": []})

        ai_text = response.json().get("response", "").strip()
        conversation_history.append({"role": "assistant", "content": ai_text})

        actions, clean_lines = [], []
        for line in ai_text.split("\n"):
            if line.strip().startswith("ACTION:"):
                try:
                    actions.append(json.loads(line.strip()[7:].strip()))
                except:
                    pass
            else:
                clean_lines.append(line)

        clean_response = "\n".join(clean_lines).strip()

        results = [execute_action(a) for a in actions]

        return jsonify({"response": clean_response, "actions": actions, "action_results": results})

    except req.exceptions.ConnectionError:
        return jsonify({"response": "Ollama is offline. Run: ollama serve", "actions": [], "error": "connection"})
    except Exception as e:
        return jsonify({"response": f"Error: {e}", "actions": [], "error": str(e)})


# ── Action Router ─────────────────────────────────────────────────────────────
def execute_action(action: dict) -> dict:
    t = action.get("type", "")
    if t == "launch_app":
        memory.track_app_usage(action.get("app", ""))
        return launch_app(action.get("app", ""))
    if t == "play_music":        return spotify_play(action.get("query", ""))
    if t == "music_control":     return spotify_control(action.get("action", "current"))
    if t == "clean_desktop":     return clean_desktop()
    if t == "scan_filesystem":   return scan_filesystem()
    if t == "confirm_clean":     return confirm_clean()
    if t == "remember":
        memory.remember_fact(action.get("category","general"), action.get("key",""), action.get("value",""))
        return {"success": True, "message": f"Got it — I'll remember that."}
    if t == "save_playlist":
        memory.save_playlist(action.get("name",""), action.get("query",""))
        return {"success": True, "message": f"Saved playlist '{action.get('name','')}'."}
    if t == "add_reminder":
        try:
            from datetime import datetime
            dt_str = f"{action.get('date','')} {action.get('time','00:00')}"
            ts = datetime.strptime(dt_str.strip(), "%Y-%m-%d %H:%M").timestamp()
            memory.add_reminder(action.get("message",""), ts)
            return {"success": True, "message": "Reminder set."}
        except Exception as e:
            return {"success": False, "message": f"Reminder error: {e}"}
    if t == "schedule_task":
        try:
            schedule = action.get("schedule", {"type":"daily","time":"08:00"})
            task_id = task_scheduler.add_task(
                name      = action.get("name","Task"),
                task_type = action.get("task_type","speak"),
                task_data = action.get("task_data",{}),
                schedule  = schedule,
            )
            human = task_scheduler._human_schedule(schedule)
            return {"success": True, "message": f"Scheduled '{action.get('name')}' — {human}."}
        except Exception as e:
            return {"success": False, "message": f"Schedule error: {e}"}
    if t == "email_summary":
        return {"success": True, "message": outlook.get_email_summary()}
    if t == "calendar_summary":
        return {"success": True, "message": outlook.get_calendar_summary()}
    if t == "create_event":
        return outlook.create_event(
            action.get("subject",""),
            action.get("start",""),
            action.get("end"),
            action.get("location",""),
        )
    if t == "send_email":
        return outlook.send_email(
            action.get("to",""),
            action.get("subject",""),
            action.get("body",""),
        )
    if t == "screenshot":
        return screen_mod.screenshot_and_save()
    if t == "analyse_screen":
        prompt = action.get("prompt", "What is on the screen? Describe what you see.")
        result = screen_mod.analyse_screen(prompt)
        return {"success": True, "message": result}
    if t == "summarise_clipboard":
        cb = screen_mod._get_clipboard()
        ctype = screen_mod._detect_clipboard_type(cb)
        if ctype == "url":
            return {"success": True, "message": screen_mod.summarise_clipboard_url(cb)}
        elif ctype == "code":
            return {"success": True, "message": screen_mod.explain_clipboard_code(cb)}
        return {"success": True, "message": f"Clipboard contains: {cb[:200]}"}
    if t == "add_note":
        nid = notes_mod.add_note(action.get("title","Note"), action.get("body",""))
        return {"success": True, "message": f"Note saved: '{action.get('title','Note')}'."}
    if t == "search_notes":
        results = notes_mod.search_notes(action.get("query",""))
        if not results:
            return {"success": True, "message": "No notes found matching that search."}
        lines = "\n".join(f"  • {n['title']}: {n['body'][:80]}" for n in results[:5])
        return {"success": True, "message": f"Found {len(results)} note(s):\n{lines}"}
    if t == "list_notes":
        return {"success": True, "message": notes_mod.get_notes_summary()}
    if t == "get_news":
        category = action.get("category", "all")
        if category == "fox":
            items = news_mod.get_fox_headlines(5)
            text = "Fox News headlines:\n" + "\n".join(f"  • {h['title']}" for h in items)
        elif category == "cyber":
            items = news_mod.get_cyber_headlines(5)
            text = "Cybersecurity news:\n" + "\n".join(f"  • {h['title']}" for h in items)
        elif category == "sports":
            items = news_mod.get_espn_headlines(5)
            text = "Sports headlines:\n" + "\n".join(f"  • {h['title']}" for h in items)
        else:
            text = news_mod.format_headlines(news_mod.get_all_headlines(3))
        return {"success": True, "message": text}
    if t == "get_parlays":
        leagues = action.get("leagues", ["NFL","NBA","MLB","NHL"])
        legs = action.get("legs", 3)
        count = action.get("count", 3)
        parlays = pp_mod.suggest_parlays(leagues=leagues, count=count, legs=legs)
        return {"success": True, "message": pp_mod.format_parlay_suggestions(parlays), "parlays": parlays}
    if t == "get_projections":
        league = action.get("league")
        return {"success": True, "message": pp_mod.format_projections_summary(league)}
    if t == "network_status":
        summary = net_mod.get_network_summary()
        msg = (f"Network status: {'Online' if summary['online'] else 'OFFLINE'}. "
               f"Local IP: {summary['local_ip']}. "
               f"Ping: {summary['ping_ms']}ms. "
               f"{len(summary['devices'])} device(s) on network.")
        return {"success": True, "message": msg}
    if t == "speed_test":
        return {"success": True, "message": "Speed test running — this takes about 10 seconds, Boss."}
    if t == "run_routine":
        return routines_mod.run_routine(action.get("name", ""))
    if t == "list_routines":
        rlist = routines_mod.list_routines()
        if not rlist:
            return {"success": True, "message": "No routines saved yet, Boss."}
        lines = "\n".join(f"  • {r['name']}: {r['description']}" for r in rlist)
        return {"success": True, "message": f"Available routines:\n{lines}"}
    if t == "system_command":
        cmd = action.get("command","").lower()
        if IS_WINDOWS:
            cmds = {
                "shutdown":  "shutdown /s /t 30",
                "restart":   "shutdown /r /t 30",
                "sleep":     "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
                "lock":      "rundll32.exe user32.dll,LockWorkStation",
                "hibernate": "shutdown /h",
            }
            if cmd not in cmds:
                return {"success": False, "message": f"Unknown system command: {cmd}"}
            subprocess.Popen(cmds[cmd], shell=True)
        else:
            cmds = {
                "shutdown":  ["systemctl", "poweroff"],
                "restart":   ["systemctl", "reboot"],
                "sleep":     ["systemctl", "suspend"],
                "lock":      ["loginctl", "lock-session"],
                "hibernate": ["systemctl", "hibernate"],
            }
            if cmd not in cmds:
                return {"success": False, "message": f"Unknown system command: {cmd}"}
            subprocess.Popen(cmds[cmd])
        return {"success": True, "message": f"System {cmd} initiated, Boss."}
    if t == "open_url":
        return open_url(action.get("url", ""))
    if t in ("volume","set_volume"):
        set_volume(action.get("level", 50))
        return {"success": True, "message": f"Volume set to {action.get('level',50)}%"}
    if t == "search_files":
        return {"success": True, "files": search_files(action.get("query",""))}
    return {"success": False, "message": "Unknown action"}


# ── App Launcher ──────────────────────────────────────────────────────────────
COMMON_APPS_WINDOWS = {
    "notepad":      "notepad.exe",
    "calculator":   "calc.exe",
    "paint":        "mspaint.exe",
    "explorer":     "explorer.exe",
    "chrome":       r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "firefox":      r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "edge":         "msedge.exe",
    "spotify":      os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
    "vlc":          r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    "vscode":       os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
    "word":         r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
    "excel":        r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
    "cmd":          "cmd.exe",
    "powershell":   "powershell.exe",
    "task manager": "taskmgr.exe",
    "settings":     "ms-settings:",
    "discord":      os.path.expandvars(r"%LOCALAPPDATA%\Discord\Update.exe"),
    "steam":        r"C:\Program Files (x86)\Steam\steam.exe",
    "terminal":     "wt.exe",
}

# Each value is a list of candidate [binary, *args] commands, tried in order —
# first one found on PATH wins. Prefers KDE Plasma-native apps first since
# that's the reference desktop, with common alternatives as fallbacks.
COMMON_APPS_LINUX = {
    "notepad":      [["kate"], ["gedit"], ["kwrite"], ["featherpad"], ["xed"]],
    "calculator":   [["kcalc"], ["gnome-calculator"], ["qalculate-gtk"]],
    "paint":        [["kolourpaint"], ["gimp"]],
    "explorer":     [["dolphin"], ["nautilus"], ["thunar"], ["pcmanfm"]],
    "chrome":       [["google-chrome-stable"], ["google-chrome"], ["chromium"], ["chromium-browser"]],
    "firefox":      [["firefox"]],
    "edge":         [["microsoft-edge-stable"], ["microsoft-edge"]],
    "spotify":      [["spotify"]],
    "vlc":          [["vlc"]],
    "vscode":       [["code"]],
    "word":         [["libreoffice", "--writer"]],
    "excel":        [["libreoffice", "--calc"]],
    "cmd":          [["konsole"], ["gnome-terminal"], ["xterm"]],
    "powershell":   [["konsole"], ["gnome-terminal"], ["xterm"]],
    "task manager": [["plasma-systemmonitor"], ["ksysguard"], ["gnome-system-monitor"]],
    "settings":     [["systemsettings"], ["systemsettings5"], ["gnome-control-center"]],
    "discord":      [["discord"]],
    "steam":        [["steam"]],
    "terminal":     [["konsole"], ["gnome-terminal"], ["xterm"]],
}

COMMON_APPS = COMMON_APPS_LINUX if IS_LINUX else COMMON_APPS_WINDOWS


def launch_app(name: str) -> dict:
    key = name.lower().strip()

    if IS_WINDOWS:
        path = COMMON_APPS.get(key)
        if path:
            try:
                if path.startswith("ms-"):
                    subprocess.Popen(["start", path], shell=True)
                else:
                    subprocess.Popen([path])
                return {"success": True, "message": f"Launched {name}"}
            except FileNotFoundError:
                pass
        try:
            subprocess.Popen(["start", name], shell=True)
            return {"success": True, "message": f"Launching {name}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # Linux
    for cmd in COMMON_APPS.get(key, [[key]]):
        binary = which_first(cmd[0])
        if not binary:
            continue
        try:
            subprocess.Popen([binary, *cmd[1:]])
            return {"success": True, "message": f"Launched {name}"}
        except Exception:
            continue
    return {"success": False, "message": f"Could not find an app for '{name}' on this system."}


def open_url(url: str) -> dict:
    if not url:
        return {"success": False, "message": "No URL provided."}
    try:
        webbrowser.open(url)
        return {"success": True, "message": f"Opened {url}"}
    except Exception as e:
        return {"success": False, "message": f"Could not open URL: {e}"}


# ── Desktop Cleaner ───────────────────────────────────────────────────────────
def clean_desktop() -> dict:
    desktop     = user_dir("Desktop")
    sort_folder = os.path.join(desktop, config.DESKTOP_SORT_FOLDER)
    os.makedirs(sort_folder, exist_ok=True)

    moved = 0
    deleted = 0

    for item in os.listdir(desktop):
        item_path = os.path.join(desktop, item)

        # Never touch the sort folder itself or system/hidden files
        if item == config.DESKTOP_SORT_FOLDER:
            continue
        if os.path.isdir(item_path):
            continue
        if item.startswith("."):
            continue

        # Delete junk files
        is_junk = any(fnmatch.fnmatch(item.lower(), pat.lower()) for pat in config.JUNK_PATTERNS)
        if is_junk:
            try:
                os.remove(item_path)
                deleted += 1
                continue
            except:
                pass

        # Skip .lnk shortcuts (keep them visible on desktop)
        _, ext = os.path.splitext(item)
        if ext.lower() == ".lnk":
            continue

        # Categorise and move
        category = "Other"
        for cat, exts in config.FILE_CATEGORIES.items():
            if ext.lower() in exts:
                category = cat
                break

        dest_dir = os.path.join(sort_folder, category)
        os.makedirs(dest_dir, exist_ok=True)

        dest = os.path.join(dest_dir, item)
        counter = 1
        base, extension = os.path.splitext(item)
        while os.path.exists(dest):
            dest = os.path.join(dest_dir, f"{base}_{counter}{extension}")
            counter += 1

        try:
            shutil.move(item_path, dest)
            moved += 1
        except:
            pass

    return {
        "success": True,
        "message": (
            f"Desktop cleaned. {moved} files organised into '{config.DESKTOP_SORT_FOLDER}', "
            f"{deleted} junk files removed. Your shortcuts are untouched."
        )
    }


# ── Volume ────────────────────────────────────────────────────────────────────
def _set_volume_windows(level: int):
    script = f"""
$vol = {level / 100.0}
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume{{
 int f();int g();int h();int i();
 int SetMasterVolumeLevelScalar(float fLevel,System.Guid pguidEventContext);
 int j();int GetMasterVolumeLevelScalar(out float pfLevel);
 int k();int l();int m();int n();
 int SetMute([MarshalAs(UnmanagedType.Bool)]bool bMute,System.Guid pguidEventContext);
 int GetMute(out bool pbMute);
}}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice{{int Activate(ref System.Guid id,int clsCtx,int activationParams,out IAudioEndpointVolume aev);}}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator{{int f();int GetDefaultAudioEndpoint(int dataFlow,int role,out IMMDevice endpoint);}}
[ComImport,Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]class MMDeviceEnumeratorComObject{{}}
public class Audio{{
 static IAudioEndpointVolume Vol(){{
  var e=new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;IMMDevice d=null;
  Marshal.ThrowExceptionForHR(e.GetDefaultAudioEndpoint(0,1,out d));
  IAudioEndpointVolume v=null;var id=typeof(IAudioEndpointVolume).GUID;
  Marshal.ThrowExceptionForHR(d.Activate(ref id,23,0,out v));return v;}}
 public static float Volume{{
  get{{float v=-1;Marshal.ThrowExceptionForHR(Vol().GetMasterVolumeLevelScalar(out v));return v;}}
  set{{Marshal.ThrowExceptionForHR(Vol().SetMasterVolumeLevelScalar(value,System.Guid.Empty));}}}}
}}
'@
[Audio]::Volume = $vol
"""
    subprocess.run(["powershell", "-Command", script], capture_output=True, timeout=10)


def _set_volume_linux(level: int):
    # Try WirePlumber (modern PipeWire default), then PulseAudio/pipewire-pulse,
    # then plain ALSA — whichever is actually running wins.
    if which_first("wpctl"):
        run_silent(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level / 100.0}"])
    elif which_first("pactl"):
        run_silent(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
    elif which_first("amixer"):
        run_silent(["amixer", "-D", "pulse", "sset", "Master", f"{level}%"])
        run_silent(["amixer", "sset", "Master", f"{level}%"])


def set_volume(level: int):
    level = max(0, min(100, int(level)))
    try:
        if IS_WINDOWS:
            _set_volume_windows(level)
        else:
            _set_volume_linux(level)
    except Exception:
        pass


# ── File Search ───────────────────────────────────────────────────────────────
def search_files(query: str) -> list:
    results = []
    for path in [user_dir("Desktop"), user_dir("Documents"), user_dir("Downloads")]:
        if os.path.exists(path):
            results += glob.glob(os.path.join(path, f"*{query}*"))
    return results[:10]


# ── File System Cleaner ────────────────────────────────────────────────────────
def scan_filesystem() -> dict:
    """Scan and store result — does NOT delete anything yet."""
    global _pending_scan
    try:
        _pending_scan = fs_cleaner.scan_system()
        summary = fs_cleaner.format_scan_summary(_pending_scan)
        return {"success": True, "message": summary, "scan": _pending_scan}
    except Exception as e:
        return {"success": False, "message": f"Scan error: {e}"}


def confirm_clean() -> dict:
    """Execute the clean after user confirmed."""
    global _pending_scan
    if not _pending_scan:
        return {"success": False, "message": "No pending scan. Ask me to scan your system first."}
    try:
        report = fs_cleaner.execute_clean(_pending_scan)
        _pending_scan = None
        return {"success": True, "message": fs_cleaner.format_clean_report(report)}
    except Exception as e:
        return {"success": False, "message": f"Clean error: {e}"}


@app.route("/api/filesystem/scan", methods=["POST"])
def api_filesystem_scan():
    result = scan_filesystem()
    return jsonify(result)


@app.route("/api/filesystem/confirm", methods=["POST"])
def api_filesystem_confirm():
    result = confirm_clean()
    return jsonify(result)


@app.route("/api/filesystem/cancel", methods=["POST"])
def api_filesystem_cancel():
    global _pending_scan
    _pending_scan = None
    return jsonify({"success": True, "message": "Clean cancelled."})


# ── System Metrics ────────────────────────────────────────────────────────────
@app.route("/api/system", methods=["GET"])
def system_info():
    try:
        import psutil
        cpu        = psutil.cpu_percent(interval=0.5)
        cpu_freq   = psutil.cpu_freq()
        mem        = psutil.virtual_memory()
        swap       = psutil.swap_memory()
        disk       = psutil.disk_usage("/")
        net        = psutil.net_io_counters()
        per_cpu    = psutil.cpu_percent(interval=0, percpu=True)

        cpu_temp = None
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for entries in temps.values():
                    if entries:
                        cpu_temp = round(entries[0].current, 1)
                        break
        except:
            pass

        gpu_info = []
        try:
            import GPUtil
            for g in GPUtil.getGPUs():
                gpu_info.append({"name":g.name,"load":round(g.load*100,1),"mem_used":round(g.memoryUsed),"mem_total":round(g.memoryTotal),"temp":round(g.temperature,1)})
        except:
            pass

        procs = []
        for p in sorted(psutil.process_iter(["pid","name","cpu_percent","memory_percent"]),
                        key=lambda x: x.info["cpu_percent"] or 0, reverse=True)[:5]:
            procs.append({"name":p.info["name"],"cpu":round(p.info["cpu_percent"] or 0,1),"mem":round(p.info["memory_percent"] or 0,1)})

        uptime_secs = int(time.time() - psutil.boot_time())
        h, rem = divmod(uptime_secs, 3600)
        m = rem // 60

        return jsonify({
            "cpu": round(cpu,1), "per_cpu":[round(x,1) for x in per_cpu],
            "cpu_freq": round(cpu_freq.current/1000,2) if cpu_freq else None,
            "cpu_freq_max": round(cpu_freq.max/1000,2) if cpu_freq else None,
            "cpu_cores": psutil.cpu_count(logical=False),
            "cpu_threads": psutil.cpu_count(logical=True),
            "cpu_temp": cpu_temp,
            "memory": round(mem.percent,1),
            "memory_used": round(mem.used/(1024**3),2),
            "memory_total": round(mem.total/(1024**3),2),
            "memory_available": round(mem.available/(1024**3),2),
            "swap_used": round(swap.used/(1024**3),2),
            "swap_total": round(swap.total/(1024**3),2),
            "swap_percent": round(swap.percent,1),
            "disk_used": round(disk.used/(1024**3),1),
            "disk_total": round(disk.total/(1024**3),1),
            "disk_percent": round(disk.percent,1),
            "net_sent": round(net.bytes_sent/(1024**2),1),
            "net_recv": round(net.bytes_recv/(1024**2),1),
            "gpu": gpu_info,
            "processes": procs,
            "uptime": f"{h}h {m}m",
        })
    except ImportError:
        return jsonify({"cpu":0,"memory":0,"error":"psutil not installed"})


# ── Spotify Status ────────────────────────────────────────────────────────────
@app.route("/api/spotify/devices", methods=["GET"])
def spotify_devices():
    """Debug endpoint — lists all Spotify devices FRIDAY can see."""
    client = get_spotify()
    if not client:
        return jsonify({"connected": False, "devices": []})
    try:
        devices = client.devices().get("devices", [])
        return jsonify({
            "connected": True,
            "devices": [{"id": d["id"], "name": d["name"], "type": d["type"], "active": d["is_active"]} for d in devices]
        })
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)})


@app.route("/api/spotify/status", methods=["GET"])
def spotify_status():
    client = get_spotify()
    if not client:
        return jsonify({"connected": False})
    try:
        playing = client.current_playback()
        if playing and playing.get("item"):
            return jsonify({
                "connected": True,
                "playing": playing["is_playing"],
                "track": playing["item"]["name"],
                "artist": playing["item"]["artists"][0]["name"],
                "album_art": playing["item"]["album"]["images"][0]["url"] if playing["item"]["album"]["images"] else None,
                "progress": playing["progress_ms"],
                "duration": playing["item"]["duration_ms"],
            })
        return jsonify({"connected": True, "playing": False})
    except:
        return jsonify({"connected": False})


@app.route("/api/spotify/control", methods=["POST"])
def spotify_control_route():
    action = (request.json or {}).get("action","current")
    return jsonify(spotify_control(action))


# ── Ollama Status ─────────────────────────────────────────────────────────────
@app.route("/api/ollama/status", methods=["GET"])
def ollama_status():
    try:
        r = req.get("http://localhost:11434/api/tags", timeout=3)
        if r.status_code == 200:
            return jsonify({"online":True,"models":[m["name"] for m in r.json().get("models",[])]})
    except:
        pass
    return jsonify({"online":False,"models":[]})


@app.route("/api/clear", methods=["POST"])
def clear_history():
    global conversation_history
    conversation_history = []
    return jsonify({"success":True})


@app.route("/api/briefing", methods=["GET"])
def get_briefing():
    try:
        briefing = briefing_mod.build_daily_briefing()
        return jsonify({"success": True, "briefing": briefing})
    except Exception as e:
        return jsonify({"success": False, "briefing": f"Briefing unavailable: {e}"})


@app.route("/api/alerts/poll", methods=["GET"])
def poll_alerts():
    """Frontend polls this to get any pending health alerts."""
    with _alert_lock:
        alerts = list(_alert_queue)
        _alert_queue.clear()
    return jsonify({"alerts": alerts})


@app.route("/api/memory/facts", methods=["GET"])
def get_facts():
    return jsonify({"facts": memory.get_all_facts()})


@app.route("/api/memory/facts", methods=["POST"])
def set_fact():
    data = request.json or {}
    memory.remember_fact(data.get("category","general"), data.get("key",""), data.get("value",""))
    return jsonify({"success": True})


@app.route("/api/memory/facts/<key>", methods=["DELETE"])
def delete_fact(key):
    memory.forget_fact(key)
    return jsonify({"success": True})


@app.route("/api/memory/playlists", methods=["GET"])
def get_playlists():
    return jsonify({"playlists": memory.list_playlists()})


@app.route("/api/memory/reminders", methods=["GET"])
def get_reminders():
    return jsonify({"reminders": memory.list_reminders()})


@app.route("/api/memory/reminders/<int:reminder_id>", methods=["DELETE"])
def delete_reminder(reminder_id):
    memory.delete_reminder(reminder_id)
    return jsonify({"success": True})


@app.route("/api/memory/suggestions", methods=["GET"])
def get_suggestions():
    return jsonify({"suggestions": memory.get_app_suggestions()})


# ── Screen routes ─────────────────────────────────────────────────────────────
@app.route("/api/screen/capture", methods=["POST"])
def capture_screen():
    return jsonify(screen_mod.screenshot_and_save())

@app.route("/api/screen/analyse", methods=["POST"])
def analyse_screen():
    prompt = (request.json or {}).get("prompt", "What is on the screen?")
    result = screen_mod.analyse_screen(prompt)
    return jsonify({"success": True, "description": result})

@app.route("/api/screen/clipboard", methods=["GET"])
def get_clipboard():
    content = screen_mod._get_clipboard()
    ctype   = screen_mod._detect_clipboard_type(content)
    return jsonify({"content": content, "type": ctype})

@app.route("/api/screen/clipboard/act", methods=["POST"])
def act_on_clipboard():
    content = screen_mod._get_clipboard()
    ctype   = screen_mod._detect_clipboard_type(content)
    if ctype == "url":
        result = screen_mod.summarise_clipboard_url(content)
    elif ctype == "code":
        result = screen_mod.explain_clipboard_code(content)
    else:
        result = content[:500]
    return jsonify({"success": True, "result": result, "type": ctype})


# ── Notes routes ──────────────────────────────────────────────────────────────
@app.route("/api/notes", methods=["GET"])
def get_notes():
    return jsonify({"notes": notes_mod.list_notes()})

@app.route("/api/notes", methods=["POST"])
def create_note():
    data = request.json or {}
    nid = notes_mod.add_note(data.get("title","Note"), data.get("body",""), data.get("tags",[]))
    return jsonify({"success": True, "id": nid})

@app.route("/api/notes/search", methods=["POST"])
def search_notes():
    query = (request.json or {}).get("query","")
    return jsonify({"notes": notes_mod.search_notes(query)})

@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
def delete_note(note_id):
    notes_mod.delete_note(note_id)
    return jsonify({"success": True})

@app.route("/api/notes/<int:note_id>/pin", methods=["POST"])
def pin_note(note_id):
    pinned = (request.json or {}).get("pinned", True)
    notes_mod.pin_note(note_id, pinned)
    return jsonify({"success": True})


# ── News routes ───────────────────────────────────────────────────────────────
@app.route("/api/news", methods=["GET"])
def get_news():
    category = request.args.get("category","all")
    if category == "fox":
        return jsonify({"items": news_mod.get_fox_headlines(8)})
    elif category == "cyber":
        return jsonify({"items": news_mod.get_cyber_headlines(8)})
    elif category == "espn":
        return jsonify({"items": news_mod.get_espn_headlines(8)})
    all_h = news_mod.get_all_headlines(5)
    return jsonify({"fox": all_h["fox"], "cyber": all_h["cyber"], "espn": all_h["espn"]})

@app.route("/api/news/brief", methods=["GET"])
def news_brief():
    return jsonify({"brief": news_mod.get_news_brief()})


# ── PrizePicks routes ─────────────────────────────────────────────────────────
@app.route("/api/prizepicks/projections", methods=["GET"])
def get_pp_projections():
    league = request.args.get("league")
    if league:
        return jsonify({"projections": pp_mod.get_league_projections(league)})
    return jsonify(pp_mod.get_all_projections())

@app.route("/api/prizepicks/parlays", methods=["POST"])
def get_pp_parlays():
    data = request.json or {}
    leagues = data.get("leagues", ["NFL","NBA","MLB","NHL"])
    legs    = data.get("legs", 3)
    count   = data.get("count", 3)
    parlays = pp_mod.suggest_parlays(leagues=leagues, count=count, legs=legs)
    return jsonify({"parlays": parlays, "message": pp_mod.format_parlay_suggestions(parlays)})

@app.route("/api/prizepicks/summary", methods=["GET"])
def pp_summary():
    league = request.args.get("league")
    return jsonify({"summary": pp_mod.format_projections_summary(league)})


# ── Network routes ────────────────────────────────────────────────────────────
@app.route("/api/network/status", methods=["GET"])
def network_status():
    return jsonify(net_mod.get_network_summary())

@app.route("/api/network/speed", methods=["POST"])
def run_speed_test():
    result = net_mod.test_speed()
    msg = ""
    if result.get("download_mbps"):
        msg = f"Download: {result['download_mbps']} Mbps, Ping: {result['ping_ms']}ms"
    else:
        msg = f"Speed test failed: {result.get('error','Unknown error')}"
    return jsonify({"success": True, "message": msg, **result})

@app.route("/api/network/trust", methods=["POST"])
def trust_device():
    mac = (request.json or {}).get("mac","")
    if mac:
        net_mod.trust_device(mac)
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "No MAC provided"})

# ── Routines routes ───────────────────────────────────────────────────────────
@app.route("/api/routines", methods=["GET"])
def get_routines():
    return jsonify({"routines": routines_mod.list_routines()})

@app.route("/api/routines/<int:rid>", methods=["GET"])
def get_routine_route(rid):
    routine = routines_mod.get_routine_by_id(rid)
    if not routine:
        return jsonify({"success": False, "message": "Not found"}), 404
    return jsonify({"success": True, "routine": routine})

@app.route("/api/routines/<int:rid>", methods=["PUT"])
def update_routine_route(rid):
    data = request.json or {}
    routines_mod.update_routine_by_id(
        rid,
        name=data.get("name"),
        steps=data.get("steps"),
        description=data.get("description"),
    )
    return jsonify({"success": True})

@app.route("/api/routines", methods=["POST"])
def create_routine():
    data = request.json or {}
    rid = routines_mod.add_routine(
        data.get("name",""),
        data.get("steps",[]),
        data.get("description","")
    )
    return jsonify({"success": True, "id": rid})

@app.route("/api/routines/<int:rid>/run", methods=["POST"])
def run_routine_route(rid):
    return jsonify(routines_mod.run_routine_by_id(rid))

@app.route("/api/routines/<int:rid>", methods=["DELETE"])
def delete_routine(rid):
    routines_mod.delete_routine_by_id(rid)
    return jsonify({"success": True})


# ── System command route ──────────────────────────────────────────────────────
@app.route("/api/system/command", methods=["POST"])
def system_command():
    cmd = (request.json or {}).get("command","")
    return jsonify(execute_action({"type": "system_command", "command": cmd}))


# ── Face Auth routes ──────────────────────────────────────────────────────────
@app.route("/api/face/status", methods=["GET"])
def face_status():
    return jsonify({
        "available": face_mod.is_available(),
        "enrolled":  face_mod.is_enrolled(),
        "config":    face_mod.load_config(),
    })

@app.route("/api/face/enroll", methods=["POST"])
def face_enroll():
    result = face_mod.enroll_face(frames=25)
    return jsonify(result)

@app.route("/api/face/verify", methods=["POST"])
def face_verify():
    frame_b64 = (request.json or {}).get("frame", "")
    return jsonify(face_mod.verify_face_from_frame(frame_b64))

@app.route("/api/face/delete", methods=["POST"])
def face_delete():
    face_mod.delete_enrollment()
    return jsonify({"success": True})

@app.route("/api/pin/set", methods=["POST"])
def pin_set():
    data = request.json or {}
    pin  = str(data.get("pin", "")).strip()
    if not pin or len(pin) < 4:
        return jsonify({"success": False, "message": "PIN must be at least 4 digits."})
    result = face_mod.set_pin(pin)
    return jsonify(result)

@app.route("/api/pin/verify", methods=["POST"])
def pin_verify():
    data = request.json or {}
    pin  = str(data.get("pin", "")).strip()
    if not pin:
        return jsonify({"verified": False, "message": "No PIN entered."})
    ok = face_mod.verify_pin(pin)
    return jsonify({"verified": ok, "message": "Access granted." if ok else "Incorrect PIN. Try again."})


# ── Scheduler routes ──────────────────────────────────────────────────────────

@app.route("/api/scheduler/tasks", methods=["GET"])
def get_tasks():
    return jsonify({"tasks": task_scheduler.list_tasks()})


@app.route("/api/scheduler/tasks", methods=["POST"])
def create_task():
    data = request.json or {}
    try:
        schedule = data.get("schedule", {"type": "daily", "time": "08:00"})
        task_id = task_scheduler.add_task(
            name      = data.get("name", "Task"),
            task_type = data.get("task_type", "speak"),
            task_data = data.get("task_data", {}),
            schedule  = schedule,
        )
        return jsonify({"success": True, "id": task_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/scheduler/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    task_scheduler.remove_task(task_id)
    return jsonify({"success": True})


@app.route("/api/scheduler/tasks/<int:task_id>/toggle", methods=["POST"])
def toggle_task(task_id):
    enabled = (request.json or {}).get("enabled", True)
    task_scheduler.toggle_task(task_id, enabled)
    return jsonify({"success": True})


@app.route("/api/scheduler/parse", methods=["POST"])
def parse_schedule():
    text = (request.json or {}).get("text", "")
    schedule = task_scheduler.parse_schedule_from_text(text)
    return jsonify({"schedule": schedule, "human": task_scheduler._human_schedule(schedule)})


# ── Email / Calendar routes ───────────────────────────────────────────────────

@app.route("/api/email/status", methods=["GET"])
def email_status():
    return jsonify({"available": outlook.is_available()})


@app.route("/api/email/unread", methods=["GET"])
def get_unread():
    return jsonify({"emails": outlook.get_unread_emails(10)})


@app.route("/api/email/recent", methods=["GET"])
def get_recent():
    return jsonify({"emails": outlook.get_recent_emails(10)})


@app.route("/api/email/summary", methods=["GET"])
def email_summary():
    return jsonify({"summary": outlook.get_email_summary()})


@app.route("/api/email/search", methods=["POST"])
def search_email():
    query = (request.json or {}).get("query", "")
    return jsonify({"emails": outlook.search_emails(query)})


@app.route("/api/email/send", methods=["POST"])
def send_email_route():
    data = request.json or {}
    result = outlook.send_email(
        data.get("to",""),
        data.get("subject",""),
        data.get("body","")
    )
    return jsonify(result)


@app.route("/api/calendar/today", methods=["GET"])
def calendar_today():
    return jsonify({"events": outlook.get_todays_events(), "summary": outlook.get_calendar_summary()})


@app.route("/api/calendar/upcoming", methods=["GET"])
def calendar_upcoming():
    days = int(request.args.get("days", 7))
    return jsonify({"events": outlook.get_upcoming_events(days)})


@app.route("/api/calendar/create", methods=["POST"])
def calendar_create():
    data = request.json or {}
    result = outlook.create_event(
        subject  = data.get("subject",""),
        start    = data.get("start",""),
        end      = data.get("end"),
        location = data.get("location",""),
        body     = data.get("body",""),
    )
    return jsonify(result)


@app.route("/")
def index():
    return send_from_directory("static","index.html")


# ── Background services ───────────────────────────────────────────────────────
def execute_action_direct(action: dict) -> dict:
    """Direct action executor for scheduler and routines (bypasses HTTP)."""
    return execute_action(action)

# Health + briefing monitor
briefing_mod.set_alert_callback(_handle_alert)
briefing_mod.start_monitor()

# Task scheduler
task_scheduler.set_callbacks(execute_action_direct, _handle_alert)
task_scheduler.start_scheduler()

# Routines engine
routines_mod.set_callbacks(execute_action_direct, _handle_alert)

# Network monitor
net_mod.set_alert_callback(_handle_alert)
net_mod.start_monitor()

# Clipboard monitor
def _on_clipboard(content: str, ctype: str):
    if ctype in ("url", "code"):
        _handle_alert(
            f"CLIPBOARD — {ctype.upper()}",
            f"I noticed you copied a {ctype}, Boss. Say 'Friday, explain my clipboard' to act on it.",
            speak=False
        )

screen_mod.start_clipboard_monitor(_on_clipboard)



if __name__ == "__main__":
    print("\n" + "="*52)
    print("  F.R.I.D.A.Y.  —  SYSTEM ONLINE")
    print("="*52)
    print(f"  Model  : {config.OLLAMA_MODEL}")
    print(f"  Port   : {config.PORT}")
    print(f"  Spotify: {config.SPOTIFY_USERNAME}")
    print(f"  Outlook: {'Connected' if outlook.is_available() else 'Not installed'}")
    print("="*52 + "\n")
    app.run(debug=False, port=config.PORT, host="127.0.0.1")
