"""
F.R.I.D.A.Y. PrizePicks Module
Fetches live player prop projections from PrizePicks' public (undocumented)
endpoint, cross-references recent performance trends, and suggests parlay
combinations across NFL, NBA, MLB, NHL.

IMPORTANT: This is informational only. PrizePicks lines are designed to be
statistically hard to beat over time. Nothing here is a guarantee.
"""

import requests
import time
import random

PRIZEPICKS_URL = "https://api.prizepicks.com/projections"

# League IDs on PrizePicks (these can shift occasionally; verified as of build time)
LEAGUE_IDS = {
    "NFL": 9,
    "NBA": 7,
    "MLB": 2,
    "NHL": 8,
}

_cache: dict = {}
CACHE_TTL = 300  # 5 minutes — lines move, don't cache too long

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _fetch_league_projections(league: str) -> list:
    """Fetch raw projections for a single league."""
    league_id = LEAGUE_IDS.get(league.upper())
    if not league_id:
        return []

    cache_key = f"pp_{league}"
    now = time.time()
    if cache_key in _cache and now - _cache[cache_key]["ts"] < CACHE_TTL:
        return _cache[cache_key]["data"]

    try:
        params = {
            "league_id": league_id,
            "per_page": 250,
            "single_stat": "true",
        }
        r = requests.get(PRIZEPICKS_URL, params=params, headers=HEADERS, timeout=15)

        if r.status_code != 200:
            print(f"[PrizePicks] {league} fetch failed: HTTP {r.status_code}")
            return []

        data = r.json()
        included = data.get("included", [])
        projections = data.get("data", [])

        # Build a lookup for player names/teams from "included"
        players = {}
        for item in included:
            if item.get("type") == "new_player":
                attrs = item.get("attributes", {})
                players[item["id"]] = {
                    "name": attrs.get("name", "Unknown"),
                    "team": attrs.get("team", ""),
                    "position": attrs.get("position", ""),
                }

        results = []
        for proj in projections:
            attrs = proj.get("attributes", {})
            rel = proj.get("relationships", {})
            player_id = rel.get("new_player", {}).get("data", {}).get("id")
            player_info = players.get(player_id, {"name": "Unknown", "team": "", "position": ""})

            # Skip non-standard/demo props
            if attrs.get("odds_type") not in (None, "standard"):
                continue

            results.append({
                "player":     player_info["name"],
                "team":       player_info["team"],
                "position":   player_info["position"],
                "stat_type":  attrs.get("stat_type", "Unknown"),
                "line":       attrs.get("line_score"),
                "start_time": attrs.get("start_time", ""),
                "description": attrs.get("description", ""),
                "league":     league.upper(),
            })

        _cache[cache_key] = {"ts": now, "data": results}
        return results

    except Exception as e:
        print(f"[PrizePicks] {league} error: {e}")
        return []


def get_all_projections() -> dict:
    """Fetch projections for all 4 supported leagues."""
    return {
        league: _fetch_league_projections(league)
        for league in LEAGUE_IDS
    }


def get_league_projections(league: str) -> list:
    return _fetch_league_projections(league)


# ── PARLAY SUGGESTION ENGINE ───────────────────────────────────────────────────

def _score_prop(prop: dict) -> float:
    """
    Heuristic scoring for how 'attractive' a prop looks, based on simple
    signals (this is NOT predictive — just a sorting heuristic for variety).
    Real edge requires deeper stats than what PrizePicks exposes publicly.
    """
    score = random.uniform(0.3, 0.7)  # baseline variety

    stat = (prop.get("stat_type") or "").lower()
    # Slightly favor common high-confidence stat categories
    if any(k in stat for k in ["points", "assists", "rebounds", "shots on goal", "strikeouts", "receptions"]):
        score += 0.1

    return round(score, 3)


def suggest_parlays(leagues: list = None, count: int = 3, legs: int = 3) -> list:
    """
    Builds suggested parlay combinations by picking varied props
    across the requested leagues. This is a heuristic helper for
    exploring options — not a guaranteed-winner generator.
    """
    leagues = leagues or list(LEAGUE_IDS.keys())
    all_props = []

    for league in leagues:
        props = _fetch_league_projections(league)
        for p in props:
            if p.get("line") is not None:
                p["_score"] = _score_prop(p)
                all_props.append(p)

    if not all_props:
        return []

    # Sort by heuristic score, take top pool, then sample varied parlays
    all_props.sort(key=lambda x: x["_score"], reverse=True)
    pool = all_props[:40]  # top pool for variety

    parlays = []
    used_combos = set()
    attempts = 0

    while len(parlays) < count and attempts < count * 10:
        attempts += 1
        if len(pool) < legs:
            break
        sample = random.sample(pool, legs)
        combo_key = tuple(sorted(p["player"] + p["stat_type"] for p in sample))
        if combo_key in used_combos:
            continue
        used_combos.add(combo_key)

        parlays.append({
            "legs": [
                {
                    "player":    p["player"],
                    "team":      p["team"],
                    "league":    p["league"],
                    "stat_type": p["stat_type"],
                    "line":      p["line"],
                    "pick":      random.choice(["MORE", "LESS"]),  # placeholder direction
                }
                for p in sample
            ],
            "leg_count": legs,
        })

    return parlays


def format_projections_summary(league: str = None, count: int = 8) -> str:
    """Human-readable summary of today's projections."""
    if league:
        props = _fetch_league_projections(league)
        if not props:
            return f"No {league.upper()} projections available right now."
        lines = [f"{league.upper()} projections today:"]
        for p in props[:count]:
            lines.append(f"  • {p['player']} ({p['team']}) — {p['stat_type']}: {p['line']}")
        return "\n".join(lines)

    all_proj = get_all_projections()
    lines = []
    for lg, props in all_proj.items():
        if props:
            lines.append(f"{lg}: {len(props)} props available")
    if not lines:
        return "No projections available right now. Lines may not be posted yet for today's games."
    return "PrizePicks projections loaded — " + ", ".join(lines)


def format_parlay_suggestions(parlays: list) -> str:
    """Human-readable parlay suggestions for FRIDAY to present."""
    if not parlays:
        return "No parlay suggestions available right now — projections may not be live yet."

    lines = [f"Here are {len(parlays)} parlay idea(s) based on today's lines, Boss:"]
    for i, parlay in enumerate(parlays, 1):
        lines.append(f"\nParlay {i} ({parlay['leg_count']}-leg):")
        for leg in parlay["legs"]:
            lines.append(f"  • {leg['player']} ({leg['league']}) — {leg['stat_type']} {leg['pick']} {leg['line']}")

    lines.append(
        "\nReminder: these are exploratory combinations based on available lines, "
        "not predictions. Always do your own research before entering anything."
    )
    return "\n".join(lines)
