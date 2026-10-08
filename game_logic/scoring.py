"""Apply weekly item effects to Sleeper matchup scores."""

import json

from game_logic.item_inputs import NFL_DIVISION_TEAMS

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


def _selection_for_play(play: dict) -> dict:
    selection = play.get("selection") or {}
    if isinstance(selection, str):
        try:
            selection = json.loads(selection)
        except json.JSONDecodeError:
            selection = {}
    if selection:
        return selection

    custom_target = play.get("custom_target")
    if isinstance(custom_target, str) and custom_target.lstrip().startswith("{"):
        try:
            return json.loads(custom_target)
        except json.JSONDecodeError:
            return {}
    return {}


def _player_points(matchup: dict, player_id: str) -> float | None:
    points = matchup.get("players_points") or {}
    if not isinstance(points, dict):
        return None
    for candidate_id, score in points.items():
        if str(candidate_id) != str(player_id):
            continue
        try:
            return float(score or 0.0)
        except (TypeError, ValueError):
            return None
    return None


def _league_player_points(matchups: list[dict]) -> dict[str, float]:
    player_points = {}
    if not isinstance(matchups, list):
        return player_points

    for matchup in matchups:
        if not isinstance(matchup, dict):
            continue
        scores = matchup.get("players_points") or {}
        if not isinstance(scores, dict):
            continue
        for player_id in scores:
            score = _player_points(matchup, str(player_id))
            if score is not None:
                player_points.setdefault(str(player_id), score)
    return player_points


def _score_or_zero(score: float | None) -> float:
    return score if score is not None else 0.0


def _selection_team_codes(selection: dict) -> set[str]:
    team_codes = {str(team) for team in selection.get("teams") or []}
    if selection.get("team"):
        team_codes.add(str(selection["team"]))
    division = selection.get("division")
    if division:
        team_codes.update(NFL_DIVISION_TEAMS.get(division, ()))
    return team_codes


