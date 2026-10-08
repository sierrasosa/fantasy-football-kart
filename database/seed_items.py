import pandas as pd
from supabase import create_client
from pathlib import Path
from game_logic.item_inputs import ITEM_INPUTS

# Initialize Supabase Client
import streamlit as st

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = st.secrets["SUPABASE_SERVICE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

excel_file = Path(__file__).resolve().parent.parent / "data" / "item_rules.xlsx"

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
    
    name = str(row["Item"]).strip()
    item_id = name.upper().replace(" ", "_").replace("/", "_")
    input_spec = ITEM_INPUTS[item_id]

    items_to_insert.append({
        "id": item_id,
        "name": name,
        "description": str(row["Description"]).strip(),
        "target_type": input_spec["mode"],
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