"""
F.R.I.D.A.Y. Screen Awareness Module
- Take screenshots and analyse with llava vision model via Ollama
- Monitor clipboard for URLs, code, text to act on
- Annotate and save screenshots
"""

import os
import base64
import subprocess
import threading
import time
import requests
from datetime import datetime
from pathlib import Path

OLLAMA_VISION_URL = "http://localhost:11434/api/generate"
VISION_MODEL      = "llava"   # ollama pull llava
SCREENSHOT_DIR    = os.path.join(os.path.expanduser("~"), "Desktop", "FRIDAY_Screenshots")

_clipboard_prev   = ""
_clipboard_cb     = None   # callback(content, type)
_clip_running     = False


# ── SCREENSHOT ────────────────────────────────────────────────────────────────

def take_screenshot(save: bool = True) -> tuple[str, str | None]:
    """
    Takes a screenshot using PowerShell.
    Returns (base64_png, saved_path | None)
    """
    try:
        # Use PowerShell to capture screen to temp file
        tmp = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "friday_screen.png")
        script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
$bmp.Save('{tmp}')
$g.Dispose()
$bmp.Dispose()
"""
        subprocess.run(["powershell", "-Command", script], capture_output=True, timeout=10)

        if not os.path.exists(tmp):
            return "", None

        with open(tmp, "rb") as f:
            data = f.read()

        b64 = base64.b64encode(data).decode("utf-8")

        saved_path = None
        if save:
            os.makedirs(SCREENSHOT_DIR, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            saved_path = os.path.join(SCREENSHOT_DIR, f"screenshot_{ts}.png")
            with open(saved_path, "wb") as f:
                f.write(data)

        return b64, saved_path

    except Exception as e:
        print(f"[Screen] Screenshot error: {e}")
        return "", None


def analyse_screen(prompt: str = "What is on the screen? Describe what you see.") -> str:
    """
    Takes a screenshot and sends it to llava for vision analysis.
    Returns FRIDAY's description.
    """
    b64, _ = take_screenshot(save=False)
    if not b64:
        return "I couldn't capture the screen, Boss."

    try:
        response = requests.post(OLLAMA_VISION_URL, json={
            "model":  VISION_MODEL,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 300},
        }, timeout=60)

        if response.status_code == 200:
            return response.json().get("response", "").strip()
        else:
            return f"Vision model error: {response.status_code}. Make sure you've run: ollama pull llava"

    except requests.exceptions.ConnectionError:
        return "Ollama is offline. Start it with: ollama serve"
    except Exception as e:
        return f"Vision error: {e}"


def screenshot_and_save() -> dict:
    """Take a screenshot, save it, return info."""
    b64, path = take_screenshot(save=True)
    if path:
        return {"success": True, "message": f"Screenshot saved to {path}", "path": path}
    return {"success": False, "message": "Could not take screenshot."}


# ── CLIPBOARD MONITOR ─────────────────────────────────────────────────────────

def _get_clipboard() -> str:
    """Read clipboard text via PowerShell."""
    try:
        result = subprocess.run(
            ["powershell", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _detect_clipboard_type(text: str) -> str:
    """Detect what kind of content is in the clipboard."""
    if text.startswith("http://") or text.startswith("https://"):
        return "url"
    if any(kw in text for kw in ["def ", "function ", "class ", "import ", "const ", "var ", "int ", "#include"]):
        return "code"
    return "text"


def _clipboard_loop():
    global _clipboard_prev, _clip_running
    while _clip_running:
        try:
            current = _get_clipboard()
            if current and current != _clipboard_prev and len(current) > 3:
                ctype = _detect_clipboard_type(current)
                _clipboard_prev = current
                if _clipboard_cb:
                    _clipboard_cb(current, ctype)
        except Exception as e:
            print(f"[Clipboard] Error: {e}")
        time.sleep(2)


def start_clipboard_monitor(callback):
    """Start monitoring clipboard. callback(content, type) fires on change."""
    global _clipboard_cb, _clip_running
    _clipboard_cb = callback
    _clip_running = True
    t = threading.Thread(target=_clipboard_loop, daemon=True)
    t.start()
    print("[Clipboard] Monitor started.")


def stop_clipboard_monitor():
    global _clip_running
    _clip_running = False


def summarise_clipboard_url(url: str) -> str:
    """Fetch a URL and ask FRIDAY to summarise it."""
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        # Extract text crudely (strip HTML tags)
        import re
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s+", " ", text).strip()[:3000]

        ollama_resp = requests.post("http://localhost:11434/api/generate", json={
            "model":  "llama3",
            "prompt": f"Summarise this web page content in 3-4 sentences:\n\n{text}",
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 200},
        }, timeout=30)

        if ollama_resp.status_code == 200:
            return ollama_resp.json().get("response", "").strip()
    except Exception as e:
        return f"Could not summarise URL: {e}"
    return "Could not summarise that page."


def explain_clipboard_code(code: str) -> str:
    """Ask FRIDAY to explain clipboard code."""
    try:
        ollama_resp = requests.post("http://localhost:11434/api/generate", json={
            "model":  "llama3",
            "prompt": f"Explain this code briefly and clearly:\n\n{code[:2000]}",
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 300},
        }, timeout=30)
        if ollama_resp.status_code == 200:
            return ollama_resp.json().get("response", "").strip()
    except Exception as e:
        return f"Could not explain code: {e}"
    return "Could not analyse that code."
