"""Apply weekly item effects to Sleeper matchup scores."""

import json

from game_logic.item_inputs import NFL_DIVISION_TEAMS
from game_logic.player_scores import normalize_player_name, player_score_key

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
            return None if score is None else float(score)
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


def _player_name(player_id: str, players_data: dict) -> str:
    player = players_data.get(player_id, {})
    return (
        str(player.get("full_name") or "").strip()
        or f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
    )


def _resolve_player_id(
    player_id: object | None,
    player_name: str | None,
    players_data: dict,
) -> str | None:
    if player_id is not None and str(player_id).strip():
        return str(player_id).strip()
    normalized_name = normalize_player_name(player_name or "")
    if not normalized_name:
        return None
    matches = [
        str(candidate_id)
        for candidate_id, player in players_data.items()
        if normalized_name
        in {
            normalize_player_name(str(player.get("full_name") or "")),
            normalize_player_name(
                f"{player.get('first_name', '')} {player.get('last_name', '')}"
            ),
        }
    ]
    return matches[0] if len(matches) == 1 else None


def _score_from_sources(
    player_id: str | None,
    player_name: str | None,
    matchup_points: dict | None,
    league_player_points: dict[str, float],
    fallback_player_points: dict[str, float],
) -> float | None:
    if player_id:
        score = _player_points(matchup_points or {}, player_id)
        if score is None:
            score = league_player_points.get(player_id)
        if score is not None:
            return score

    if player_id:
        score = fallback_player_points.get(player_score_key(player_id))
        if score is not None:
            return score
    if player_name:
        score_key = player_score_key(player_name=player_name)
        return fallback_player_points.get(score_key)
    return None


