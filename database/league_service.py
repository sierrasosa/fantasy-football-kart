import hmac
import requests
from helpers import sleeper_api
import streamlit as st
from database.auth_service import generate_pin, hash_pin


def get_user_rosters(supabase_client, user_id: str, include_pin_hash: bool = False) -> list[dict]:
    """Load initialized league roster rows for a Sleeper user."""
    columns = "roster_id, league_id, league_name, user_id, user_name, team_name"
    if include_pin_hash:
        columns += ", pin_hash"
    rows = (
        supabase_client.table("rosters")
        .select(columns)
        .eq("user_id", str(user_id))
        .execute()
        .data
        or []
    )
    seasons = {}
    for row in rows:
        league_id = str(row.get("league_id", ""))
        if league_id and league_id not in seasons:
            try:
                league_info = sleeper_api.get_league_info(league_id)
                seasons[league_id] = str(league_info["season"])
            except (KeyError, ValueError, requests.RequestException):
                seasons[league_id] = "Year unknown"
        row["season"] = seasons.get(league_id, "Year unknown")
    return rows


def get_commissioner_leagues(account: dict, season: str) -> list[dict]:
    """Find the user's NFL leagues where they may initialize the app."""
    user_id = account.get("user_id")
    if not user_id:
        return []
    leagues = sleeper_api.get_user_nfl_leagues(str(user_id), season)
    username_is_exception = str(account.get("username", "")).casefold() == "sierrabellum"
    return [
        league
        for league in leagues
        if league.get("league_id")
        and (
            username_is_exception
            or sleeper_api.is_league_commissioner(str(league["league_id"]), str(user_id))
        )
    ]


def find_commissioner_leagues(account: dict, current_season: str) -> tuple[str | None, list[dict]]:
    """Find commissioner leagues, searching seasons back to 2022 if needed."""
    current_year = int(current_season)
    for year in range(current_year, 2021, -1):
        leagues = get_commissioner_leagues(account, str(year))
        if leagues:
            return str(year), leagues
    return None, []


def get_league_name(league_id: str) -> str:
    """Fetch the actual league name from Sleeper."""
    response = requests.get(
        f"https://api.sleeper.app/v1/league/{league_id}", timeout=30
    )
    response.raise_for_status()
    data = response.json()
    return data.get("name") or st.secrets.get("LEAGUE_NAME", "My Fantasy League")


def initialize_commissioner_league(
    supabase_client,
    account: dict,
    league: dict,
    setup_code: str,
    configured_code: str,
) -> dict:
    """Validate setup authorization and initialize one Sleeper league."""
    if not configured_code or not hmac.compare_digest(
        setup_code.encode(), configured_code.encode()
    ):
        raise ValueError("Invalid setup code.")

    user_id = str(account.get("user_id") or "")
    league_id = str(league.get("league_id") or "")
    if not user_id or not league_id:
        raise ValueError("Sleeper account or league ID is missing.")

    is_exception = str(account.get("username", "")).casefold() == "sierrabellum"
    if not is_exception and not sleeper_api.is_league_commissioner(league_id, user_id):
        raise PermissionError("Only a Sleeper league commissioner can initialize this league.")

    pins = sync_sleeper_rosters(
        league_id, supabase_client, commissioner_user_id=user_id
    )
    return {
        "league_name": league.get("name", "League"),
        "pins": pins,
    }


def sync_sleeper_rosters(
    league_id: str,
    supabase_client,
    commissioner_user_id: str | None = None,
) -> list[dict]:
    """Sync Sleeper rosters and return newly generated one-time manager PINs."""
    users_url = f"https://api.sleeper.app/v1/league/{league_id}/users"
    users_res = requests.get(users_url, timeout=30)
    users_res.raise_for_status()
    users = users_res.json()

    user_map = {}
    for user in users:
        user_id = user.get("user_id")
        if not user_id:
            continue
        metadata = user.get("metadata") or {}
        user_map[str(user_id)] = {
            "user_id": str(user_id),
            "user_name": user.get("display_name") or f"User {user_id}",
            "team_name": metadata.get("team_name") or user.get("display_name") or f"Team {user_id}",
            "commissioner": (
                bool(user.get("is_owner", False))
                or str(user_id) == str(commissioner_user_id)
            ),
        }

    rosters_url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    rosters_res = requests.get(rosters_url, timeout=30)
    rosters_res.raise_for_status()
    rosters = rosters_res.json()

    existing_rosters = (
        supabase_client.table("rosters")
        .select("roster_id, pin_hash")
        .eq("league_id", league_id)
        .execute()
        .data
        or []
    )
    existing_pin_hashes = {
        row.get("roster_id"): row.get("pin_hash")
        for row in existing_rosters
        if row.get("pin_hash")
    }

    league_name = get_league_name(league_id)
    roster_records = []
    manager_pins = []
    for roster in rosters:
        roster_id = roster.get("roster_id")
        owner_id = roster.get("owner_id")
        info = user_map.get(str(owner_id), {
            "user_id": str(owner_id or ""),
            "user_name": f"Manager {roster_id}",
            "team_name": f"Team {roster_id}",
            "commissioner": False,
        })

        existing_pin_hash = existing_pin_hashes.get(roster_id)
        if existing_pin_hash:
            pin_hash_value = existing_pin_hash
        else:
            pin = generate_pin()
            pin_hash_value = hash_pin(pin)
            manager_pins.append({
                "user_name": info["user_name"],
                "team_name": info["team_name"],
                "pin": pin,
            })

        roster_records.append({
            "roster_id": roster_id,
            "league_id": league_id,
            "user_id": info["user_id"] or None,
            "league_name": league_name,
            "user_name": info["user_name"],
            "team_name": info["team_name"],
            "commissioner": info["commissioner"],
            "pin_hash": pin_hash_value,
        })

    supabase_client.table("rosters").upsert(
        roster_records,
        on_conflict="league_id,roster_id",
    ).execute()

    template_events = (
        supabase_client.table("league_events")
        .select("week, event_name, description, chance")
        .is_("league_id", "null")
        .execute()
        .data
        or []
    )
    existing_events = (
        supabase_client.table("league_events")
        .select("week")
        .eq("league_id", league_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if template_events and not existing_events:
        supabase_client.table("league_events").insert([
            {**event, "league_id": league_id} for event in template_events
        ]).execute()

    return manager_pins