import requests
import json
import os
import streamlit as st
from typing import Optional, List, Dict, Any

BASE_URL = "https://api.sleeper.app/v1"
AVATAR_CDN_URL = "https://sleepercdn.com/avatars"
UPLOADS_CDN_URL = "https://sleepercdn.com/uploads"

# Replaced (avatar_id: str | None) with Optional[str]
def get_avatar_url(avatar_id: Optional[str] = None, thumbnail: bool = True) -> str:
    """
    Constructs the Sleeper CDN avatar URL. Handles custom uploads,
    standard avatars, and full image URLs seamlessly.
    """
    if not avatar_id:
        return "https://sleepercdn.com/images/v2/placeholder_avatar.png"

    if str(avatar_id).startswith("http"):
        return avatar_id

    if "uploads/" in str(avatar_id):
        return f"https://sleepercdn.com/{avatar_id}"

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
def get_nfl_players() -> dict:
    """
    Reads local players.json snapshot file to skip external Sleeper API requests.
    Caches result for 24 hours.
    """
    file_path = "players.json"
    
    if not os.path.exists(file_path):
        st.error(f"⚠️ '{file_path}' not found in root directory. Please upload your snapshot file.")
        return {}

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)
    
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

def get_roster_players(league_id: str, roster_id: int) -> List[Dict[str, Any]]:
    """
    Fetches active roster players for a specific roster_id in a Sleeper league.
    Returns a list of dicts with player details (id, name, pos, team, years_exp).
    """
    # 1. Fetch all league rosters
    rosters_url = f"{BASE_URL}/league/{league_id}/rosters"
    rosters_res = requests.get(rosters_url)
    if rosters_res.status_code != 200:
        return []

    rosters = rosters_res.json()
    target_roster = next((r for r in rosters if r.get("roster_id") == roster_id), None)
    
    if not target_roster or not target_roster.get("players"):
        return []

    # 2. Fetch master player dictionary
    all_players = get_all_nfl_players()

    # 3. Format active roster players
    roster_player_ids = target_roster.get("players", [])
    starter_ids = set(target_roster.get("starters", []))

    player_list = []
    for p_id in roster_player_ids:
        player_info = all_players.get(str(p_id), {})
        
        full_name = player_info.get("full_name") or f"{player_info.get('first_name', '')} {player_info.get('last_name', '')}".strip() or f"Player {p_id}"
        
        player_list.append({
            "id": str(p_id),
            "name": full_name,
            "pos": player_info.get("position", "N/A"),
            "team": player_info.get("team") or "FA",
            "years_exp": player_info.get("years_exp", 0),
            "is_starter": str(p_id) in starter_ids
        })

    return player_list