import os
import sys
import datetime
import requests
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Missing SUPABASE credentials.")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 1. Fetch MLB Schedule & Probables from MLB Stats API
today_str = datetime.datetime.now().strftime("%Y-%m-%d")
schedule_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={today_str}&hydrate=probablePitcher"
data = requests.get(schedule_url, timeout=15).json()
dates = data.get("dates", [])
games = dates[0].get("games", []) if dates else []

def get_pitcher_k9(player_id):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=pitching"
    try:
        r = requests.get(url, timeout=10).json()
        splits = r.get("stats", [{}])[0].get("splits", [])
        if splits:
            stat = splits[0].get("stat", {})
            k9 = float(stat.get("strikeoutsPer9Inn", 8.5))
            innings = float(stat.get("inningsPitched", 0))
            starts = int(stat.get("gamesStarted", 1)) or 1
            avg_ip = innings / starts if starts > 0 else 5.5
            return k9, avg_ip
    except Exception:
        pass
    return 8.5, 5.5

# 2. Fetch Live Player Props from The Odds API (Pinnacle, DraftKings, FanDuel)
book_props = {}
if ODDS_API_KEY:
    events_url = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey={ODDS_API_KEY}"
    ev_resp = requests.get(events_url, timeout=10)
    if ev_resp.status_code == 200:
        events = ev_resp.json()
        # Query pitcher_strikeouts for upcoming events
        for ev in events[:5]:  # Process closest upcoming slate
            event_id = ev["id"]
            props_url = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds"
            p_resp = requests.get(props_url, params={
                "apiKey": ODDS_API_KEY,
                "regions": "us,eu",
                "markets": "pitcher_strikeouts",
                "oddsFormat": "american"
            }, timeout=10)
            if p_resp.status_code == 200:
                p_data = p_resp.json()
                for bm in p_data.get("bookmakers", []):
                    b_key = bm.get("key") # 'pinnacle', 'draftkings', 'fanduel'
                    for mkt in bm.get("markets", []):
                        if mkt.get("key") == "pitcher_strikeouts":
                            for outcome in mkt.get("outcomes", []):
                                if outcome.get("name") == "Over":
                                    p_name = outcome.get("description")
                                    if p_name not in book_props:
                                        book_props[p_name] = {}
                                    book_props[p_name][b_key] = {
                                        "line": outcome.get("point"),
                                        "odds": str(outcome.get("price"))
                                    }

records = []

for game in games:
    teams = game.get("teams", {})
    matchup = f"{teams.get('away',{}).get('team',{}).get('name')} @ {teams.get('home',{}).get('team',{}).get('name')}"

    for side in ["away", "home"]:
        p_info = teams.get(side, {}).get("probablePitcher")
        if not p_info:
            continue

        p_id = p_info.get("id")
        p_name = p_info.get("fullName")

        k9, avg_ip = get_pitcher_k9(p_id)
        projected_k = round((k9 / 9.0) * avg_ip, 2)

        # Extract specific sportsbook data
        props = book_props.get(p_name, {})
        pinny = props.get("pinnacle", {})
        dk = props.get("draftkings", {})
        fd = props.get("fanduel", {})

        # Use consensus line (Pinnacle preferred, then DK, then FD, then fallback)
        active_line = pinny.get("line") or dk.get("line") or fd.get("line") or 5.5
        active_odds = pinny.get("odds") or dk.get("odds") or fd.get("odds") or "-115"
        best_book = "Pinnacle" if "pinnacle" in props else ("DraftKings" if "draftkings" in props else "Consensus")

        edge = round((projected_k - float(active_line)) / float(active_line), 3)

        records.append({
            "player_name": p_name,
            "matchup": matchup,
            "prop_type": "Strikeouts",
            "line": float(active_line),
            "odds": active_odds,
            "projected": projected_k,
            "edge": edge,
            "pinnacle_line": pinny.get("line"),
            "pinnacle_odds": pinny.get("odds"),
            "dk_line": dk.get("line"),
            "dk_odds": dk.get("odds"),
            "fd_line": fd.get("line"),
            "fd_odds": fd.get("odds"),
            "bookmaker": best_book,
            "status": "APPROVED"
        })

if records:
    records = sorted(records, key=lambda x: x["edge"], reverse=True)
    supabase.table("predictions").delete().neq("id", 0).execute()
    supabase.table("predictions").insert(records).execute()
    print(f"Loaded {len(records)} pitcher edges with multi-book comparison.")
else:
    print("No pitchers found to update.")
