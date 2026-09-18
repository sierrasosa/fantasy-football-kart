import random
import pandas as pd
from datetime import datetime

def generate_weekly_drops(supabase, week: int, standings_ranks: dict):
    """
    Checks if items are rolled for the week. If not, rolls items for each manager
    based on their position rank odds from Supabase.
    standings_ranks: {roster_id: rank_position (1 to 12)}
    """
    # 1. Check if league event replaces items this week
    events_res = supabase.table("league_events").select("*").eq("week", week).execute()
    if events_res.data:
        # Global event active; skip individual items
        return False, "Global league event active this week!"

    # 2. Check if drops already generated
    existing_drops = supabase.table("team_inventory").select("id").eq("week", week).execute()
    if existing_drops.data:
        return True, "Drops already generated for this week."

    # 3. Fetch item odds matrix from Supabase
    items = supabase.table("items").select("*").execute().data or []
    
    new_drops = []
    for roster_id, rank in standings_ranks.items():
        # Build weighted choices for manager's rank
        item_pool = []
        weights = []
        
        for item in items:
            odds_map = item.get("odds", {})
            weight = odds_map.get(str(rank), 0.0)
            if weight > 0:
                item_pool.append(item["id"])
                weights.append(weight)

        if item_pool and sum(weights) > 0:
            selected_item_id = random.choices(item_pool, weights=weights, k=1)[0]
            new_drops.append({
                "roster_id": roster_id,
                "item_id": selected_item_id,
                "week": week,
                "is_used": False
            })

    if new_drops:
        supabase.table("team_inventory").insert(new_drops).execute()
        return True, f"Generated item drops for {len(new_drops)} teams!"
    
    return False, "No items available to roll."