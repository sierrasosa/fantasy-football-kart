import requests
import streamlit as st

# Base URLs for Sleeper API and CDN
BASE_URL = "https://api.sleeper.app/v1"
AVATAR_CDN_URL = "https://sleepercdn.com/avatars"
UPLOADS_CDN_URL = "https://sleepercdn.com/uploads"

def get_avatar_url(avatar_id: str | None, thumbnail: bool = True) -> str:
    """
    Constructs the Sleeper CDN avatar URL. Handles custom uploads, 
    standard avatars, and full image URLs seamlessly.
    """
    if not avatar_id:
        return "https://sleepercdn.com/images/v2/placeholder_avatar.png"
    
    # If it's already a full HTTP URL (e.g. metadata.avatar)
    if str(avatar_id).startswith("http"):
        return avatar_id
    
    # If avatar_id is a custom upload hash or path
    if "uploads/" in str(avatar_id):
        return f"https://sleepercdn.com/{avatar_id}"

    # Standard Sleeper account avatar ID
    if thumbnail:
        return f"{AVATAR_CDN_URL}/thumbs/{avatar_id}"
    return f"{AVATAR_CDN_URL}/{avatar_id}"

def get_league_users(league_id: str) -> list[dict]:
    """Fetches all users/managers in a league."""
    url = f"{BASE_URL}/league/{league_id}/users"
    response = requests.get(url)
    return response.json() if response.status_code == 200 else []

def get_league_users_avatar_map(league_id: str, thumbnail: bool = True) -> dict[str, dict]:
    """
    Maps user_id -> {'display_name': str, 'avatar_url': str}
    Checks for custom team avatar in metadata FIRST, then user avatar.
    """
    users = get_league_users(league_id)
    avatar_map = {}
    
    for user in users:
        u_id = user.get("user_id")
        metadata = user.get("metadata") or {}
        
        # 1. Prioritize metadata avatar (custom league/team avatar)
        # 2. Fall back to user level avatar ID
        avatar_val = metadata.get("avatar") or user.get("avatar")
        
        display_name = (
            metadata.get("team_name") 
            or user.get("display_name") 
            or user.get("username", "Unknown User")
        )

        avatar_map[u_id] = {
            "display_name": display_name,
            "avatar_url": get_avatar_url(avatar_val, thumbnail=thumbnail)
        }
        
    return avatar_map

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
    url = f"{BASE_URL}/league/{league_id}/matchups/{week}"
    response = requests.get(url)
    return response.json() if response.status_code == 200 else []

def get_league_rosters(league_id: str):
    """Fetches all rosters in the league to map roster_id to owner_id."""
    url = f"{BASE_URL}/league/{league_id}/rosters"
    response = requests.get(url)
    return response.json() if response.status_code == 200 else []