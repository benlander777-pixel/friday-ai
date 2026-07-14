@echo off
title F.R.I.D.A.Y.
echo.
echo  Initializing F.R.I.D.A.Y...
echo.

:: Start Python server in background
start "FRIDAY-Server" /min python server.py

:: Wait 4 seconds for server to be ready
echo  Starting backend server...
timeout /t 4 /nobreak >nul

:: Launch Electron
echo  Launching FRIDAY interface...
npx electron . --disable-gpu

echo.
echo  FRIDAY closed.
