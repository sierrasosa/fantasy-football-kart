import pandas as pd
from supabase import create_client

# Initialize Supabase Client
import streamlit as st

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = st.secrets["SUPABASE_SERVICE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

excel_file = "item_rules.xlsx"

# -----------------------------------------------------------------------------
# 1. Parse & Seed Standard Items (Sheet: 'Player Items')
# -----------------------------------------------------------------------------
df_items = pd.read_excel(excel_file, sheet_name="Player Items").dropna(subset=["Item"])

items_to_insert = []
for _, row in df_items.iterrows():
    # Construct position-based odds dictionary (1st through 12th place)
    odds = {
        rank: float(row[f"{rank}{'st' if rank==1 else 'nd' if rank==2 else 'rd' if rank==3 else 'th'} odds"])
        for rank in range(1, 13)
    }
    
    # Map item to target requirements
    name = str(row["Item"]).strip()
    target_type = "SELF"
    if name in ["Shell", "Triple Shell", "Master Ball"]:
        target_type = "OPPONENT"
    elif name in ["NFL Team Bye", "NFL Team Supercharge"]:
        target_type = "NFL_TEAM"
    elif name in ["NFL Division Bye", "NFL Division Supercharge"]:
        target_type = "NFL_DIVISION"
    elif name in ["Snow Game/Dome Game"]:
        target_type = "CHOICE_POSITION"
    elif name in ["Recall", "Mushroom", "Superstar", "Bullet Bill"]:
        target_type = "ROSTER_PLAYER"
    elif name in ["Hyperflex", "Ultraflex", "Smash Ball"]:
        target_type = "FREE_TEXT"

    items_to_insert.append({
        "id": name.upper().replace(" ", "_").replace("/", "_"),
        "name": name,
        "description": str(row["Description"]).strip(),
        "target_type": target_type,
        "odds": odds
    })

supabase.table("items").upsert(items_to_insert).execute()
print("✅ Items table seeded successfully!")

# -----------------------------------------------------------------------------
# 2. Parse & Seed League-Wide Schedule (Sheet: 'League-wide')
# -----------------------------------------------------------------------------
df_events = pd.read_excel(excel_file, sheet_name="League-wide")

events_to_insert = []
for _, row in df_events.iterrows():
    event_name = str(row["Item"]).strip()
    if event_name == "Player Items":
        continue
    
    description = str(row["Description"]).strip()
    
    for week in range(1, 19):
        col_name = f"Odds of occurance week {week}"
        chance = float(row[col_name]) if col_name in row and pd.notna(row[col_name]) else 0.0
        
        if chance > 0:
            events_to_insert.append({
                "week": week,
                "event_name": event_name,
                "description": description,
                "chance": chance
            })

supabase.table("league_events").upsert(events_to_insert).execute()
print("✅ League-wide events seeded successfully!")

# -----------------------------------------------------------------------------
# 3. Parse & Seed Special Players (Sheet: 'Special Players')
# -----------------------------------------------------------------------------
df_special = pd.read_excel(excel_file, sheet_name="Special Players").dropna(subset=["Item"])

special_to_insert = []
for _, row in df_special.iterrows():
    special_to_insert.append({
        "player_name": str(row["Item"]).strip(),
        "description": str(row["Description"]).strip()
    })

supabase.table("special_player_rules").upsert(special_to_insert).execute()
print("✅ Special player rules seeded successfully!")