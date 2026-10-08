"""Resolve visible weekly modifiers from league events and item selections."""

import json

from game_logic.item_inputs import NFL_DIVISION_TEAMS


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


def _player_position(player_id: str, players_data: dict) -> str:
    player = players_data.get(str(player_id), {})
    return str(player.get("position") or player.get("pos") or "").upper()


def _format_modifiers(entries: list[tuple[str, float | None]]) -> str:
    if not entries:
        return "—"

    labels = [label for label, _factor in entries if label]
    if "OUT" in labels:
        labels = list(dict.fromkeys(
            label for label in labels
            if label not in {"OUT", "2x", "4x", "10x", "0.5x", "1x"}
        ))
        return " · ".join(["OUT"] + labels)

    factors = [factor for _label, factor in entries if factor is not None]
    formatted = []
    if factors:
        product = 1.0
        for factor in factors:
            product *= factor
        if product != 1.0 or len(factors) > 1:
            formatted.append(f"{product:g}x")

    formatted.extend(
        label for label, factor in entries
        if factor is None and label and label not in formatted
    )
    return " · ".join(formatted) if formatted else "—"


def build_weekly_player_modifiers(
    players_data: dict,
    weekly_plays: list[dict],
    weekly_events: list[dict],
    matchup_data_by_roster: dict,
    roster_map: dict,
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Return player-database and per-roster modifier display values."""
    league_effects: dict[str, list[tuple[str, float | None]]] = {}
    roster_effects: dict[str, dict[str, list[tuple[str, float | None]]]] = {}

    def add_league_effect(player_id: str, label: str, factor: float | None = None):
        league_effects.setdefault(str(player_id), []).append((label, factor))

    def add_roster_effect(
        roster_id: int | str,
        player_id: str,
        label: str,
        factor: float | None = None,
    ):
        roster_effects.setdefault(str(roster_id), {}).setdefault(
            str(player_id), []
        ).append((label, factor))

    roster_players = {
        str(roster_id): [str(player_id) for player_id in (matchup.get("players") or [])]
        for roster_id, matchup in matchup_data_by_roster.items()
    }
    roster_starters = {
        str(roster_id): {str(player_id) for player_id in (matchup.get("starters") or [])}
        for roster_id, matchup in matchup_data_by_roster.items()
    }

    for event in weekly_events:
        event_name = str(event.get("event_name") or "").strip().casefold()
        if event_name == "rookie of the week":
            for player_id, player in players_data.items():
                try:
                    is_rookie = float(player.get("years_exp")) == 0
                except (TypeError, ValueError):
                    is_rookie = False
                if is_rookie:
                    add_league_effect(str(player_id), "2x", 2.0)
        elif event_name == "the price is right":
            for roster_id, matchup in matchup_data_by_roster.items():
                points = matchup.get("points")
                if points is None:
                    continue
                factor = 2.0 if float(points) <= 100 else 0.5
                for player_id in roster_players.get(str(roster_id), []):
                    add_roster_effect(roster_id, player_id, f"{factor:g}x", factor)

    for play in weekly_plays:
        item_id = str(play.get("item_id") or "").upper()
        roster_id = str(play.get("roster_id"))
        selection = _selection_for_play(play)
        team_codes = set(selection.get("teams") or [])
        if selection.get("team"):
            team_codes.add(str(selection["team"]))
        division = selection.get("division")
        if division:
            team_codes.update(NFL_DIVISION_TEAMS.get(division, ()))

        if item_id in {"NFL_TEAM_BYE", "NFL_DIVISION_BYE"}:
            for player_id, player in players_data.items():
                if player.get("team") in team_codes:
                    add_league_effect(str(player_id), "OUT")
        elif item_id in {"NFL_TEAM_SUPERCHARGE", "NFL_DIVISION_SUPERCHARGE"}:
            for player_id, player in players_data.items():
                if player.get("team") in team_codes:
                    add_league_effect(str(player_id), "2x", 2.0)
                    add_league_effect(str(player_id), "SHELL IMMUNE")

        player_id = selection.get("player_id") or play.get("target_player_id")
        if item_id == "MUSHROOM" and player_id:
            add_roster_effect(roster_id, player_id, "+ACTIVE")
        elif item_id == "RECALL" and player_id:
            add_roster_effect(roster_id, player_id, "RECALL")
        elif item_id == "SUPERSTAR" and player_id:
            add_roster_effect(roster_id, player_id, "2x", 2.0)
            for teammate_id in roster_players.get(roster_id, []):
                add_roster_effect(roster_id, teammate_id, "SHELL IMMUNE")
        elif item_id == "BULLET_BILL" and player_id:
            add_roster_effect(roster_id, player_id, "10x", 10.0)
        elif item_id == "HYPERFLEX" and player_id:
            add_roster_effect(roster_id, player_id, "+ACTIVE")
        elif item_id == "ULTRAFLEX":
            name = str(selection.get("player_name") or "").strip().casefold()
            matching_ids = [
                str(candidate_id)
                for candidate_id, player in players_data.items()
                if name
                and name in {
                    str(player.get("full_name") or "").casefold(),
                    f"{player.get('first_name', '')} {player.get('last_name', '')}".strip().casefold(),
                }
            ]
            for candidate_id in matching_ids:
                add_roster_effect(roster_id, candidate_id, "+ACTIVE")
        elif item_id == "GOLDEN_MUSHROOM":
            for bench_id in set(roster_players.get(roster_id, [])) - roster_starters.get(roster_id, set()):
                add_roster_effect(roster_id, bench_id, "+ACTIVE")
        elif item_id == "SNOW_GAME_DOME_GAME":
            selected_position = selection.get("position")
            if selected_position:
                for teammate_id in roster_players.get(roster_id, []):
                    factor = 2.0 if _player_position(teammate_id, players_data) == selected_position else 0.5
                    add_roster_effect(roster_id, teammate_id, f"{factor:g}x", factor)
        elif item_id == "MASTER_BALL":
            target_player_id = (selection.get("target") or {}).get("player_id")
            if target_player_id:
                add_league_effect(str(target_player_id), "2x", 2.0)
                add_league_effect(str(target_player_id), "SHELL IMMUNE")
        elif item_id == "SMASH_BALL":
            lineup_ids = {
                str(slot.get("player_id"))
                for slot in selection.get("lineup", [])
                if slot.get("player_id")
            }
            current_player_ids = set(roster_players.get(roster_id, []))
            for current_player_id in current_player_ids:
                add_roster_effect(
                    roster_id,
                    current_player_id,
                    "DREAM" if current_player_id in lineup_ids else "OUT",
                )
            for lineup_player_id in lineup_ids:
                if lineup_player_id not in current_player_ids:
                    add_roster_effect(roster_id, lineup_player_id, "DREAM")

        elif item_id in {"SHELL", "TRIPLE_SHELL"}:
            target_roster_ids = selection.get("target_roster_ids") or []
            if selection.get("target_roster_id") is not None:
                target_roster_ids.append(selection["target_roster_id"])
            for target_roster_id in target_roster_ids:
                target_roster_id = str(target_roster_id)
                for target_player_id in roster_players.get(target_roster_id, []):
                    add_roster_effect(target_roster_id, target_player_id, "SHELL RISK")

    roster_modifier_maps = {}
    for roster_id, players in roster_players.items():
        roster_modifier_maps[roster_id] = {
            player_id: _format_modifiers(
                league_effects.get(player_id, [])
                + roster_effects.get(roster_id, {}).get(player_id, [])
            )
            for player_id in players
        }

    player_database_modifiers = {}
    all_player_ids = set(league_effects)
    for player_map in roster_effects.values():
        all_player_ids.update(player_map)

    for player_id in all_player_ids:
        base_effects = league_effects.get(player_id, [])
        context_values = []
        for roster_id, player_map in roster_effects.items():
            local_effects = player_map.get(player_id, [])
            if not local_effects:
                continue
            has_local_factor = any(factor is not None for _label, factor in local_effects)
            value = (
                _format_modifiers(base_effects + local_effects)
                if base_effects and has_local_factor
                else _format_modifiers(local_effects)
            )
            roster_name = next(
                (name for key, name in roster_map.items() if str(key) == roster_id),
                f"Roster {roster_id}",
            )
            context_values.append(f"{value} ({roster_name})")

        if context_values:
            if base_effects:
                base_value = _format_modifiers(base_effects)
                if base_value == "OUT":
                    player_database_modifiers[player_id] = "OUT"
                else:
                    player_database_modifiers[player_id] = " · ".join(
                        [base_value] + context_values
                    )
            else:
                player_database_modifiers[player_id] = " · ".join(context_values)
        elif base_effects:
            player_database_modifiers[player_id] = _format_modifiers(base_effects)

    return player_database_modifiers, roster_modifier_maps