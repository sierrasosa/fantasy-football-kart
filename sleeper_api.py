import requests
import streamlit as st

# Sleeper recommends fetching players at most once per day due to payload size
@st.cache_data(ttl=86400)
def get_nfl_players():
    """Temporary mock data to skip external Sleeper API network requests during testing."""
    return {
        "4034": {"name": "Christian McCaffrey", "pos": "RB", "team": "SF"},
        "4881": {"name": "Lamar Jackson", "pos": "QB", "team": "BAL"},
        "6794": {"name": "Justin Jefferson", "pos": "WR", "team": "MIN"},
        "4984": {"name": "Josh Allen", "pos": "QB", "team": "BUF"},
        "5849": {"name": "A.J. Brown", "pos": "WR", "team": "PHI"}
    }
    print('Using temporary fake player data')
    # print("🔥 CACHE MISS: Downloading players from Sleeper API...")
    # """Fetches full NFL player database from Sleeper and filters to skill positions."""
    # url = "https://api.sleeper.app/v1/players/nfl"
    # response = requests.get(url)
    # if response.status_code == 200:
    #     data = response.json()
    #     # Filter down to essential fields for fantasy positions
    #     return {
    #         p_id: {
    #             "name": info.get("full_name", p_id),
    #             "pos": info.get("position"),
    #             "team": info.get("team")
    #         }
    #         for p_id, info in data.items()
    #         if info.get("position") in ["QB", "RB", "WR", "TE", "K", "DEF"]
    #     }
    return {}

def get_league_matchups(league_id: str, week: int):
    """Fetches matchup scores and roster starting lineups for a given week."""
    url = f"https://api.sleeper.app/v1/league/{league_id}/matchups/{week}"
    response = requests.get(url)
    return response.json() if response.status_code == 200 else []

def get_league_rosters(league_id: str):
    """Fetches all rosters in the league to map roster_id to owner_id."""
    url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    response = requests.get(url)
    return response.json() if response.status_code == 200 else []