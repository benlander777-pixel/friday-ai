#!/usr/bin/env bash
cd "$(dirname "$0")"

echo
echo "Deleting Spotify token cache to force re-authorisation..."
echo "(This fixes permission/scope issues)"
echo

if [ -f ".spotify_cache" ]; then
    rm .spotify_cache
    echo "Cache deleted."
else
    echo "No cache found -- already clean."
fi

echo
echo "Now run ./start_friday.sh"
echo "Spotify will ask you to log in once more, then it will work."
echo
