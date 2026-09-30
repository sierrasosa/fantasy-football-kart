import streamlit as st
from supabase import create_client

from auth_service import generate_pin, hash_pin, verify_pin
from league_service import sync_sleeper_rosters


if __name__ == "__main__":
    supabase_client = create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_SERVICE_KEY"],
    )
    manager_pins = sync_sleeper_rosters(
        st.secrets["SLEEPER_LEAGUE_ID"], supabase_client
    )
    for manager in manager_pins:
        print(f"{manager['user_name']} ({manager['team_name']}): {manager['pin']}")