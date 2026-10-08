"""Shared input form for the weekly item selection flow."""

import random

import pandas as pd
import streamlit as st

from game_logic.item_inputs import (
    ITEM_INPUTS,
    LINEUP_SLOT_POSITIONS,
    NFL_DIVISION_TEAMS,
    NFL_TEAM_NAMES,
    NON_STARTER_SLOTS,
)
from helpers import sleeper_api


def build_lineup_slots(roster_positions: list[str]) -> list[dict]:
    """Expand Sleeper starter slots into labeled, position-aware rows."""
    slot_counts = {}
    lineup_slots = []
    for roster_position in roster_positions:
        position = str(roster_position).upper()
        if position in NON_STARTER_SLOTS:
            continue

        slot_counts[position] = slot_counts.get(position, 0) + 1
        eligible_positions = LINEUP_SLOT_POSITIONS.get(position, (position,))
        lineup_slots.append({
            "slot": f"{position} {slot_counts[position]}",
            "eligible_positions": eligible_positions,
        })
    return lineup_slots


def assign_starter_slots(
    starters: list[str],
    roster_positions: list[str],
    players_data: dict,
) -> dict[str, str]:
    """Map starter IDs to compatible configured lineup slots."""
    lineup_slots = build_lineup_slots(roster_positions)
    player_positions = {
        str(player_id): str(
            players_data.get(str(player_id), {}).get("position")
            or players_data.get(str(player_id), {}).get("pos")
            or ""
        ).upper()
        for player_id in starters
    }
    candidates_by_player = {
        player_id: [
            index for index, slot in enumerate(lineup_slots)
            if player_positions[player_id] in slot["eligible_positions"]
        ]
        for player_id in player_positions
    }
    ordered_players = sorted(
        (
            player_id for player_id in player_positions
            if candidates_by_player[player_id]
        ),
        key=lambda player_id: (
            len(candidates_by_player[player_id]),
            player_id,
        ),
    )

    slot_to_player: dict[int, str] = {}

    def assign_player(player_id: str, visited_slots: set[int]) -> bool:
        for slot_index in candidates_by_player[player_id]:
            if slot_index in visited_slots:
                continue
            visited_slots.add(slot_index)
            assigned_player = slot_to_player.get(slot_index)
            if (
                assigned_player is None
                or assign_player(assigned_player, visited_slots)
            ):
                slot_to_player[slot_index] = player_id
                return True
        return False

    for player_id in reversed(ordered_players):
        assign_player(player_id, set())

    return {
        player_id: lineup_slots[slot_index]["slot"]
        for slot_index, player_id in slot_to_player.items()
    }


def _player_name(player_id: str, player: dict) -> str:
    return (
        player.get("name")
        or player.get("full_name")
        or f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
        or f"Player {player_id}"
    )


def _player_label(player_id: str, player: dict) -> str:
    name = _player_name(player_id, player)
    position = player.get("pos") or player.get("position") or "N/A"
    team = player.get("team") or "FA"
    return f"{name} · {position} · {team} · {player_id}"


def _own_roster_players(
    league_id: str,
    roster_id: int,
    matchup_data_by_roster: dict,
) -> list[dict]:
    return sleeper_api.get_roster_players(
        league_id,
        roster_id,
        matchup_data=matchup_data_by_roster.get(str(roster_id)),
    ) or []


