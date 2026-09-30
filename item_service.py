import random


def generate_weekly_drops(
    supabase,
    league_id: str,
    week: int,
    standings_ranks: dict,
) -> tuple[bool, str]:
    """Generate one league's weekly item drops based on standings."""
    events_res = (
        supabase.table("league_events")
        .select("*")
        .eq("league_id", league_id)
        .eq("week", week)
        .execute()
    )
    if events_res.data:
        return False, "Global league event active this week!"

    existing_drops = (
        supabase.table("team_inventory")
        .select("id")
        .eq("league_id", league_id)
        .eq("week", week)
        .execute()
    )
    if existing_drops.data:
        return True, "Drops already generated for this week."

    items = supabase.table("items").select("*").execute().data or []
    new_drops = []
    for roster_id, rank in standings_ranks.items():
        item_pool = []
        weights = []
        for item in items:
            odds_map = item.get("odds", {})
            weight = odds_map.get(str(rank), odds_map.get(rank, 0.0))
            if weight > 0:
                item_pool.append(item["id"])
                weights.append(weight)

        if item_pool and sum(weights) > 0:
            selected_item_id = random.choices(item_pool, weights=weights, k=1)[0]
            new_drops.append({
                "league_id": league_id,
                "roster_id": roster_id,
                "item_id": selected_item_id,
                "week": week,
                "is_used": False,
            })

    if new_drops:
        supabase.table("team_inventory").insert(new_drops).execute()
        return True, f"Generated item drops for {len(new_drops)} teams!"
    return False, "No items available to roll."