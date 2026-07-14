# F.R.I.D.A.Y.  —  Desktop App
### Female Replacement Intelligent Digital Assistant Youth

---

## Prerequisites

| Tool | Download |
|---|---|
| Python 3.10+ | https://python.org |
| Node.js 18+ | https://nodejs.org |
| Ollama | https://ollama.ai |

---

## First-Time Setup

### 1. Spotify — Add Redirect URI
1. Go to https://developer.spotify.com/dashboard
2. Click your app → **Settings**
3. Under **Redirect URIs**, add: `http://127.0.0.1:8888/callback`
4. Click **Save**

### 2. Run the installer
Double-click **INSTALL.bat**

### 3. Pull an Ollama model (first time only)
```
ollama pull llama3
```

### 4. Start Ollama
```
ollama serve
```

### 5. Launch FRIDAY
Double-click **START_FRIDAY.bat**

On first launch, a browser window will open asking you to authorise Spotify.
Log in and click Allow — this only happens once. A `.spotify_cache` file is saved locally.

---

## Voice Commands

| Say... | What happens |
|---|---|
| **"Friday"** | Wakes FRIDAY up (she says "Yes, Boss?") |
| **"Sleep Friday"** | Puts her back to quiet mode |
| Anything after waking | Sent as a command |

Voice works immediately on launch. The pill in the header shows the state:
- 🔴 LISTENING — waiting for wake word
- 🟡 AWAKE — actively processing your voice

---

## What FRIDAY Can Do

| Say... | Result |
|---|---|
| "Play some jazz" | Searches and plays on Spotify |
| "Pause / resume / next / previous" | Controls Spotify playback |
| "Clean my desktop" | Sorts files into FRIDAY_Sorted/, deletes junk |
| "Open Chrome / Spotify / VSCode" | Launches the app |
| "Set volume to 70" | Sets Windows system volume |
| "What's my CPU usage?" | Reads from the metrics panel |

---

## File Structure

```
friday-app/
├── main.js           Electron app shell
├── preload.js        Secure IPC bridge
├── server.py         Flask + Ollama + Spotify backend
├── config.py         All settings (model, credentials, etc.)
├── package.json      Node/Electron config
├── static/
│   └── index.html    The Iron Man HUD
├── INSTALL.bat       One-time setup
├── START_FRIDAY.bat  Daily launcher
└── README.md
```

---

## Changing the AI Model

Open `config.py` and change:
```python
OLLAMA_MODEL = "llama3"
```
To any model you have: `mistral`, `phi3`, `llama3.2`, `gemma2`, etc.

---

## Desktop Cleaner

Files are **never deleted** (except true junk: `.tmp`, `.log`, `Thumbs.db`, etc.).
All your files are moved to `Desktop\FRIDAY_Sorted\` organised by type:
`Images / Documents / Videos / Music / Archives / Code / Installers / Other`

Shortcuts (`.lnk`) are always left on your desktop untouched.

---

*Built with Electron + Flask + Ollama + Spotipy*