def build_random_item_selection(
    item_id: str,
    league_id: str,
    week: int,
    roster_id: int,
    roster_map: dict,
    matchup_data_by_roster: dict,
    players_data: dict,
) -> dict:
    """Build a random valid selection using the item's normal eligibility rules."""
    input_spec = ITEM_INPUTS.get(item_id)
    if input_spec is None:
        raise ValueError(f"No input mapping is defined for {item_id}.")

    mode = input_spec["mode"]
    selection = {"mode": mode}
    opponent_roster_ids = [
        target_roster_id
        for target_roster_id in roster_map
        if str(target_roster_id) != str(roster_id)
    ]

    if mode == "opponent_manager":
        if not opponent_roster_ids:
            raise ValueError("No opposing managers are available.")
        selection["target_roster_id"] = random.choice(opponent_roster_ids)
    elif mode == "opponent_managers":
        target_count = input_spec["count"]
        if len(opponent_roster_ids) < target_count:
            raise ValueError(
                f"Need {target_count} opposing managers, but only "
                f"{len(opponent_roster_ids)} are available."
            )
        selection["target_roster_ids"] = random.sample(
            opponent_roster_ids,
            target_count,
        )
    elif mode in {"bench_player", "starter_player", "recall_player"}:
        roster_players = _own_roster_players(
            league_id,
            roster_id,
            matchup_data_by_roster,
        )
        eligible_players = roster_players
        if mode == "bench_player":
            eligible_players = [
                player for player in roster_players
                if not player.get("is_starter")
            ]
        elif mode == "starter_player":
            eligible_players = [
                player for player in roster_players
                if player.get("is_starter")
            ]
        else:
            eligible_players = (
                [
                    player for player in roster_players
                    if player.get("is_starter")
                ]
                if week > 1
                else []
            )

        if not eligible_players:
            raise ValueError(f"No eligible roster players are available for {item_id}.")
        selection["player_id"] = str(random.choice(eligible_players)["id"])
    elif mode == "nfl_team":
        selection["team"] = random.choice(list(NFL_TEAM_NAMES))
    elif mode == "nfl_division":
        division = random.choice(list(NFL_DIVISION_TEAMS))
        selection["division"] = division
        selection["teams"] = list(NFL_DIVISION_TEAMS[division])
    elif mode == "position_choice":
        choice = random.choice(list(input_spec["choices"]))
        selection["choice"] = choice
        selection["position"] = input_spec["choices"][choice]
    elif mode == "nfl_player":
        eligible_player_ids = [
            str(player_id)
            for player_id, player in players_data.items()
            if player.get("team") in NFL_TEAM_NAMES
            and player.get("position")
        ]
        if not eligible_player_ids:
            raise ValueError("No eligible NFL players are available.")
        selection["player_id"] = random.choice(eligible_player_ids)
    elif mode == "free_text_player":
        eligible_names = [
            player.get("full_name")
            or f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
            for player in players_data.values()
            if player.get("team") in NFL_TEAM_NAMES
            and (
                player.get("full_name")
                or (player.get("first_name") and player.get("last_name"))
            )
        ]
        if not eligible_names:
            raise ValueError("No eligible NFL player names are available.")
        selection["player_name"] = random.choice(eligible_names)
    elif mode == "dream_lineup":
        league_info = sleeper_api.get_league_info(league_id)
        settings = league_info.get("settings") or {}
        roster_positions = (
            league_info.get("roster_positions")
            or settings.get("roster_positions")
            or []
        )
        lineup_slots = build_lineup_slots(roster_positions)
        if not lineup_slots:
            raise ValueError("The league starting lineup slots could not be loaded.")

        eligible_players = [
            {
                "player_id": str(player_id),
                "position": player.get("position"),
            }
            for player_id, player in players_data.items()
            if player.get("team") in NFL_TEAM_NAMES and player.get("position")
        ]
        def choose_lineup(
            slot_index: int,
            used_player_ids: set[str],
            lineup: list[dict],
        ) -> list[dict] | None:
            if slot_index == len(lineup_slots):
                return lineup

            slot = lineup_slots[slot_index]
            candidates = [
                player for player in eligible_players
                if player["player_id"] not in used_player_ids
                and player["position"] in slot["eligible_positions"]
            ]
            random.shuffle(candidates)
            for player in candidates:
                result = choose_lineup(
                    slot_index + 1,
                    used_player_ids | {player["player_id"]},
                    [
                        *lineup,
                        {
                            "slot": slot["slot"],
                            "player_id": player["player_id"],
                        },
                    ],
                )
                if result is not None:
                    return result
            return None

        selected_lineup = choose_lineup(0, set(), [])
        if selected_lineup is None:
            raise ValueError(
                "Could not build a complete lineup with eligible NFL players."
            )
        selection["lineup"] = selected_lineup
    elif mode == "player_trade":
        own_roster_players = _own_roster_players(
            league_id,
            roster_id,
            matchup_data_by_roster,
        )
        trade_targets = [
            {
                "player_id": str(player_id),
                "roster_id": target_roster_id,
            }
            for target_roster_id, matchup in matchup_data_by_roster.items()
            if str(target_roster_id) != str(roster_id)
            for player_id in matchup.get("players", [])
        ]
        if not own_roster_players or not trade_targets:
            raise ValueError(
                "A trade requires at least one player on your roster and one "
                "opposing roster."
            )
        selection["target"] = random.choice(trade_targets)
        selection["offered_player_id"] = str(
            random.choice(own_roster_players)["id"]
        )
    elif mode != "none":
        raise ValueError(f"Unsupported item selection mode: {mode}.")

    return selection