def get_missing_item_player_score_targets(
    weekly_plays: list[dict],
    current_week_matchups: list[dict],
    previous_week_matchups: list[dict],
    players_data: dict,
    current_week: int,
    fallback_player_points_by_week: dict[int, dict[str, float]],
) -> list[dict]:
    """Find item-selected players still missing a raw score for their scoring week."""
    live_points_by_week = {
        current_week: _league_player_points(current_week_matchups),
    }
    if current_week > 1:
        live_points_by_week[current_week - 1] = _league_player_points(
            previous_week_matchups
        )

    targets = []
    item_ids_with_player_scores = {
        "MUSHROOM",
        "SUPERSTAR",
        "BULLET_BILL",
        "HYPERFLEX",
        "ULTRAFLEX",
        "RECALL",
    }

    for play in weekly_plays:
        item_id = str(play.get("item_id") or "").upper()
        selection = _selection_for_play(play)
        scoring_week = current_week - 1 if item_id == "RECALL" else current_week
        if scoring_week < 1:
            continue

        selected_players = []
        if item_id == "SMASH_BALL":
            selected_players = [
                (
                    slot.get("player_id"),
                    None,
                    str(slot.get("slot") or "Dream lineup"),
                )
                for slot in selection.get("lineup") or []
                if isinstance(slot, dict) and slot.get("player_id")
            ]
        elif item_id in item_ids_with_player_scores:
            selected_players = [(
                selection.get("player_id") or play.get("target_player_id"),
                selection.get("player_name"),
                item_id.replace("_", " ").title(),
            )]

        for selected_id, selected_name, item_label in selected_players:
            resolved_id = _resolve_player_id(
                selected_id,
                str(selected_name) if selected_name else None,
                players_data,
            )
            player_name = (
                str(selected_name).strip()
                if selected_name
                else _player_name(resolved_id, players_data)
                if resolved_id
                else ""
            )
            if not resolved_id and not player_name:
                continue
            key = player_score_key(resolved_id, player_name)
            fallback_points = fallback_player_points_by_week.get(
                scoring_week, {}
            )
            has_live_score = bool(
                resolved_id
                and resolved_id
                in live_points_by_week.get(scoring_week, {})
            )
            has_saved_score = (
                key in fallback_points
                or (
                    bool(player_name)
                    and player_score_key(player_name=player_name)
                    in fallback_points
                )
            )
            if has_live_score or has_saved_score:
                continue
            targets.append({
                "player_id": resolved_id,
                "player_name": player_name or f"Player {resolved_id}",
                "player_key": key,
                "scoring_week": scoring_week,
                "item_label": item_label,
            })

    return targets


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
    fallback_player_points=None,
    previous_week_fallback_player_points=None,
    weekly_events=None,
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
    extra_player_names: dict[str, set[str]] = {}
    pending_effects: dict[str, list[str]] = {}
    fallback_player_points = fallback_player_points or {}
    previous_week_fallback_player_points = (
        previous_week_fallback_player_points or {}
    )
    for event in weekly_events or []:
        if (
            str(event.get("event_name") or "").strip().casefold()
            != "rookie of the week"
        ):
            continue
        for player_id, player in players_data.items():
            try:
                is_rookie = float(player.get("years_exp")) == 0
            except (TypeError, ValueError):
                is_rookie = False
            if is_rookie:
                global_factors.setdefault(str(player_id), []).append(2.0)

    roster_players = {
        str(matchup.get("roster_id")): [
            str(player_id) for player_id in matchup.get("players") or []
        ]
        for matchup in matchups
        if isinstance(matchup, dict)
    }
    league_player_points = _league_player_points(matchups)
    previous_week_points = _league_player_points(previous_week_matchups or [])
    for player_key, score in previous_week_fallback_player_points.items():
        if player_key.startswith("id:"):
            previous_week_points.setdefault(player_key.removeprefix("id:"), score)

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
                ).strip()
                matching_id = _resolve_player_id(
                    None,
                    player_name,
                    players_data,
                )
                if matching_id:
                    extra_players.setdefault(roster_id, set()).add(matching_id)
                elif normalize_player_name(player_name):
                    extra_player_names.setdefault(roster_id, set()).add(
                        player_name
                    )
                else:
                    pending_effects.setdefault(roster_id, []).append(
                        "Ultraflex: no player was selected"
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
                    recalled_score = _score_from_sources(
                        recall_player_id,
                        _player_name(recall_player_id, players_data),
                        None,
                        {},
                        previous_week_fallback_player_points,
                    )
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
            player_name: str | None = None,
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
            score = recall_points.get(roster_key, {}).get(player_id)
            if score is None:
                score = _score_from_sources(
                    player_id or None,
                    player_name
                    or (_player_name(player_id, players_data) if player_id else None),
                    team,
                    league_player_points,
                    fallback_player_points,
                )
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
                adjusted_points(
                    player_id,
                    ignore_bye=True,
                    player_name=_player_name(player_id, players_data),
                )
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
                player_scores = {player_id: player_score}
                effects.append(
                    "Bullet Bill: selected player score counts 10 times"
                )
        else:
            starting_points = 0.0
            adjusted_starting_points = 0.0
            missing_starters = []
            for player_id in starters:
                base_points = _score_from_sources(
                    player_id,
                    _player_name(player_id, players_data),
                    team,
                    league_player_points,
                    fallback_player_points,
                )
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
            player_scores.update(extra_player_points)
            name_extra_points = {
                player_name: adjusted_points("", player_name=player_name)
                for player_name in extra_player_names.get(roster_key, set())
            }
            added_points = sum(
                _score_or_zero(score)
                for score in (
                    list(extra_player_points.values())
                    + list(name_extra_points.values())
                )
            )
            modified_score += added_points
            if added_points:
                effects.append(f"Extra players: +{added_points:.2f} pts")
            missing_extra_players = [
                player_label
                for player_label, score in (
                    list(extra_player_points.items())
                    + list(name_extra_points.items())
                )
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
    fallback_player_points_by_week: dict[int, dict[str, float]] | None = None,
    weekly_events_by_week: dict[int, list[dict]] | None = None,
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
            (fallback_player_points_by_week or {}).get(week, {}),
            (fallback_player_points_by_week or {}).get(week - 1, {}),
            (weekly_events_by_week or {}).get(week, []),
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