def calculate_modified_scores(
    matchups,
    weekly_plays,
    players_data,
    previous_week_matchups=None,
):
    """Apply implemented player-score effects and return one result per roster.

    Effects which need different data or a team-to-team points transfer are
    reported in ``effects`` until their scoring rules are implemented.
    """
    global_byes: set[str] = set()
    global_factors: dict[str, list[float]] = {}
    local_factors: dict[str, dict[str, list[float]]] = {}
    extra_players: dict[str, set[str]] = {}
    dream_lineups: dict[str, list[str]] = {}
    bullet_targets: dict[str, str] = {}
    recall_targets: dict[str, str] = {}
    recall_points: dict[str, dict[str, float]] = {}
    pending_effects: dict[str, list[str]] = {}
    roster_players = {
        str(matchup.get("roster_id")): [
            str(player_id) for player_id in matchup.get("players") or []
        ]
        for matchup in matchups
        if isinstance(matchup, dict)
    }
    league_player_points = _league_player_points(matchups)
    previous_week_points = _league_player_points(previous_week_matchups or [])

    def add_local_factor(roster_id: str, player_id: str, factor: float) -> None:
        local_factors.setdefault(roster_id, {}).setdefault(
            player_id,
            [],
        ).append(factor)

    for play in weekly_plays:
        item_id = str(play.get("item_id") or "").upper()
        roster_id = str(play.get("roster_id"))
        selection = _selection_for_play(play)
        team_codes = _selection_team_codes(selection)

        if item_id in {"NFL_TEAM_BYE", "NFL_DIVISION_BYE"}:
            for player_id, player in players_data.items():
                if player.get("team") in team_codes:
                    global_byes.add(str(player_id))
        elif item_id in {"NFL_TEAM_SUPERCHARGE", "NFL_DIVISION_SUPERCHARGE"}:
            for player_id, player in players_data.items():
                if player.get("team") in team_codes:
                    global_factors.setdefault(str(player_id), []).append(2.0)

        player_id = str(
            selection.get("player_id")
            or play.get("target_player_id")
            or ""
        )
        if item_id == "MUSHROOM" and player_id:
            extra_players.setdefault(roster_id, set()).add(player_id)
        elif item_id == "SUPERSTAR" and player_id:
            add_local_factor(roster_id, player_id, 2.0)
        elif item_id == "BULLET_BILL" and player_id:
            bullet_targets[roster_id] = player_id
        elif item_id == "SNOW_GAME_DOME_GAME":
            position = str(selection.get("position") or "").upper()
            if position in {"RB", "WR"}:
                for teammate_id in roster_players.get(roster_id, []):
                    player = players_data.get(teammate_id, {})
                    player_position = str(
                        player.get("position") or player.get("pos") or ""
                    ).upper()
                    if player_position in {"RB", "WR"}:
                        add_local_factor(
                            roster_id,
                            teammate_id,
                            2.0 if player_position == position else 0.5,
                        )
        elif item_id in {"HYPERFLEX", "ULTRAFLEX"}:
            if player_id:
                extra_players.setdefault(roster_id, set()).add(player_id)
            elif item_id == "ULTRAFLEX":
                player_name = str(
                    selection.get("player_name") or ""
                ).strip().casefold()
                matching_ids = [
                    str(candidate_id)
                    for candidate_id, player in players_data.items()
                    if player_name
                    and player_name in {
                        str(player.get("full_name") or "").casefold(),
                        (
                            f"{player.get('first_name', '')} "
                            f"{player.get('last_name', '')}"
                        ).strip().casefold(),
                    }
                ]
                if len(matching_ids) == 1:
                    extra_players.setdefault(roster_id, set()).update(matching_ids)
                else:
                    pending_effects.setdefault(roster_id, []).append(
                        "Ultraflex: selected player could not be matched to one "
                        "player in the NFL database"
                    )
        elif item_id == "GOLDEN_MUSHROOM":
            extra_players.setdefault(roster_id, set()).add("*BENCH*")
        elif item_id == "SMASH_BALL":
            dream_lineups[roster_id] = [
                str(slot.get("player_id"))
                for slot in selection.get("lineup") or []
                if slot.get("player_id")
            ]
        elif item_id == "RECALL":
            if player_id:
                recall_targets[roster_id] = player_id
            else:
                pending_effects.setdefault(roster_id, []).append(
                    "Recall: no player was selected"
                )
        elif item_id == "MASTER_BALL":
            pending_effects.setdefault(roster_id, []).append(
                "Master Ball: traded-player scoring is not yet applied"
            )
        elif item_id in {"SHELL", "TRIPLE_SHELL"}:
            pending_effects.setdefault(roster_id, []).append(
                "Shell: player targeting and score transfer are not yet applied"
            )

    modified_matchups = []
    for team in matchups:
        roster_id = team.get("roster_id")
        roster_key = str(roster_id)
        raw_score = float(team.get("points") or 0.0)
        starters = [str(player_id) for player_id in team.get("starters") or []]
        players = {
            str(player_id) for player_id in team.get("players") or []
        }
        recall_player_id = recall_targets.get(roster_key)
        if recall_player_id:
            if recall_player_id not in starters:
                pending_effects.setdefault(roster_key, []).append(
                    "Recall: selected player is not a current starter"
                )
            else:
                recalled_score = previous_week_points.get(recall_player_id)
                if recalled_score is None:
                    pending_effects.setdefault(roster_key, []).append(
                        "Recall: previous-week points are unavailable for the "
                        "selected player"
                    )
                else:
                    recall_points.setdefault(roster_key, {})[
                        recall_player_id
                    ] = recalled_score

        roster_extras = extra_players.get(roster_key, set())
        if "*BENCH*" in roster_extras:
            roster_extras = roster_extras | (players - set(starters))
            roster_extras.discard("*BENCH*")
        roster_extras = roster_extras - set(starters)

        def adjusted_points(
            player_id: str,
            ignore_bye: bool = False,
        ) -> float | None:
            if not ignore_bye and player_id in global_byes:
                return 0.0
            factors = (
                global_factors.get(player_id, [])
                + local_factors.get(roster_key, {}).get(player_id, [])
            )
            factor = 1.0
            for value in factors:
                factor *= value
            score = recall_points.get(roster_key, {}).get(
                player_id,
                _player_points(team, player_id),
            )
            if score is None:
                score = league_player_points.get(player_id)
            if score is None:
                return None
            return score * factor

        effects = list(pending_effects.get(roster_key, []))
        player_scores = {
            player_id: adjusted_points(player_id)
            for player_id in players
        }
        if roster_key in dream_lineups:
            lineup_points = [
                adjusted_points(player_id, ignore_bye=True)
                for player_id in dream_lineups[roster_key]
            ]
            if any(score is None for score in lineup_points):
                modified_score = raw_score
                effects.append(
                    "Smash Ball: score not applied; weekly points are missing "
                    "for one or more selected players"
                )
            else:
                modified_score = sum(
                    _score_or_zero(score) for score in lineup_points
                )
                effects.append(
                    "Smash Ball: dream lineup replaces your roster score"
                )
                player_scores = {
                    player_id: (
                        adjusted_points(player_id, ignore_bye=True)
                        if player_id in dream_lineups[roster_key]
                        else 0.0
                    )
                    for player_id in players
                }
        elif roster_key in bullet_targets:
            player_id = bullet_targets[roster_key]
            player_score = adjusted_points(player_id)
            if player_score is None:
                modified_score = raw_score
                effects.append(
                    "Bullet Bill: score not applied; weekly points are missing "
                    "for the selected player"
                )
            else:
                modified_score = player_score * 10
                player_scores = {
                    roster_player_id: (
                        modified_score
                        if roster_player_id == player_id
                        else 0.0
                    )
                    for roster_player_id in players
                }
                effects.append(
                    "Bullet Bill: selected player score counts 10 times"
                )
        else:
            starting_points = 0.0
            adjusted_starting_points = 0.0
            missing_starters = []
            for player_id in starters:
                base_points = _player_points(team, player_id)
                if base_points is None:
                    base_points = league_player_points.get(player_id)
                if (
                    player_id == recall_player_id
                    and player_id in recall_points.get(roster_key, {})
                ):
                    base_points = _player_points(team, player_id)
                changed_points = adjusted_points(player_id)
                if base_points is None or changed_points is None:
                    has_modifier = (
                        player_id in global_byes
                        or player_id in global_factors
                        or player_id in local_factors.get(roster_key, {})
                    )
                    if has_modifier:
                        missing_starters.append(player_id)
                    continue
                starting_points += base_points
                adjusted_starting_points += changed_points
            modified_score = (
                raw_score
                - starting_points
                + adjusted_starting_points
            )
            extra_player_points = {
                player_id: adjusted_points(player_id)
                for player_id in roster_extras
            }
            added_points = sum(
                _score_or_zero(score)
                for score in extra_player_points.values()
            )
            modified_score += added_points
            if added_points:
                effects.append(f"Extra players: +{added_points:.2f} pts")
            missing_extra_players = [
                player_id
                for player_id, score in extra_player_points.items()
                if score is None
            ]
            if missing_extra_players:
                effects.append(
                    "Extra player score not applied; weekly points are missing "
                    f"for {', '.join(missing_extra_players)}"
                )
            if missing_starters:
                effects.append(
                    "Starter adjustments not fully applied; weekly points are "
                    f"missing for {', '.join(missing_starters)}"
                )

            if adjusted_starting_points != starting_points:
                effects.append(
                    "Player modifiers: "
                    f"{adjusted_starting_points - starting_points:+.2f} pts"
                )
            if recall_player_id in recall_points.get(roster_key, {}):
                effects.append("Recall: prior-week score replaces current score")

        modified_matchups.append({
            "roster_id": roster_id,
            "matchup_id": team.get("matchup_id"),
            "raw_score": round(raw_score, 2),
            "modified_score": round(modified_score, 2),
            "effects": effects,
            "player_scores": player_scores,
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
            weekly_matchups.get(week - 1, []),
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