def describe_item_selection(
    selection: dict,
    roster_map: dict,
    players_data: dict,
) -> list[str]:
    """Format a stored structured selection for weekly standings cards."""
    mode = selection.get("mode")

    def player_name(player_id: str) -> str:
        player_id = str(player_id)
        return _player_name(player_id, players_data.get(player_id, {}))

    def manager_name(roster_id: int | str) -> str:
        return next(
            (
                name for key, name in roster_map.items()
                if str(key) == str(roster_id)
            ),
            f"Roster {roster_id}",
        )

    if mode == "opponent_manager":
        return [f"Target: {manager_name(selection.get('target_roster_id'))}"]
    if mode == "opponent_managers":
        targets = selection.get("target_roster_ids") or []
        return ["Targets: " + ", ".join(manager_name(target) for target in targets)]
    if mode in {"bench_player", "starter_player", "recall_player", "nfl_player"}:
        selected_player = selection.get("player_id")
        return [f"Player: {player_name(selected_player)}"] if selected_player else []
    if mode == "nfl_team":
        team = selection.get("team")
        return [f"Team: {NFL_TEAM_NAMES.get(team, team)}"] if team else []
    if mode == "nfl_division":
        division = selection.get("division")
        return [f"Division: {division}"] if division else []
    if mode == "position_choice":
        choice = selection.get("choice")
        return [f"Choice: {choice}"] if choice else []
    if mode == "free_text_player":
        name = selection.get("player_name")
        return [f"Player: {name}"] if name else []
    if mode == "dream_lineup":
        return [
            f"{slot.get('slot')}: {player_name(slot.get('player_id'))}"
            for slot in selection.get("lineup", [])
        ]
    if mode == "player_trade":
        target = selection.get("target") or {}
        offered_player_id = selection.get("offered_player_id")
        details = []
        if target.get("player_id"):
            target_manager = manager_name(target.get("roster_id"))
            details.append(
                f"Receive: {player_name(target['player_id'])} ({target_manager})"
            )
        if offered_player_id:
            details.append(f"Trade away: {player_name(offered_player_id)}")
        return details
    return []


