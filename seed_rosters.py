import hashlib
import requests
import streamlit as st
from supabase import create_client

# Initialize Supabase client
supabase_url = st.secrets["SUPABASE_URL"]
# Use service_role key to bypass RLS for administrative script execution
supabase_service_key = st.secrets["SUPABASE_SERVICE_KEY"]
league_id = st.secrets["SLEEPER_LEAGUE_ID"]

supabase = create_client(supabase_url, supabase_service_key)

def hash_pin(pin: str) -> str:
    """Hashes a 4-digit PIN using SHA-256."""
    return hashlib.sha256(pin.encode()).hexdigest()

def sync_sleeper_rosters():
    # 1. Fetch league users (maps user_id -> display_name / team_name)
    users_url = f"https://api.sleeper.app/v1/league/{league_id}/users"
    users_res = requests.get(users_url).json()
    user_map = {}
    for user in users_res:
        u_id = user.get("user_id")
        owner_name = user.get("display_name", f"User {u_id}")
        team_name = user.get("metadata", {}).get("team_name") or owner_name
        user_map[u_id] = {"owner_name": owner_name, "team_name": team_name}

    # 2. Fetch league rosters
    rosters_url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    rosters_res = requests.get(rosters_url).json()

    # Default 4-digit PIN for initial setup
    default_pin_hash = hash_pin("1234")

    roster_records = []
    for r in rosters_res:
        roster_id = r["roster_id"]
        owner_id = r.get("owner_id")
        
        info = user_map.get(owner_id, {
            "owner_name": f"Manager {roster_id}", 
            "team_name": f"Team {roster_id}"
        })

        roster_records.append({
            "roster_id": roster_id,
            "owner_name": info["owner_name"],
            "team_name": info["team_name"],
            "pin_hash": default_pin_hash
        })

    # 3. Upsert records into Supabase
    data = supabase.table("rosters").upsert(roster_records).execute()
    print(f"Successfully seeded {len(roster_records)} rosters into Supabase!")

if __name__ == "__main__":
    sync_sleeper_rosters()