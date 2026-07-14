@echo off
title FRIDAY — Reset Spotify Auth
echo.
echo  Deleting Spotify token cache to force re-authorisation...
echo  (This fixes permission/scope issues)
echo.
if exist .spotify_cache (
    del .spotify_cache
    echo  Cache deleted.
) else (
    echo  No cache found — already clean.
)
echo.
echo  Now run START_FRIDAY.bat
echo  Spotify will ask you to log in once more, then it will work.
echo.
pause