def render_item_selection_form(
    item_id: str,
    league_id: str,
    week: int,
    user_roster_id: int,
    roster_map: dict,
    matchup_data_by_roster: dict,
    players_data: dict,
    form_key: str,
    allow_lock_in: bool = True,
) -> tuple[dict, str] | None:
    """Render one item form and return a validated selection and requested action."""
    input_spec = ITEM_INPUTS.get(item_id)
    if input_spec is None:
        st.error(f"No input mapping is defined for {item_id}.")
        return None

    mode = input_spec["mode"]
    user_roster_players = []
    if mode in {"bench_player", "recall_player", "starter_player", "player_trade"}:
        user_roster_players = _own_roster_players(
            league_id,
            user_roster_id,
            matchup_data_by_roster,
        )

    opponent_options = {
        f"{team_name} · {roster_id}": roster_id
        for roster_id, team_name in roster_map.items()
        if str(roster_id) != str(user_roster_id)
    }

    nfl_player_options = {
        _player_label(str(player_id), player): {
            "player_id": str(player_id),
            "position": player.get("position"),
        }
        for player_id, player in players_data.items()
        if player.get("team") in NFL_TEAM_NAMES and player.get("position")
    }

    recall_options = {}
    if mode == "recall_player" and week > 1:
        recall_options = {
            _player_label(str(player["id"]), player): str(player["id"])
            for player in user_roster_players
            if player.get("is_starter")
        }

    trade_target_options = {}
    if mode == "player_trade":
        for target_roster_id, matchup in matchup_data_by_roster.items():
            if str(target_roster_id) == str(user_roster_id):
                continue
            manager_name = next(
                (
                    name for roster_id, name in roster_map.items()
                    if str(roster_id) == str(target_roster_id)
                ),
                f"Roster {target_roster_id}",
            )
            for player_id in matchup.get("players", []):
                player_id = str(player_id)
                player = players_data.get(player_id, {})
                label = (
                    f"{_player_name(player_id, player)} · "
                    f"{player.get('position', 'N/A')} · "
                    f"{player.get('team') or 'FA'} · {manager_name} · {player_id}"
                )
                trade_target_options[label] = {
                    "player_id": player_id,
                    "roster_id": target_roster_id,
                }

    lineup_slots = []
    if mode == "dream_lineup":
        try:
            league_info = sleeper_api.get_league_info(league_id)
            settings = league_info.get("settings") or {}
            roster_positions = (
                league_info.get("roster_positions")
                or settings.get("roster_positions")
                or []
            )
            lineup_slots = build_lineup_slots(roster_positions)
        except Exception:
            lineup_slots = []

    selection = {"mode": mode}
    with st.form(form_key):
        selected_lineup = None

        if mode == "opponent_manager":
            selected_manager = st.selectbox(
                "Select opposing manager",
                list(opponent_options),
                index=None,
                key=f"{form_key}_opponent",
            )
            if selected_manager:
                selection["target_roster_id"] = opponent_options[selected_manager]

        elif mode == "opponent_managers":
            selected_managers = st.multiselect(
                f"Select {input_spec['count']} distinct opposing managers",
                list(opponent_options),
                max_selections=input_spec["count"],
                key=f"{form_key}_opponents",
            )
            selection["target_roster_ids"] = [
                opponent_options[label] for label in selected_managers
            ]

        elif mode in {"bench_player", "starter_player"}:
            eligible_players = [
                player for player in user_roster_players
                if bool(player.get("is_starter")) == (mode == "starter_player")
            ]
            player_options = {
                _player_label(str(player["id"]), player): str(player["id"])
                for player in eligible_players
            }
            selected_player = st.selectbox(
                "Select a bench player" if mode == "bench_player" else "Select a current starter",
                list(player_options),
                index=None,
                key=f"{form_key}_player",
            )
            if selected_player:
                selection["player_id"] = player_options[selected_player]

        elif mode == "recall_player":
            if week <= 1:
                st.warning("Recall is unavailable in Week 1.")
            selected_player = st.selectbox(
                "Select one of your current starters",
                list(recall_options),
                index=None,
                key=f"{form_key}_recall_player",
            )
            if selected_player:
                selection["player_id"] = recall_options[selected_player]

        elif mode == "nfl_team":
            team_options = {
                f"{name} ({team})": team
                for team, name in NFL_TEAM_NAMES.items()
            }
            selected_team = st.selectbox(
                "Select an NFL team",
                list(team_options),
                index=None,
                key=f"{form_key}_team",
            )
            if selected_team:
                selection["team"] = team_options[selected_team]

        elif mode == "nfl_division":
            selected_division = st.selectbox(
                "Select an NFL division",
                list(NFL_DIVISION_TEAMS),
                index=None,
                key=f"{form_key}_division",
            )
            if selected_division:
                selection["division"] = selected_division
                selection["teams"] = list(NFL_DIVISION_TEAMS[selected_division])

        elif mode == "position_choice":
            choices = input_spec["choices"]
            selected_choice = st.radio(
                "Choose your item effect",
                list(choices),
                key=f"{form_key}_position",
            )
            selection["position"] = choices[selected_choice]
            selection["choice"] = selected_choice

        elif mode == "nfl_player":
            selected_player = st.selectbox(
                "Select any NFL player",
                list(nfl_player_options),
                index=None,
                key=f"{form_key}_nfl_player",
            )
            if selected_player:
                selection["player_id"] = nfl_player_options[selected_player]["player_id"]

        elif mode == "free_text_player":
            player_name = st.text_input(
                "Enter any player name",
                key=f"{form_key}_free_text_player",
            ).strip()
            if player_name:
                selection["player_name"] = player_name

        elif mode == "dream_lineup":
            if lineup_slots and nfl_player_options:
                lineup_frame = pd.DataFrame([
                    {"Slot": slot["slot"], "Player": ""}
                    for slot in lineup_slots
                ])
                selected_lineup = st.data_editor(
                    lineup_frame,
                    column_config={
                        "Slot": st.column_config.TextColumn("Slot"),
                        "Player": st.column_config.SelectboxColumn(
                            "Player",
                            options=[""] + list(nfl_player_options),
                        ),
                    },
                    disabled=["Slot"],
                    hide_index=True,
                    num_rows="fixed",
                    key=f"{form_key}_lineup",
                )
            else:
                st.warning("Could not load this league’s starting lineup slots or NFL players.")

        elif mode == "player_trade":
            selected_target = st.selectbox(
                "Select an opposing player to receive",
                list(trade_target_options),
                index=None,
                key=f"{form_key}_trade_target",
            )
            selected_offer = st.selectbox(
                "Select your player to trade (bench allowed)",
                [
                    _player_label(str(player["id"]), player)
                    for player in user_roster_players
                ],
                index=None,
                key=f"{form_key}_trade_offer",
            )
            if selected_target:
                selection["target"] = trade_target_options[selected_target]
            if selected_offer:
                selection["offered_player_id"] = next(
                    str(player["id"])
                    for player in user_roster_players
                    if _player_label(str(player["id"]), player) == selected_offer
                )

        test_col, lock_col = st.columns(2)
        with test_col:
            test_submitted = st.form_submit_button("Test")
        with lock_col:
            lock_in_submitted = st.form_submit_button(
                "Lock in",
                disabled=not allow_lock_in,
            )

    if not test_submitted and not lock_in_submitted:
        return None

    if mode in {"opponent_manager", "bench_player", "starter_player", "recall_player", "nfl_team", "nfl_division", "nfl_player"}:
        required_key = "target_roster_id" if mode == "opponent_manager" else (
            "team" if mode == "nfl_team" else (
                "division" if mode == "nfl_division" else "player_id"
            )
        )
        if required_key not in selection:
            st.error("Make a selection before submitting.")
            return None

    elif mode == "opponent_managers":
        if len(selection["target_roster_ids"]) != input_spec["count"]:
            st.error(f"Select exactly {input_spec['count']} different managers.")
            return None

    elif mode == "position_choice" and "position" not in selection:
        st.error("Choose a position before submitting.")
        return None

    elif mode == "free_text_player" and "player_name" not in selection:
        st.error("Enter a player name before submitting.")
        return None

    elif mode == "dream_lineup":
        if selected_lineup is None:
            st.error("The league starting lineup could not be loaded.")
            return None

        used_player_ids = set()
        lineup = []
        for slot, row in zip(lineup_slots, selected_lineup.to_dict("records")):
            player = nfl_player_options.get(row.get("Player", ""))
            if player is None:
                st.error(f"Select a player for {slot['slot']}.")
                return None
            if player["player_id"] in used_player_ids:
                st.error("Each player can only be selected once in the lineup.")
                return None
            if player["position"] not in slot["eligible_positions"]:
                st.error(
                    f"{_player_name(player['player_id'], players_data[player['player_id']])} "
                    f"is not eligible for {slot['slot']}."
                )
                return None
            used_player_ids.add(player["player_id"])
            lineup.append({"slot": slot["slot"], "player_id": player["player_id"]})
        selection["lineup"] = lineup

    elif mode == "player_trade":
        if "target" not in selection or "offered_player_id" not in selection:
            st.error("Choose an opposing player and one of your players to trade.")
            return None

    return selection, "test" if test_submitted else "lock_in"