#!/usr/bin/env bash
set -e

echo
echo "============================================================"
echo "  F.R.I.D.A.Y.  --  INSTALLATION (Linux)"
echo "============================================================"
echo

echo "[1/5] Checking Python..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "  ERROR: python3 not found. Install it with your package manager"
    echo "         (e.g. sudo pacman -S python python-pip)"
    exit 1
fi
echo "      OK ($(python3 --version))"

echo "[2/5] Installing Python packages..."
# Arch (and modern Debian/Ubuntu) mark the system Python as externally
# managed (PEP 668), so `pip install` refuses to touch it directly. Use a
# venv instead -- the correct fix, not something to override.
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet
echo "      OK (installed into .venv/)"

echo "[3/5] Checking .env configuration..."
if [ ! -f ".env" ]; then
    cp ".env.example" ".env"
    echo "      Created .env -- add your Spotify credentials before first launch."
    echo "      See: https://developer.spotify.com/dashboard"
else
    echo "      .env already exists."
fi

echo "[4/5] Checking Node.js..."
if ! command -v node >/dev/null 2>&1; then
    echo "  ERROR: Node.js not found. Install it with your package manager"
    echo "         (e.g. sudo pacman -S nodejs npm)"
    exit 1
fi
echo "      OK ($(node --version))"

echo "      Installing Electron..."
npm install --silent
echo "      OK"

echo "[5/5] Checking Ollama..."
if ! command -v ollama >/dev/null 2>&1; then
    echo "  NOTE: Ollama not found. Install from https://ollama.ai"
    echo "        Then run:  ollama pull llama3"
    echo "        And for screen awareness: ollama pull llava"
else
    echo "      OK"
fi

echo
echo "============================================================"
echo "  Optional but recommended desktop tools (install what's missing"
echo "  via your package manager -- e.g. pacman -S <name> on Arch):"
echo
echo "    Volume control : wireplumber (wpctl) or pipewire-pulse (pactl)"
echo "    Screenshots    : spectacle (KDE) or grim (Wayland) or scrot (X11)"
echo "    Clipboard      : wl-clipboard (Wayland) or xclip (X11)"
echo "    Network devices: iproute2 (ip command)"
echo "    Trash/Recycle  : glib2 (gio command)"
echo "============================================================"
echo
echo "  INSTALLATION COMPLETE"
echo "  Run ./start_friday.sh to launch"
echo "============================================================"
echo
