@echo off
title F.R.I.D.A.Y. INSTALLER
color 0A
echo.
echo  ============================================================
echo    F.R.I.D.A.Y.  --  INSTALLATION
echo  ============================================================
echo.

echo  [1/6] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (echo  ERROR: Python not found. Install from https://python.org & pause & exit /b 1)
echo       OK

echo  [2/6] Installing Python packages...
pip install flask flask-cors requests psutil spotipy pywin32 pillow opencv-python face-recognition --quiet
echo       OK

echo  [3/6] Checking Node.js...
node --version >nul 2>&1
if errorlevel 1 (echo  ERROR: Node.js not found. Install from https://nodejs.org & pause & exit /b 1)
echo       OK

echo  [4/6] Installing Electron...
npm install --save-dev electron electron-builder --silent
echo       OK

echo  [5/6] Downloading Piper voice model (one-time, ~50MB)...
if not exist "piper" mkdir piper
if not exist "piper\piper.exe" (
    echo     Downloading Piper...
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip' -OutFile 'piper\piper.zip'"
    powershell -Command "Expand-Archive -Path 'piper\piper.zip' -DestinationPath 'piper' -Force"
    del piper\piper.zip
    echo     Downloading voice model...
    powershell -Command "Invoke-WebRequest -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx' -OutFile 'piper\en_US-lessac-medium.onnx'"
    powershell -Command "Invoke-WebRequest -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json' -OutFile 'piper\en_US-lessac-medium.onnx.json'"
) else (echo     Piper already installed.)
echo       OK

echo  [6/6] Checking Ollama...
ollama --version >nul 2>&1
if errorlevel 1 (
    echo  NOTE: Ollama not found. Download from https://ollama.ai
    echo        Then run:  ollama pull llama3
    echo        And for screen awareness: ollama pull llava
) else (
    echo       OK
)

echo.
echo  ============================================================
echo    INSTALLATION COMPLETE
echo.
echo.
echo    Run START_FRIDAY.bat to launch
echo  ============================================================
echo.
pause
