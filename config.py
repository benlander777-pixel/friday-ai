# ============================================================
#  F.R.I.D.A.Y. CONFIGURATION
# ============================================================

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Ollama model
OLLAMA_MODEL      = "llama3"
OLLAMA_URL        = "http://localhost:11434/api/generate"
OLLAMA_VISION_MODEL = "llava"   # ollama pull llava

# Spotify — set these in a local .env file (copy .env.example to .env).
# Never commit real credentials to git.
SPOTIFY_CLIENT_ID     = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_USERNAME      = os.environ.get("SPOTIFY_USERNAME", "")
SPOTIFY_REDIRECT_URI  = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
SPOTIFY_SCOPE         = (
    "user-modify-playback-state "
    "user-read-playback-state "
    "user-read-currently-playing "
    "user-read-private "
    "streaming "
    "app-remote-control "
    "playlist-read-private "
    "playlist-read-collaborative"
)


# Voice
WAKE_WORD  = "friday"       # say this to wake FRIDAY
SLEEP_WORD = "sleep friday" # say this to put her back to sleep

# Piper TTS (local AI voice)
# Download from: https://github.com/rhasspy/piper/releases
# Place piper.exe and a voice model in the piper/ folder next to server.py
PIPER_EXE   = "piper\\piper.exe"
PIPER_MODEL = "piper\\en_US-lessac-medium.onnx"
USE_PIPER   = True   # False = use browser TTS instead

# Server
PORT = 5000

# Desktop cleaner
DESKTOP_SORT_FOLDER = "FRIDAY_Sorted"

FILE_CATEGORIES = {
    "Images":     [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff", ".raw"],
    "Documents":  [".pdf", ".doc", ".docx", ".txt", ".xlsx", ".xls", ".pptx", ".ppt", ".csv", ".odt", ".rtf"],
    "Videos":     [".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm", ".m4v"],
    "Music":      [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"],
    "Archives":   [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
    "Code":       [".py", ".js", ".html", ".css", ".json", ".ts", ".cpp", ".c", ".java", ".cs", ".go", ".rs"],
    "Installers": [".exe", ".msi"],
}

JUNK_PATTERNS = [
    "*.tmp", "*.temp", "~$*", "*.log",
    "Thumbs.db", "desktop.ini", ".DS_Store",
    "*.bak", "*.old", "*.crdownload", "*.part",
]

# Mood tracking thresholds
STRESS_HISTORY_DAYS = 7   # days to keep stress history

# Network monitor
TRUSTED_PING_THRESHOLD = 200   # ms — alert above this
