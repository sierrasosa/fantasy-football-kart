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
    
    # 1. Map played items by target for instant lookup
    
    # Map target_player_id -> roster_id of attacker
    frozen_players = {
        play["target_player_id"]: play["roster_id"] 
        for play in weekly_plays 
        if play.get("item_id") == "FREEZE_PLAYER" and play.get("target_player_id")
    }
    
    # Map target_nfl_team -> roster_id of user who activated it
    double_teams = {
        play["target_nfl_team"]: play["roster_id"] 
        for play in weekly_plays 
        if play.get("item_id") == "DOUBLE_TEAM" and play.get("target_nfl_team")
    }
    
    # List of roster_ids who played the bench boost
    bench_boost_rosters = [
        play["roster_id"] 
        for play in weekly_plays 
        if play.get("item_id") == "PLAY_BENCH"
    ]

    # 2. Iterate through each team's raw Sleeper matchup data
    for team in matchups:
        roster_id = team.get("roster_id")
        raw_score = team.get("points") or 0.0
        starters = team.get("starters") or []
        players = team.get("players") or []
        players_points = team.get("players_points") or {}
        
        modified_score = 0.0
        applied_effects = []
        
        # Calculate starters' points with active item modifiers
        for p_id in starters:
            pts = players_points.get(p_id) or 0.0
            p_info = players_data.get(p_id, {})
            p_name = p_info.get("name", p_id)
            p_team = p_info.get("team")
            
            # Modifier 1: Freeze Player (Sets player points to 0)
            if p_id in frozen_players:
                attacker_id = frozen_players[p_id]
                applied_effects.append(f"❄️ {p_name} was FROZEN by Team {attacker_id} (Scored 0 pts instead of {pts:.2f})")
                pts = 0.0
            
            # Modifier 2: Double Team (Doubles score for starters on selected NFL team)
            elif p_team and p_team in double_teams:
                pts *= 2.0
                applied_effects.append(f"⚡ {p_name} ({p_team}) doubled to {pts:.2f} pts")
                
            modified_score += pts

        # Modifier 3: Sixth Man / Bench Boost (Adds bench player points to team total)
        if roster_id in bench_boost_rosters:
            bench_ids = [p for p in players if p not in starters]
            bench_pts = sum((players_points.get(p) or 0.0) for p in bench_ids)
            modified_score += bench_pts
            applied_effects.append(f"🏀 Sixth Man Boost activated: Added +{bench_pts:.2f} bench pts")

        modified_matchups.append({
            "roster_id": roster_id,
            "matchup_id": team.get("matchup_id"),
            "raw_score": round(raw_score, 2),
            "modified_score": round(modified_score, 2),
            "effects": applied_effects
        })
        
    return modified_matchups