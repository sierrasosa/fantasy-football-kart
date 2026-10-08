GP_POINTS_MAP = {
    1: 15,
    2: 12,
    3: 10,
    4: 9,
    5: 8,
    6: 7,
    7: 6,
    8: 5,
    9: 4,
    10: 3,
    11: 2,
    12: 1,
}


def calculate_modified_scores(matchups, weekly_plays, players_data):
    """
    Applies played chaos items to raw Sleeper matchup scores.
    
    Args:
        matchups (list): Matchup objects from Sleeper API.
        weekly_plays (list): List of play dicts from Supabase 'weekly_plays' table.
        players_data (dict): Filtered NFL player database from helpers/sleeper_api.py.
        
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


def calculate_gp_standings(
    weekly_matchups: dict[int, list[dict]],
    weekly_plays: list[dict],
    players_data: dict,
    roster_ids: list[int],
) -> list[dict]:
    """Rank rosters by cumulative GP points, then cumulative modified score."""
    season_totals = {roster_id: 0 for roster_id in roster_ids}
    season_scores = {roster_id: 0.0 for roster_id in roster_ids}

    for week, matchups in weekly_matchups.items():
        if not matchups:
            continue
        week_plays = [play for play in weekly_plays if play.get("week") == week]
        calculated_matchups = calculate_modified_scores(
            matchups,
            week_plays,
            players_data,
        )
        week_standings = sorted(
            calculated_matchups,
            key=lambda team: (
                team.get("modified_score", 0.0),
                team.get("raw_score", 0.0),
            ),
            reverse=True,
        )

        for rank, team in enumerate(week_standings, start=1):
            roster_id = team.get("roster_id")
            if roster_id is None:
                continue
            season_totals[roster_id] = (
                season_totals.get(roster_id, 0)
                + GP_POINTS_MAP.get(rank, 0)
            )
            season_scores[roster_id] = (
                season_scores.get(roster_id, 0.0)
                + team.get("modified_score", 0.0)
            )

    return [
        {
            "roster_id": roster_id,
            "gp_points": gp_points,
            "modified_score": season_scores.get(roster_id, 0.0),
        }
        for roster_id, gp_points in sorted(
            season_totals.items(),
            key=lambda item: (
                item[1],
                season_scores.get(item[0], 0.0),
            ),
            reverse=True,
        )
    ]