import requests
import json
import os
import streamlit as st
from pathlib import Path
from urllib.parse import quote
from typing import Optional, List, Dict, Any

BASE_URL = "https://api.sleeper.app/v1"
AVATAR_CDN_URL = "https://sleepercdn.com/avatars"
UPLOADS_CDN_URL = "https://sleepercdn.com/uploads"

# Replaced (avatar_id: str | None) with Optional[str]

def get_league_users(league_id: str) -> list[dict]:
    """Fetches all users/managers in a league."""
    url = f"{BASE_URL}/league/{league_id}/users"
    response = requests.get(url)
    return response.json() if response.status_code == 200 else []


@st.cache_data(ttl=86400)
def get_league_info(league_id: str) -> dict:
    """Fetch league metadata such as its season, cached for one day."""
    response = requests.get(f"{BASE_URL}/league/{league_id}", timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not data.get("season"):
        raise ValueError(f"Sleeper returned no season metadata for league {league_id}.")
    return data


def get_user(username: str) -> dict:
    """Fetch a Sleeper account by username."""
    response = requests.get(f"{BASE_URL}/user/{quote(username, safe='')}", timeout=20)
    return response.json() if response.status_code == 200 else {}


def get_user_nfl_leagues(user_id: str, season: str) -> list[dict]:
    """Fetch NFL leagues for a Sleeper user in a season."""
    url = f"{BASE_URL}/user/{user_id}/leagues/nfl/{season}"
    response = requests.get(url, timeout=20)
    data = response.json() if response.status_code == 200 else []
    return data if isinstance(data, list) else []


def is_league_commissioner(league_id: str, user_id: str) -> bool:
    """Check whether a Sleeper user is marked as league owner."""
    return any(
        str(user.get("user_id")) == str(user_id) and user.get("is_owner") is True
        for user in get_league_users(league_id)
    )

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
    file_path = Path(__file__).resolve().parent.parent / "data" / "pruned_players.json"
    
    if not os.path.exists(file_path):
        st.error(f"⚠️ '{file_path}' not found in root directory. Please upload your snapshot file.")
        return {}

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)
    return {}

def get_nfl_state() -> dict:
    """Fetches the current NFL state from Sleeper, including week and season metadata."""
    url = f"{BASE_URL}/state/nfl"
    response = requests.get(url)
    return response.json() if response.status_code == 200 else {}

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

def get_roster_players(
    league_id: str,
    roster_id: int,
    player_points: Optional[Dict[str, Any]] = None,
    matchup_data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
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

    if not target_roster and not matchup_data:
        return []

    roster_data = matchup_data or target_roster
    if not roster_data or not roster_data.get("players"):
        return []

    # 2. Fetch the local NFL player snapshot used elsewhere in the app
    all_players = get_nfl_players() or {}

    # 3. Format active roster players
    roster_player_ids = roster_data.get("players", [])
    starter_ids = set(roster_data.get("starters", []))
    player_points = (
        roster_data.get("players_points") or player_points or {}
    )

    player_list = []
    for p_id in roster_player_ids:
        player_info = all_players.get(str(p_id), {})

        full_name = (
            player_info.get("full_name")
            or f"{player_info.get('first_name', '')} {player_info.get('last_name', '')}".strip()
            or f"Player {p_id}"
        )

        player_list.append({
            "id": str(p_id),
            "name": full_name,
            "pos": player_info.get("position", "N/A"),
            "team": player_info.get("team") or "FA",
            "years_exp": player_info.get("years_exp", 0),
            "is_starter": str(p_id) in starter_ids,
            "points": player_points.get(str(p_id)),
            "injury_status": player_info.get("injury_status") or "Active",
        })

    return player_list