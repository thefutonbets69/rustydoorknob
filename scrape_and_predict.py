import os
import sys
import datetime
import requests
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Missing SUPABASE_URL or SUPABASE_KEY environment variables.")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 1. Fetch today's schedule from official MLB Stats API (Free, No Auth)
today_str = datetime.datetime.now().strftime("%Y-%m-%d")
schedule_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={today_str}&hydrate=probablePitcher,linescore"
print(f"Fetching games for {today_str}...")

resp = requests.get(schedule_url, timeout=15)
if resp.status_code != 200:
    print(f"Failed to fetch MLB schedule: {resp.status_code}")
    sys.exit(1)

data = resp.json()
dates = data.get("dates", [])
if not dates:
    print("No MLB games scheduled for today.")
    sys.exit(0)

games = dates[0].get("games", [])
print(f"Found {len(games)} scheduled games.")

def get_pitcher_k9(player_id):
    """Pulls current season K/9 and IP from MLB stats"""
    stats_url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=pitching"
    try:
        r = requests.get(stats_url, timeout=10).json()
        splits = r.get("stats", [{}])[0].get("splits", [])
        if splits:
            stat = splits[0].get("stat", {})
            k9 = float(stat.get("strikeoutsPer9Inn", 8.5))
            innings = float(stat.get("inningsPitched", 0))
            games_started = int(stat.get("gamesStarted", 1)) or 1
            avg_ip = innings / games_started if games_started > 0 else 5.5
            return k9, avg_ip
    except Exception:
        pass
    return 8.5, 5.5  # MLB baseline fallback

records = []

for game in games:
    teams = game.get("teams", {})
    away_team = teams.get("away", {}).get("team", {}).get("name", "Away")
    home_team = teams.get("home", {}).get("team", {}).get("name", "Home")
    matchup = f"{away_team} @ {home_team}"

    for side in ["away", "home"]:
        pitcher_info = teams.get(side, {}).get("probablePitcher")
        if not pitcher_info:
            continue

        player_id = pitcher_info.get("id")
        player_name = pitcher_info.get("fullName")

        # Get actual performance metrics
        k9, avg_ip = get_pitcher_k9(player_id)
        
        # Expected strikeouts: (K/9 / 9) * Average Innings Pitched
        projected_k = round((k9 / 9.0) * avg_ip, 2)
        baseline_line = 5.5  # Standard median market benchmark
        
        # Edge calculation against market standard
        edge = round((projected_k - baseline_line) / baseline_line, 3)

        records.append({
            "player_name": player_name,
            "matchup": matchup,
            "prop_type": "Strikeouts",
            "line": baseline_line,
            "odds": "-115",
            "projected": projected_k,
            "edge": edge,
            "status": "APPROVED"
        })

if not records:
    print("No probable pitchers announced yet for today's slate.")
    sys.exit(0)

# Sort highest edge first
records = sorted(records, key=lambda x: x["edge"], reverse=True)

# 2. Push real records into Supabase
print(f"Pushing {len(records)} pitcher projections to Supabase...")
supabase.table("predictions").delete().neq("id", 0).execute()
res = supabase.table("predictions").insert(records).execute()
print(f"Success! Inserted {len(res.data)} live pitcher records.")
