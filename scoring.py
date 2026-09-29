def calculate_modified_scores(matchups, weekly_plays, players_data):
    """
    Applies played chaos items to raw Sleeper matchup scores.
    
    Args:
        matchups (list): Matchup objects from Sleeper API.
        weekly_plays (list): List of play dicts from Supabase 'weekly_plays' table.
        players_data (dict): Filtered NFL player database from sleeper_api.py.
        
    Returns:
        list: Calculated scores and breakdown logs for display in Streamlit.
    """
    modified_matchups = []
    
    # 2. Iterate through each team's raw Sleeper matchup data
    for team in matchups:
        roster_id = team.get("roster_id")
        raw_score = team.get("points") or 0.0
        starters = team.get("starters") or []
        players = team.get("players") or []
        players_points = team.get("players_points") or {}
        
        modified_score = 0.0
        applied_effects = []

        modified_matchups.append({
            "roster_id": roster_id,
            "matchup_id": team.get("matchup_id"),
            "raw_score": round(raw_score, 2),
            "modified_score": round(modified_score, 2),
            "effects": applied_effects
        })
        
    return modified_matchups