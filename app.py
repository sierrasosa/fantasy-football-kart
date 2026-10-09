from helpers import sleeper_api
from game_logic import scoring, item_service
from game_logic.item_form import (
    assign_starter_slots,
    build_random_item_selection,
    describe_item_selection,
    render_item_selection_form,
)
from game_logic.modifier_logic import (
    build_weekly_nfl_team_effects,
    build_weekly_player_modifiers,
)
from game_logic.timing_logic import (
    get_revealed_item_plays,
    get_current_nfl_context,
    resolve_weekly_timing_context,
)
from game_logic.item_inputs import NFL_TEAM_NAMES, format_nfl_division
import streamlit as st
import extra_streamlit_components as stx
import pandas as pd
import os
import json
from datetime import datetime
from pathlib import Path
from postgrest.exceptions import APIError
from supabase import Client, create_client
from database.auth_service import (
    create_login_session,
    get_login_session,
    pin_is_rate_limited,
    record_failed_pin,
    revoke_login_session,
    update_login_session_league,
    verify_pin,
)
from database.league_service import (
    get_commissioner_leagues,
    get_user_rosters,
    find_commissioner_leagues,
    initialize_commissioner_league,
)
from database.player_score_service import (
    load_player_score_inputs,
    save_player_score_input,
    scores_by_week,
)
from game_logic.player_scores import normalize_player_name

# -----------------------------------------------------------------------------
# 1. Page Configuration & Supabase Initialization
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Fantasy Football Kart 🏎️", page_icon="🏎️", layout="wide"
)


@st.cache_resource
def init_supabase() -> Client:
    """Initialize a server-side client for Streamlit backend operations."""
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


supabase = init_supabase()


@st.fragment
def get_cookie_manager():
    return stx.CookieManager(key="ffkart_cookie_manager")


cookie_manager = get_cookie_manager()
AUTH_COOKIE_NAME = "ffkart_auth_v1"
ITEM_IMAGE_FILES = {
    "SHELL": "green_shell.png",
    "TRIPLE_SHELL": "triple_green_shell.png",
    "COIN": "coin.png",
    "MUSHROOM": "mushroom.png",
    "NFL_TEAM_BYE": "bye.png",
    "NFL_DIVISION_BYE": "bye.png",
    "NFL_TEAM_SUPERCHARGE": "supercharge.png",
    "NFL_DIVISION_SUPERCHARGE": "supercharge.png",
    "SNOW_GAME_DOME_GAME": "dome.png",
    "HYPERFLEX": "flex.png",
    "ULTRAFLEX": "flex.png",
    "RECALL": "recall.png",
    "GOLDEN_MUSHROOM": "golden_mushroom.png",
    "SUPERSTAR": "superstar.png",
    "BULLET_BILL": "bullet_bill.png",
    "SMASH_BALL": "smash_ball.png",
    "MASTER_BALL": "masterball.png",
}
INJURY_STATUS_ICONS = {
    "ACTIVE": "✅",
    "QUESTIONABLE": "❓",
    "DOUBTFUL": "⚠️",
    "OUT": "❌",
    "IR": "🏥",
    "PUP": "🩼",
    "SUS": "🟥",
    "INACTIVE": "⛔",
}


def get_item_image_path(item_id: object) -> Path:
    """Return item-specific artwork, falling back to the generic item box."""
    image_file = ITEM_IMAGE_FILES.get(str(item_id or "").upper())
    if image_file:
        image_path = PROJECT_ROOT / "assets" / image_file
        if image_path.is_file():
            return image_path
    return PROJECT_ROOT / "assets" / "item_box.png"


def format_injury_status(status: object) -> str:
    """Add a status icon while preserving the underlying injury designation."""
    status_text = str(status or "Active").strip()
    icon = INJURY_STATUS_ICONS.get(status_text.upper())
    return f"{icon} {status_text}" if icon else status_text


def make_roster_dataframe(
    roster_players: list[dict],
    modifiers_by_player: dict[str, str] | None = None,
    modified_points_by_player: dict[str, float | None] | None = None,
    starter_slots_by_player: dict[str, str] | None = None,
    effect_icons_by_player: dict[str, str] | None = None,
    show_injury_status_column: bool = True,
    show_inactive_status_icon: bool = False,
) -> pd.DataFrame:
    """Build a consistently sorted roster table with weekly points and injuries."""
    modifiers_by_player = modifiers_by_player or {}
    modified_points_by_player = modified_points_by_player or {}
    starter_slots_by_player = starter_slots_by_player or {}
    effect_icons_by_player = effect_icons_by_player or {}
    rows = []
    for player in roster_players:
        player_id = str(player.get("id"))
        source_player_id = str(
            player.get("source_player_id") or player_id
        )
        player_name = str(player.get("name") or "Unknown")
        effect_icons = effect_icons_by_player.get(source_player_id, "")
        injury_status = str(player.get("injury_status") or "Active").strip()
        injury_icon = INJURY_STATUS_ICONS.get(injury_status.upper(), "")
        name_status_icon = (
            injury_icon
            if show_inactive_status_icon
            and injury_status.casefold() != "active"
            else ""
        )
        player_icons = " ".join(
            icon for icon in (name_status_icon, effect_icons) if icon
        )
        modifier = modifiers_by_player.get(source_player_id, "")
        if player.get("is_bullet_bill_copy"):
            modifier_parts = [
                part.strip()
                for part in modifier.split("·")
                if part.strip() != "10x"
            ]
            modifier = " · ".join(modifier_parts)
        is_active = (
            player.get("is_starter")
            or player.get("is_item_active")
            or "+ACTIVE" in modifier
        )
        modified_points = modified_points_by_player.get(
            player_id,
            modified_points_by_player.get(
                source_player_id,
                player.get("points"),
            ),
        )
        rows.append({
            "Player ID": player_id,
            "Player": f"{player_name} {player_icons}".rstrip(),
            "Pos": (
                (
                    f"🏈 {starter_slots_by_player[player_id]} · "
                    f"{player.get('pos', 'N/A')}"
                    if player.get("is_starter")
                    and player_id in starter_slots_by_player
                    else (
                        f"{'🏈' if is_active else '🪑'} "
                        f"{player.get('pos', 'N/A')}"
                    )
                )
            ),
            "Team": player.get("team", "FA"),
            "Points": player.get("points"),
            "Modifier": modifier or "—",
            "After Modifiers": (
                round(modified_points, 2)
                if isinstance(modified_points, (int, float))
                else None
            ),
        })
        if show_injury_status_column:
            rows[-1]["Injury Status"] = format_injury_status(injury_status)
    roster_df = pd.DataFrame(rows)
    if not roster_df.empty:
        position_order = ["QB", "RB", "WR", "TE", "K", "DEF", "FLEX", "BN"]
        lineup_slot_order = {
            "QB": 0,
            "RB": 1,
            "WR": 2,
            "TE": 3,
            "FLEX": 4,
            "REC_FLEX": 4,
            "WRRB_FLEX": 4,
            "SUPER_FLEX": 4,
            "IDP_FLEX": 4,
            "K": 5,
            "DEF": 6,
        }
        sort_roles = []
        sort_positions = []
        sort_slot_numbers = []
        for player in roster_players:
            player_id = str(player.get("id"))
            slot_label = starter_slots_by_player.get(player_id)
            if player.get("is_starter") and slot_label:
                slot_parts = slot_label.split()
                slot_type = slot_parts[0]
                sort_roles.append(0)
                sort_positions.append(
                    lineup_slot_order.get(slot_type, len(lineup_slot_order))
                )
                slot_number = (
                    int(slot_parts[1])
                    if len(slot_parts) > 1 and slot_parts[1].isdigit()
                    else 0
                )
                sort_slot_numbers.append(slot_number)
            elif player.get("is_starter"):
                sort_roles.append(0)
                sort_positions.append(
                    len(lineup_slot_order)
                    + position_order.index(player.get("pos"))
                    if player.get("pos") in position_order
                    else len(lineup_slot_order) + len(position_order)
                )
                sort_slot_numbers.append(0)
            elif player.get("is_item_active"):
                sort_roles.append(1)
                sort_positions.append(
                    position_order.index(player.get("pos"))
                    if player.get("pos") in position_order
                    else len(position_order)
                )
                sort_slot_numbers.append(0)
            else:
                sort_roles.append(2)
                sort_positions.append(
                    position_order.index(player.get("pos"))
                    if player.get("pos") in position_order
                    else len(position_order)
                )
                sort_slot_numbers.append(0)
        roster_df["sort_role"] = sort_roles
        roster_df["sort_pos"] = sort_positions
        roster_df["sort_slot_number"] = sort_slot_numbers
        roster_df = roster_df.sort_values(
            by=["sort_role", "sort_pos", "sort_slot_number", "Player"],
            ascending=[True, True, True, True],
        ).drop(
            columns=[
                "Player ID",
                "sort_pos",
                "sort_role",
                "sort_slot_number",
            ]
        )
    else:
        roster_df = roster_df.drop(columns=["Player ID"])
    return roster_df


def include_flex_item_players(
    roster_players: list[dict],
    roster_plays: list[dict],
    players_data: dict,
    matchup_data_by_roster: dict,
) -> list[dict]:
    """Build the displayed roster for revealed item-added players."""
    roster_players = list(roster_players)
    flex_item_positions = {"HYPERFLEX": "HF", "ULTRAFLEX": "UF"}
    matchup_player_points = {}
    for matchup in matchup_data_by_roster.values():
        player_points = matchup.get("players_points") or {}
        if isinstance(player_points, dict):
            matchup_player_points.update({
                str(player_id): points
                for player_id, points in player_points.items()
            })

    for play in roster_plays:
        item_id = str(play.get("item_id") or "").upper()
        if item_id == "BULLET_BILL":
            selection = _commissioner_selection(play)
            player_id = str(
                selection.get("player_id")
                or play.get("target_player_id")
                or ""
            ).strip()
            player = players_data.get(player_id)
            if not player:
                player = next(
                    (
                        roster_player
                        for roster_player in roster_players
                        if str(roster_player.get("id")) == player_id
                    ),
                    None,
                )
            if not player:
                continue

            name = (
                player.get("full_name")
                or player.get("name")
                or f"{player.get('first_name', '')} "
                f"{player.get('last_name', '')}".strip()
                or f"Player {player_id}"
            )
            position = (
                player.get("position")
                or player.get("pos")
                or "N/A"
            )
            team = player.get("team") or "FA"
            years_exp = player.get("years_exp", 0)
            points = matchup_player_points.get(player_id)
            if points is None:
                points = next(
                    (
                        roster_player.get("points")
                        for roster_player in roster_players
                        if str(roster_player.get("id")) == player_id
                    ),
                    None,
                )
            return [
                {
                    "id": f"{player_id}:bullet-bill:{copy_number}",
                    "source_player_id": player_id,
                    "name": name,
                    "pos": position,
                    "team": team,
                    "years_exp": years_exp,
                    "is_starter": True,
                    "is_bullet_bill_copy": True,
                    "points": points,
                    "injury_status": player.get("injury_status") or "Active",
                }
                for copy_number in range(1, 11)
            ]

        if item_id not in {"MUSHROOM", "HYPERFLEX", "ULTRAFLEX"}:
            continue

        selection = _commissioner_selection(play)
        player_id = str(
            selection.get("player_id") or play.get("target_player_id") or ""
        ).strip()
        player_name = str(selection.get("player_name") or "").strip()
        if not player_id and item_id == "ULTRAFLEX" and player_name:
            normalized_name = normalize_player_name(player_name)
            matches = [
                str(candidate_id)
                for candidate_id, player in players_data.items()
                if normalized_name
                in {
                    normalize_player_name(str(player.get("full_name") or "")),
                    normalize_player_name(
                        f"{player.get('first_name', '')} "
                        f"{player.get('last_name', '')}"
                    ),
                }
            ]
            if len(matches) == 1:
                player_id = matches[0]

        if not player_id:
            continue

        existing_player = next(
            (
                roster_player
                for roster_player in roster_players
                if str(roster_player.get("id")) == player_id
            ),
            None,
        )
        if existing_player:
            existing_player["is_item_active"] = True
            continue

        player = players_data.get(player_id)
        if not player:
            continue
        name = (
            player.get("full_name")
            or f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
            or player_name
            or f"Player {player_id}"
        )
        position = str(
            player.get("position") or player.get("pos") or ""
        ).strip()
        if not position or position.upper() == "N/A":
            position = flex_item_positions.get(item_id, "N/A")
        roster_players.append({
            "id": player_id,
            "name": name,
            "pos": position,
            "team": player.get("team") or "FA",
            "years_exp": player.get("years_exp", 0),
            "is_starter": False,
            "is_item_active": True,
            "points": matchup_player_points.get(player_id),
            "injury_status": player.get("injury_status") or "Active",
        })

    return roster_players


def _commissioner_selection(play: dict) -> dict:
    selection = play.get("selection")
    if isinstance(selection, str):
        try:
            selection = json.loads(selection)
        except json.JSONDecodeError:
            selection = {}
    if isinstance(selection, dict) and selection:
        return selection

    custom_target = play.get("custom_target")
    if isinstance(custom_target, str) and custom_target.lstrip().startswith("{"):
        try:
            selection = json.loads(custom_target)
        except json.JSONDecodeError:
            return {}
        return selection if isinstance(selection, dict) else {}
    return {}


def _commissioner_item_summary(
    team_name: str,
    item_name: str,
    play: dict,
    roster_map: dict,
    players_data: dict,
    item_description: str = "",
) -> str:
    item_id = str(play.get("item_id") or "").upper()
    selection = _commissioner_selection(play)

    def selected_player_name(player_id: object) -> str:
        player = players_data.get(str(player_id), {})
        return (
            player.get("full_name")
            or f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
            or f"Player {player_id}"
        )

    if item_id == "COIN":
        detail = item_description.strip() or "They get their FAAB bonus this week."
        return f"{team_name} got {item_name}! {detail}"
    if item_id == "MUSHROOM":
        player_id = selection.get("player_id") or play.get("target_player_id")
        detail = (
            f"They are adding {selected_player_name(player_id)} from their "
            "bench this week."
            if player_id
            else "They are adding a player from their bench this week."
        )
    elif item_id == "GOLDEN_MUSHROOM":
        detail = "They are adding their bench players this week."
    elif item_id in {"NFL_TEAM_BYE", "NFL_TEAM_SUPERCHARGE"}:
        team_code = selection.get("team") or play.get("target_nfl_team")
        nfl_team = NFL_TEAM_NAMES.get(str(team_code), str(team_code or "the selected team"))
        verb = "are on bye" if item_id == "NFL_TEAM_BYE" else "are supercharged"
        detail = f"The {nfl_team} {verb} this week!"
    elif item_id in {"NFL_DIVISION_BYE", "NFL_DIVISION_SUPERCHARGE"}:
        division = format_nfl_division(
            selection.get("division") or "selected division"
        )
        verb = "are on bye" if item_id == "NFL_DIVISION_BYE" else "are supercharged"
        detail = f"The teams in the {division} {verb} this week!"
    elif item_id == "SNOW_GAME_DOME_GAME":
        choice = selection.get("choice")
        if not choice:
            position = str(selection.get("position") or "").upper()
            choice = {"WR": "Snow Game", "RB": "Dome Game"}.get(position, "selected effect")
        detail = f"They chose {choice} this week."
    elif item_id == "RECALL":
        player_id = selection.get("player_id") or play.get("target_player_id")
        detail = (
            f"They are replaying {selected_player_name(player_id)}'s score "
            "from last week."
            if player_id
            else "They selected a player to replay last week's score."
        )
    elif item_id == "HYPERFLEX":
        player_id = selection.get("player_id") or play.get("target_player_id")
        detail = (
            f"They are adding {selected_player_name(player_id)} to their "
            "lineup this week."
            if player_id
            else "They are adding a player to their lineup this week."
        )
    elif item_id == "ULTRAFLEX":
        player_name = str(selection.get("player_name") or "").strip()
        detail = (
            f"They selected {player_name} for Ultraflex."
            if player_name
            else "Their Ultraflex selection needs review."
        )
    elif item_id == "SUPERSTAR":
        player_id = selection.get("player_id") or play.get("target_player_id")
        detail = (
            f"{selected_player_name(player_id)} is their Superstar this week."
            if player_id
            else "They selected a Superstar."
        )
    elif item_id == "BULLET_BILL":
        player_id = selection.get("player_id") or play.get("target_player_id")
        detail = (
            f"{selected_player_name(player_id)} is their Bullet Bill player "
            "this week."
            if player_id
            else "They selected a Bullet Bill player."
        )
    elif item_id == "SMASH_BALL":
        lineup = selection.get("lineup") or []
        selected_players = [
            f"{slot.get('slot')}: {selected_player_name(slot['player_id'])}"
            for slot in lineup
            if slot.get("player_id")
        ]
        detail = (
            "Their dream lineup is " + ", ".join(selected_players) + "."
            if selected_players
            else "Their Smash Ball dream lineup needs review."
        )
    elif item_id == "MASTER_BALL":
        selection_details = describe_item_selection(
            selection,
            roster_map,
            players_data,
        )
        detail = (
            "Their Master Ball trade: " + "; ".join(selection_details) + "."
            if selection_details
            else "Their Master Ball trade needs review."
        )
    elif item_id in {"SHELL", "TRIPLE_SHELL"}:
        selection_details = describe_item_selection(
            selection,
            roster_map,
            players_data,
        )
        detail = (
            "They targeted " + "; ".join(selection_details) + "."
            if selection_details
            else "Their shell target needs review."
        )
    else:
        selection_details = describe_item_selection(
            selection,
            roster_map,
            players_data,
        )
        detail = "; ".join(selection_details) or "No selection details recorded."

    return f"{team_name} got {item_name}! {detail}"


def save_item_play(
    item_record: dict,
    selection: dict,
    league_id: str,
    week: int,
    roster_id: int,
) -> None:
    """Persist an item selection and mark the inventory item as used."""
    selection = dict(selection)
    item_id = str(item_record.get("item_id") or "").upper()
    if item_id == "NFL_DIVISION_BYE":
        existing_division_bye = (
            supabase.table("weekly_plays")
            .select("id")
            .eq("league_id", league_id)
            .eq("week", week)
            .eq("item_id", "NFL_DIVISION_BYE")
            .limit(1)
            .execute()
        )
        if existing_division_bye.data:
            raise ValueError(
                f"Only one NFL Division Bye can be locked in for Week {week}."
            )

    if item_id == "COIN":
        selection = item_service.ensure_coin_faab_amount(selection)

    mode = selection.get("mode")
    target = selection.get("target") or {}
    target_player_id = selection.get("player_id") or target.get("player_id")
    target_nfl_team = selection.get("team")
    custom_target = selection.get("player_name") or selection.get("choice")
    if mode != "none" or item_id == "COIN":
        custom_target = json.dumps(selection)

    play_record = {
        "league_id": league_id,
        "week": week,
        "roster_id": roster_id,
        "item_id": item_record.get("item_id"),
        "target_player_id": target_player_id,
        "target_nfl_team": target_nfl_team,
        "custom_target": custom_target,
        "selection": selection,
    }
    try:
        supabase.table("weekly_plays").insert(play_record).execute()
    except APIError as exc:
        if (
            getattr(exc, "code", None) != "PGRST204"
            or "selection" not in str(exc).casefold()
        ):
            raise
        play_record.pop("selection")
        supabase.table("weekly_plays").insert(play_record).execute()

    supabase.table("team_inventory").update({"is_used": True}).eq(
        "id", item_record.get("id")
    ).eq("league_id", league_id).execute()


def auto_select_expired_item_plays(
    item_week: int,
    league_id: str,
    deadline_passed: bool,
    roster_map: dict,
    matchup_data_by_roster: dict,
    players_data: dict,
) -> None:
    """Randomly lock in any unused inventory items after the weekly deadline."""
    if not deadline_passed:
        return

    try:
        inventory_res = (
            supabase.table("team_inventory")
            .select("id, roster_id, item_id, is_used")
            .eq("league_id", league_id)
            .eq("week", item_week)
            .execute()
        )
        plays_res = (
            supabase.table("weekly_plays")
            .select("roster_id, item_id")
            .eq("league_id", league_id)
            .eq("week", item_week)
            .execute()
        )
    except APIError as exc:
        st.sidebar.error(
            f"Could not load items for automatic post-deadline selection: {exc}"
        )
        return

    existing_plays = {
        (str(play.get("roster_id")), str(play.get("item_id")))
        for play in plays_res.data or []
    }
    auto_selected_count = 0
    inventory_repaired = False
    for item_record in inventory_res.data or []:
        roster_id = item_record.get("roster_id")
        item_id = item_record.get("item_id")
        play_key = (str(roster_id), str(item_id))
        if item_record.get("is_used"):
            continue

        if play_key in existing_plays:
            try:
                supabase.table("team_inventory").update(
                    {"is_used": True}
                ).eq("id", item_record.get("id")).eq(
                    "league_id", league_id
                ).execute()
                inventory_repaired = True
            except APIError as exc:
                st.sidebar.error(
                    f"Found an existing play for roster {roster_id}, but "
                    f"could not mark its item used: {exc}"
                )
            continue

        if not item_id or roster_id is None:
            st.sidebar.error(
                "Could not auto-select an item with a missing item or roster ID."
            )
            continue

        try:
            selection = build_random_item_selection(
                str(item_id),
                league_id,
                item_week,
                int(roster_id),
                roster_map,
                matchup_data_by_roster,
                players_data,
            )
        except (ValueError, KeyError) as exc:
            st.sidebar.error(
                f"Could not auto-select {item_id} for roster {roster_id}: {exc}"
            )
            continue
        except Exception as exc:
            st.sidebar.error(
                f"Could not build an automatic selection for {item_id} "
                f"(roster {roster_id}): {exc}"
            )
            continue

        selection["auto_selected"] = True
        try:
            save_item_play(
                item_record,
                selection,
                league_id,
                item_week,
                int(roster_id),
            )
        except APIError as exc:
            st.sidebar.error(
                f"Could not save the automatic selection for {item_id} "
                f"(roster {roster_id}): {exc}"
            )
            continue
        except ValueError as exc:
            st.sidebar.warning(str(exc))
            continue

        existing_plays.add(play_key)
        auto_selected_count += 1

    if auto_selected_count or inventory_repaired:
        st.rerun()


PROJECT_ROOT = Path(__file__).resolve().parent


# -----------------------------------------------------------------------------
# 2. Session State Initialization
# -----------------------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "roster_id" not in st.session_state:
    st.session_state["roster_id"] = None
if "team_name" not in st.session_state:
    st.session_state["team_name"] = None
if "is_commissioner" not in st.session_state:
    st.session_state["is_commissioner"] = False
if "user_id" not in st.session_state:
    st.session_state["user_id"] = None
if "active_league_id" not in st.session_state:
    st.session_state["active_league_id"] = None
if "login_rosters" not in st.session_state:
    st.session_state["login_rosters"] = []
if "setup_leagues" not in st.session_state:
    st.session_state["setup_leagues"] = []
if "setup_account" not in st.session_state:
    st.session_state["setup_account"] = None
if "setup_is_commissioner" not in st.session_state:
    st.session_state["setup_is_commissioner"] = False
if "setup_lookup_failed" not in st.session_state:
    st.session_state["setup_lookup_failed"] = False
if "current_setup_season" not in st.session_state:
    st.session_state["current_setup_season"] = None
if "loaded_setup_season" not in st.session_state:
    st.session_state["loaded_setup_season"] = None
if "login_error" not in st.session_state:
    st.session_state["login_error"] = None
if "new_league_pins" not in st.session_state:
    st.session_state["new_league_pins"] = None
if "remember_token" not in st.session_state:
    st.session_state["remember_token"] = None
if "pending_login_cookie" not in st.session_state:
    st.session_state["pending_login_cookie"] = None
if "pending_cookie_delete" not in st.session_state:
    st.session_state["pending_cookie_delete"] = False

if st.session_state["pending_login_cookie"]:
    cookie_manager.set(
        AUTH_COOKIE_NAME,
        st.session_state["pending_login_cookie"],
        max_age=30 * 24 * 60 * 60,
        secure=True,
        same_site="lax",
        key="set_login_cookie",
    )
    st.session_state["pending_login_cookie"] = None

deleting_login_cookie = st.session_state["pending_cookie_delete"]
if deleting_login_cookie:
    cookie_manager.delete(AUTH_COOKIE_NAME, key="delete_login_cookie")
    st.session_state["pending_cookie_delete"] = False

if not st.session_state["authenticated"] and not deleting_login_cookie:
    browser_token = cookie_manager.get(AUTH_COOKIE_NAME)
    if browser_token:
        try:
            saved_session = get_login_session(supabase, browser_token)
            if saved_session:
                saved_rosters = get_user_rosters(
                    supabase, saved_session["user_id"]
                )
                saved_roster = next(
                    (
                        row for row in saved_rosters
                        if str(row.get("league_id")) == str(saved_session["league_id"])
                    ),
                    None,
                )
                if saved_roster:
                    st.session_state["authenticated"] = True
                    st.session_state["user_id"] = saved_session["user_id"]
                    st.session_state["active_league_id"] = saved_session["league_id"]
                    st.session_state["roster_id"] = saved_roster["roster_id"]
                    st.session_state["team_name"] = saved_roster["team_name"]
                    st.session_state["is_commissioner"] = bool(
                        saved_roster.get("commissioner")
                    )
                    st.session_state["remember_token"] = browser_token
                else:
                    revoke_login_session(supabase, browser_token)
                    cookie_manager.delete(AUTH_COOKIE_NAME, key="delete_invalid_login")
            else:
                cookie_manager.delete(AUTH_COOKIE_NAME, key="delete_expired_login")
        except Exception:
            st.session_state["login_error"] = "Could not restore your saved login. Please log in again."

# -----------------------------------------------------------------------------
# 3. Sidebar Authentication Engine
# -----------------------------------------------------------------------------
nfl_context = get_current_nfl_context()
current_display_week = min(
    max(int(nfl_context["display_week"]), 1),
    18,
)
st.sidebar.title("🏎️ Current Week Overview")
sidebar_event_area = st.sidebar.empty()
if not st.session_state["authenticated"]:
    st.sidebar.divider()


if not st.session_state["authenticated"]:
    st.sidebar.subheader("Manager Login")
    username = st.sidebar.text_input("Sleeper username", key="sleeper_username")

    if st.sidebar.button("Find account", key="find_sleeper_account"):
        st.session_state["login_error"] = None
        st.session_state["setup_account"] = None
        st.session_state["setup_is_commissioner"] = False
        st.session_state["setup_lookup_failed"] = False
        st.session_state["login_rosters"] = []
        st.session_state["setup_leagues"] = []
        st.session_state["current_setup_season"] = None
        st.session_state["loaded_setup_season"] = None
        account = sleeper_api.get_user(username.strip()) if username.strip() else {}
        account = account or {}
        user_id = account.get("user_id")
        if not user_id:
            st.session_state["setup_account"] = None
            st.session_state["setup_lookup_failed"] = False
            st.session_state["login_rosters"] = []
            st.session_state["setup_leagues"] = []
            st.session_state["current_setup_season"] = None
            st.session_state["loaded_setup_season"] = None
            st.sidebar.error("That username is not a Sleeper account.")
        else:
            st.session_state["setup_account"] = account
            try:
                st.session_state["login_rosters"] = get_user_rosters(
                    supabase, str(user_id), include_pin_hash=True
                )
                season = str((sleeper_api.get_nfl_state() or {}).get("season") or datetime.now().year)
                st.session_state["current_setup_season"] = season
                st.session_state["setup_season"] = season
                st.session_state["loaded_setup_season"] = season
                st.session_state["setup_leagues"] = get_commissioner_leagues(account, season)
                st.session_state["setup_is_commissioner"] = bool(
                    st.session_state["setup_leagues"]
                    or str(account.get("username", "")).casefold() == "sierrabellum"
                )
                if not st.session_state["setup_is_commissioner"]:
                    commissioner_season, commissioner_leagues = find_commissioner_leagues(
                        account, season
                    )
                    if commissioner_season:
                        st.session_state["setup_is_commissioner"] = True
                        st.session_state["setup_season"] = commissioner_season
                        st.session_state["loaded_setup_season"] = commissioner_season
                        st.session_state["setup_leagues"] = commissioner_leagues
                st.session_state["setup_lookup_failed"] = False
            except Exception as exc:
                st.session_state["setup_lookup_failed"] = True
                st.sidebar.error(f"Could not load Sleeper leagues or roster records: {exc}")
                st.session_state["login_rosters"] = []
                st.session_state["setup_leagues"] = []

    login_rosters = st.session_state["login_rosters"]
    if login_rosters:
        league_options = {
            f"{row.get('league_name', 'League')} · {row.get('team_name', 'Team')} · {row.get('season', 'Year unknown')}": row
            for row in login_rosters
        }
        selected_login_label = st.sidebar.selectbox("League / team", list(league_options))
        selected_login_roster = league_options[selected_login_label]
        login_user_id = str(selected_login_roster.get("user_id"))
        pin_locked = pin_is_rate_limited(supabase, login_user_id)
        if pin_locked:
            st.sidebar.error("Too many incorrect PIN attempts. Try again in 15 minutes.")
        if st.session_state["login_error"]:
            st.sidebar.error(st.session_state["login_error"])
        entered_pin = st.sidebar.text_input("PIN", type="password", key="login_pin")
        remember_browser = st.sidebar.checkbox(
            "Remember this browser for 30 days", value=True, key="remember_browser"
        )
        if st.sidebar.button("Log in", disabled=pin_locked):
            st.session_state["login_error"] = None
            if verify_pin(entered_pin, selected_login_roster.get("pin_hash", "")):
                st.session_state["authenticated"] = True
                st.session_state["user_id"] = selected_login_roster.get("user_id")
                st.session_state["roster_id"] = selected_login_roster.get("roster_id")
                st.session_state["team_name"] = selected_login_roster.get("team_name")
                st.session_state["is_commissioner"] = bool(
                    selected_login_roster.get("commissioner")
                )
                st.session_state["active_league_id"] = selected_login_roster.get("league_id")
                supabase.table("login_attempts").delete().eq("user_id", login_user_id).execute()
                if remember_browser:
                    try:
                        token, _expires_at = create_login_session(
                            supabase,
                            login_user_id,
                            str(selected_login_roster.get("league_id")),
                        )
                        st.session_state["remember_token"] = token
                        st.session_state["pending_login_cookie"] = token
                    except Exception:
                        st.sidebar.warning(
                            "Logged in for this session, but remember-browser login could not be saved. "
                            "Apply database/supabase_login_sessions.sql to enable it."
                        )
                else:
                    old_token = cookie_manager.get(AUTH_COOKIE_NAME)
                    revoke_login_session(supabase, old_token)
                    st.session_state["remember_token"] = None
                    st.session_state["pending_cookie_delete"] = True
                st.rerun()
            record_failed_pin(supabase, login_user_id)
            st.session_state["login_error"] = (
                "PIN not recognized. Request your PIN from your commissioner."
            )
            st.rerun()
    elif (
        st.session_state["setup_account"]
        and not st.session_state["setup_is_commissioner"]
        and not st.session_state["setup_lookup_failed"]
    ):
        st.sidebar.info(
            "Please contact your commissioner to initialize the league in this app."
        )
    elif st.session_state["setup_lookup_failed"]:
        st.sidebar.caption(
            "Sleeper lookup failed. Check your connection and click "
            "Find account to retry."
        )
    else:
        st.sidebar.caption("Enter your Sleeper username to find your leagues.")

    if st.session_state["setup_account"] and st.session_state["setup_is_commissioner"]:
        initialized_league_ids = {str(row.get("league_id")) for row in login_rosters}
        expander_title = "Initialize a league"
        with st.sidebar.expander(expander_title):
            current_season = str(
                st.session_state["current_setup_season"]
                or (sleeper_api.get_nfl_state() or {}).get("season")
                or datetime.now().year
            )
            season_options = [
                str(year) for year in range(int(current_season), 2021, -1)
            ]
            current_selection = st.session_state.get("setup_season", current_season)
            if current_selection not in season_options:
                current_selection = current_season
            selected_setup_season = st.selectbox(
                "Sleeper season",
                season_options,
                index=season_options.index(current_selection),
                key="setup_season",
            )
            if selected_setup_season != st.session_state["loaded_setup_season"]:
                try:
                    st.session_state["setup_leagues"] = get_commissioner_leagues(
                        st.session_state["setup_account"], selected_setup_season
                    )
                    st.session_state["loaded_setup_season"] = selected_setup_season
                except Exception as exc:
                    st.session_state["setup_leagues"] = []
                    st.error(f"Could not load Sleeper leagues for {selected_setup_season}: {exc}")

            available_leagues = [
                league for league in st.session_state["setup_leagues"]
                if str(league.get("league_id")) not in initialized_league_ids
            ]
            if available_leagues:
                setup_options = {
                    f"{league.get('name', 'Unnamed league')} · {league.get('season', '')} · {league.get('league_id')}": league
                    for league in available_leagues
                }
                selected_setup_label = st.selectbox(
                    "Commissioner league", list(setup_options), key="setup_league"
                )
                setup_code = st.text_input(
                    "League setup code", type="password", key="league_setup_code"
                )
                if st.button("Initialize league", key="initialize_commissioner_league"):
                    account = st.session_state["setup_account"]
                    league = setup_options[selected_setup_label]
                    try:
                        pin_setup = initialize_commissioner_league(
                            supabase,
                            account,
                            league,
                            setup_code,
                            st.secrets.get("LEAGUE_SETUP_CODE", ""),
                        )
                        st.session_state["new_league_pins"] = (
                            pin_setup if pin_setup["pins"] else None
                        )
                        st.session_state["login_rosters"] = get_user_rosters(
                            supabase,
                            str(account.get("user_id")),
                            include_pin_hash=True,
                        )
                        st.rerun()
                    except (ValueError, PermissionError) as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f"League initialization failed: {exc}")
            else:
                st.info(
                    f"No uninitialized commissioner leagues were found for {selected_setup_season}."
                )
else:
    user_rosters = get_user_rosters(supabase, str(st.session_state["user_id"]))
    if not user_rosters:
        st.session_state["authenticated"] = False
        st.rerun()
    active_league_options = {
        f"{row.get('league_name', row['league_id'])} · {row.get('team_name', 'Team')}": row
        for row in user_rosters
    }
    current_active_label = next(
        (
            label
            for label, row in active_league_options.items()
            if str(row.get("league_id"))
            == str(st.session_state["active_league_id"])
        ),
        next(iter(active_league_options)),
    )
    if st.session_state.get("active_league_selection") not in active_league_options:
        st.session_state["active_league_selection"] = current_active_label
    active_roster = active_league_options[
        st.session_state["active_league_selection"]
    ]
    st.session_state["active_league_id"] = active_roster.get("league_id")
    st.session_state["roster_id"] = active_roster.get("roster_id")
    st.session_state["team_name"] = active_roster.get("team_name")
    st.session_state["is_commissioner"] = bool(
        active_roster.get("commissioner")
    )
    update_login_session_league(
        supabase,
        st.session_state.get("remember_token"),
        str(active_roster.get("league_id")),
    )

if st.session_state["new_league_pins"]:
    pin_setup = st.session_state["new_league_pins"]
    st.warning("Share these one-time manager PINs with the matching league members, then dismiss this list.")
    st.subheader(f"PINs for {pin_setup['league_name']}")
    st.dataframe(
        pd.DataFrame(pin_setup["pins"]),
        hide_index=True,
        width="stretch",
    )
    if st.button("I have shared/saved these PINs"):
        st.session_state["new_league_pins"] = None
        st.rerun()

if not st.session_state["authenticated"]:
    st.info("Log in from the sidebar to view a league.")
    st.stop()

# Global League Week Selector
st.title("🏎️ Fantasy Football Kart")
default_week = current_display_week
selected_week = st.number_input(
    "NFL Week",
    min_value=1,
    max_value=18,
    value=default_week,
    step=1,
    key="selected_nfl_week",
)
selected_week_event_area = st.empty()
now = nfl_context["now"]
actual_weekday = nfl_context["weekday"]
actual_nfl_week = nfl_context["week"]
if "timing_test_week" not in st.session_state:
    st.session_state["timing_test_week"] = 1
if "timing_test_day" not in st.session_state:
    st.session_state["timing_test_day"] = 0
if "use_test_timing" not in st.session_state:
    st.session_state["use_test_timing"] = False
current_weekday = int(st.session_state["timing_test_day"])
current_nfl_week = int(st.session_state["timing_test_week"])
timing_context = resolve_weekly_timing_context(
    nfl_context,
    selected_week,
    st.session_state["use_test_timing"],
    current_weekday,
    current_nfl_week,
)
item_week = timing_context["item_week"]

# -----------------------------------------------------------------------------
# 4. Data Loading (Sleeper & Supabase)
# -----------------------------------------------------------------------------
league_id = str(st.session_state["active_league_id"])

with st.spinner("Loading NFL player database..."):
    players_data = sleeper_api.get_nfl_players() or {}

raw_matchups = sleeper_api.get_league_matchups(league_id, selected_week) or []
weekly_matchups_cache = {selected_week: raw_matchups}
try:
    league_info = sleeper_api.get_league_info(league_id) or {}
except Exception as exc:
    league_info = {}
    st.warning(f"Could not load lineup slots; showing player positions only: {exc}")
league_settings = league_info.get("settings") or {}
league_roster_positions = (
    league_info.get("roster_positions")
    or league_settings.get("roster_positions")
    or []
)


def get_week_matchups(week: int) -> list[dict]:
    if week not in weekly_matchups_cache:
        weekly_matchups_cache[week] = (
            sleeper_api.get_league_matchups(league_id, week) or []
        )
    return weekly_matchups_cache[week]


matchup_data_by_roster = {
    str(matchup.get("roster_id")): matchup
    for matchup in raw_matchups
    if matchup.get("roster_id") is not None
}

try:
    plays_res = (
        supabase.table("weekly_plays")
        .select("*")
        .eq("league_id", league_id)
        .eq("week", selected_week)
        .execute()
    )
    weekly_plays = plays_res.data or []
except Exception:
    weekly_plays = []
revealed_weekly_plays = get_revealed_item_plays(
    weekly_plays,
    timing_context,
)

try:
    inventory_res = (
        supabase.table("team_inventory")
        .select("roster_id, item_id, is_used, items(name)")
        .eq("league_id", league_id)
        .eq("week", selected_week)
        .execute()
    )
    weekly_inventory = inventory_res.data or []
except Exception:
    weekly_inventory = []

try:
    events_res = (
        supabase.table("league_events")
        .select("week, event_name, description")
        .eq("league_id", league_id)
        .lte(
            "week",
            max(selected_week, item_week - 1, current_display_week),
        )
        .execute()
    )
    weekly_events_by_week: dict[int, list[dict]] = {}
    for event in events_res.data or []:
        event_week = int(event["week"])
        weekly_events_by_week.setdefault(event_week, []).append(event)
    weekly_events = weekly_events_by_week.get(selected_week, [])
    current_week_events = weekly_events_by_week.get(current_display_week, [])
except Exception as exc:
    weekly_events_by_week = {}
    weekly_events = []
    current_week_events = []
    st.error(f"Could not load league events for scoring: {exc}")

try:
    items_res = supabase.table("items").select("id, name, description").execute()
    item_names = {
        str(item.get("id")): item.get("name")
        for item in (items_res.data or [])
    }
    item_descriptions = {
        str(item.get("id")): item.get("description") or ""
        for item in (items_res.data or [])
    }
except Exception:
    item_names = {}
    item_descriptions = {}

plays_by_roster = {}
for play in weekly_plays:
    plays_by_roster.setdefault(str(play.get("roster_id")), []).append(play)

revealed_plays_by_roster = {}
for play in revealed_weekly_plays:
    revealed_plays_by_roster.setdefault(
        str(play.get("roster_id")),
        [],
    ).append(play)

inventory_by_roster = {
    str(item.get("roster_id")): item
    for item in weekly_inventory
}

previous_week_matchups = (
    get_week_matchups(selected_week - 1)
    if selected_week > 1
    else []
)
fallback_score_error = None
try:
    fallback_player_points_by_week = scores_by_week(
        load_player_score_inputs(
            supabase,
            league_id,
            max(selected_week, item_week - 1),
        )
    )
except Exception as exc:
    fallback_player_points_by_week = {}
    fallback_score_error = exc

calculated_matchups = scoring.calculate_modified_scores(
    raw_matchups,
    revealed_weekly_plays,
    players_data,
    previous_week_matchups,
    fallback_player_points_by_week.get(selected_week, {}),
    fallback_player_points_by_week.get(selected_week - 1, {}),
    weekly_events,
) or []
calculated_matchups_by_roster = {
    str(team.get("roster_id")): team
    for team in calculated_matchups
}

# Build roster mapping from Supabase
roster_map: dict[int, str] = {}
try:
    r_data = (
        supabase.table("rosters")
        .select("roster_id, team_name")
        .eq("league_id", league_id)
        .execute()
        .data
        or []
    )
    for r in r_data:
        rid = r.get("roster_id")
        if rid is not None:
            roster_map[rid] = r.get("team_name", f"Team {rid}")
except Exception:
    pass

try:
    all_plays_res = (
        supabase.table("weekly_plays")
        .select("*")
        .eq("league_id", league_id)
        .lte(
            "week",
            max(selected_week, item_week - 1, current_display_week),
        )
        .execute()
    )
    all_plays = all_plays_res.data or []
    all_plays_error = None
except Exception as exc:
    all_plays = []
    all_plays_error = exc
revealed_all_plays = get_revealed_item_plays(all_plays, timing_context)

# Build avatar map dynamically using Sleeper API
avatar_map = {}
try:
    sleeper_rosters = sleeper_api.get_league_rosters(league_id) or []
    league_users_map = sleeper_api.get_league_users_avatar_map(league_id)
    
    for r in sleeper_rosters:
        r_id = r.get("roster_id")
        owner_id = str(r.get("owner_id")) if r.get("owner_id") else None
        
        # Match user from users payload
        if r_id and owner_id in league_users_map:
            avatar_map[r_id] = league_users_map[owner_id]["avatar_url"]
except Exception as e:
    st.error(f"Error fetching avatars: {e}")

modifier_plays = revealed_weekly_plays
item_preview = st.session_state.get("item_preview")
if item_preview:
    if (
        item_preview.get("league_id") == league_id
        and item_preview.get("week") == item_week
        and str(item_preview.get("roster_id"))
        == str(st.session_state["roster_id"])
    ):
        modifier_plays = [
            *revealed_weekly_plays,
            {
                "item_id": item_preview["item_id"],
                "roster_id": item_preview["roster_id"],
                "selection": item_preview["selection"],
            },
        ]
    else:
        st.session_state.pop("item_preview", None)

(
    player_database_modifiers,
    roster_player_modifiers,
    player_database_effect_icons,
    roster_player_effect_icons,
) = build_weekly_player_modifiers(
    players_data,
    modifier_plays,
    weekly_events,
    matchup_data_by_roster,
    roster_map,
)


# -----------------------------------------------------------------------------
# 5. Main UI Tabs
# -----------------------------------------------------------------------------
show_weekly_item_details = timing_context["show_weekly_item_details"]
nfl_team_effect_rows = build_weekly_nfl_team_effects(
    [
        play
        for play in revealed_all_plays
        if int(play.get("week") or 0) == current_display_week
    ]
)
with sidebar_event_area.container():
    for weekly_event in current_week_events:
        st.info(
            f"📢 **Week {current_display_week} Global Event: "
            f"{weekly_event.get('event_name', 'League Event')}**\n\n"
            f"{weekly_event.get('description', '')}"
        )
    st.info(timing_context["announcement"])

    st.subheader("NFL Teams with Item Effects")
    if nfl_team_effect_rows:
        st.dataframe(
            pd.DataFrame(nfl_team_effect_rows),
            width="stretch",
            hide_index=True,
            height=min(300, 38 + 35 * len(nfl_team_effect_rows)),
        )
    else:
        st.caption("No NFL teams have item effects this week.")

with selected_week_event_area.container():
    for weekly_event in weekly_events:
        st.info(
            f"📢 **Week {selected_week} Special Event: "
            f"{weekly_event.get('event_name', 'League Event')}**\n\n"
            f"{weekly_event.get('description', '')}"
        )

tab_labels = [
    "🏎️ Weekly Standings",
    "🏆 Overall GP Standings",
    "🧠 Strategize",
]
if st.session_state["is_commissioner"]:
    tab_labels.append("👑 Commissioner")
tabs = st.tabs(tab_labels)
tab1, tab2, tab3 = tabs[:3]
tab4 = tabs[3] if st.session_state["is_commissioner"] else None

# -----------------------------------------------------------------------------
# TAB 1: Weekly Mario Kart Race Standings
# -----------------------------------------------------------------------------
with tab1:
    st.header(f"Week {selected_week} Race Standings")

    if not calculated_matchups:
        st.info("No score data available for this week yet.")
    else:
        leaderboard = sorted(
            calculated_matchups,
            key=lambda t: (t.get("modified_score", 0.0), t.get("raw_score", 0.0)),
            reverse=True,
        )

        roster_summary = []
        for r_id, team_name in roster_map.items():
            team_data = next((t for t in leaderboard if t.get("roster_id") == r_id), None)
            raw_score = team_data.get("raw_score", 0.0) if team_data else 0.0
            mod_score = team_data.get("modified_score", 0.0) if team_data else 0.0
            roster_summary.append({
                "Roster ID": r_id,
                "Team": team_name,
                "Raw Score": round(raw_score, 2),
                "Modified Score": round(mod_score, 2),
            })

        roster_summary = sorted(
            roster_summary,
            key=lambda row: (row["Modified Score"], row["Raw Score"]),
            reverse=True,
        )

        rank_icons = {1: "🥇", 2: "🥈", 3: "🥉"}

        st.markdown(
            """
            <style>
            div[data-testid="stColumn"]:has(
                [class*="st-key-weekly-item-panel-"]
            ) {
                position: relative;
                align-self: stretch !important;
            }
            [class*="st-key-weekly-item-panel-"] {
                height: 100%;
                display: flex;
                flex-direction: column;
            }
            [class*="st-key-weekly-item-image-"] {
                position: absolute;
                top: 50%;
                left: 0;
                width: 100%;
                transform: translateY(-50%);
            }
            [class*="st-key-weekly-item-details-"] {
                position: absolute;
                bottom: 0;
                left: 0;
                width: 100%;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        for idx, team in enumerate(leaderboard, start=1):
            r_id = team.get("roster_id")
            t_name = roster_map.get(r_id, f"Team {r_id}")
            t_avatar = avatar_map.get(r_id, sleeper_api.get_avatar_url(None))
            mod_score = team.get("modified_score", 0.0)
            raw_score = team.get("raw_score", 0.0)
            effects = team.get("effects", [])

            icon = rank_icons.get(idx, "")

            with st.container(border=True):
                rank_col, avatar_col, name_col, score_col = st.columns(
                    [0.75, 0.55, 5, 1.5],
                    gap="small",
                    vertical_alignment="top",
                )
                with rank_col:
                    st.markdown(
                        f"<div style='font-size:1.5rem; font-weight:700; "
                        f"line-height:48px; white-space:nowrap;'>"
                        f"{icon} #{idx}</div>",
                        unsafe_allow_html=True,
                    )
                with avatar_col:
                    st.image(t_avatar, width=48)
                with name_col:
                    st.markdown(
                        f"<div style='font-size:1.35rem; font-weight:700; "
                        f"line-height:48px;'>"
                        f"{t_name}</div>",
                        unsafe_allow_html=True,
                    )

                with score_col:
                    st.markdown(
                        f"<div style='text-align:right; padding-top:0.55rem;'>"
                        f"<div style='font-size:1.25rem; font-weight:700;'>"
                        f"Score: {mod_score:.2f}</div>"
                        f"<div style='font-size:0.8rem; color:gray;'>"
                        f"Raw {raw_score:.2f} pts</div></div>",
                        unsafe_allow_html=True,
                    )

                roster_plays = plays_by_roster.get(str(r_id), [])
                roster_players = sleeper_api.get_roster_players(
                    league_id,
                    r_id,
                    matchup_data=matchup_data_by_roster.get(str(r_id)),
                ) or []
                roster_players = include_flex_item_players(
                    roster_players,
                    revealed_plays_by_roster.get(str(r_id), []),
                    players_data,
                    matchup_data_by_roster,
                )
                starter_slots = assign_starter_slots(
                    [
                        str(player_id)
                        for player_id in (
                            matchup_data_by_roster.get(str(r_id), {}).get(
                                "starters"
                            )
                            or []
                        )
                    ],
                    league_roster_positions,
                    players_data,
                )
                roster_item = inventory_by_roster.get(str(r_id))
                item_info = (roster_item or {}).get("items") or {}

                manager_item_col, roster_col = st.columns(
                    [1.2, 3.8],
                    gap="medium",
                    vertical_alignment="top",
                )
                with roster_col:
                    if effects:
                        st.write("**Active Chaos Effects:**")
                        for eff in effects:
                            st.markdown(f"- {eff}")

                    if roster_players:
                        st.dataframe(
                            make_roster_dataframe(
                                roster_players,
                                roster_player_modifiers.get(str(r_id), {}),
                                team.get("player_scores", {}),
                                starter_slots,
                                roster_player_effect_icons.get(str(r_id), {}),
                                show_injury_status_column=False,
                                show_inactive_status_icon=True,
                            ),
                            width="stretch",
                            hide_index=True,
                        )

                with manager_item_col:
                    item_id = str(
                        (roster_plays[0].get("item_id") if roster_plays else None)
                        or (roster_item or {}).get("item_id")
                        or ""
                    )
                    item_name = (
                        item_info.get("name")
                        or item_names.get(item_id)
                        or item_id.replace("_", " ").title()
                        or "Item"
                    )
                    item_description = (
                        item_info.get("description")
                        or item_descriptions.get(item_id, "")
                    )
                    with st.container(key=f"weekly-item-panel-{r_id}"):
                        with st.container(key=f"weekly-item-image-{r_id}"):
                            item_image_cols = st.columns([1, 2, 1])
                            with item_image_cols[1]:
                                st.image(
                                    get_item_image_path(item_id),
                                    width=150,
                                )

                        with st.container(key=f"weekly-item-details-{r_id}"):
                            if show_weekly_item_details and roster_plays:
                                st.write(f"**{item_name}**")
                                if item_description:
                                    st.caption(item_description)
                                for play in roster_plays:
                                    selection = play.get("selection") or {}
                                    if isinstance(selection, str):
                                        try:
                                            selection = json.loads(selection)
                                        except json.JSONDecodeError:
                                            selection = {}

                                    if selection:
                                        for detail in describe_item_selection(
                                            selection,
                                            roster_map,
                                            players_data,
                                        ):
                                            st.caption(detail)
                                    else:
                                        target_player_id = str(
                                            play.get("target_player_id") or ""
                                        )
                                        if target_player_id:
                                            player_info = players_data.get(
                                                target_player_id,
                                                {},
                                            )
                                            choice = (
                                                player_info.get("full_name")
                                                or (
                                                    f"{player_info.get('first_name', '')} "
                                                    f"{player_info.get('last_name', '')}"
                                                ).strip()
                                                or f"Player {target_player_id}"
                                            )
                                        else:
                                            choice = (
                                                play.get("target_nfl_team")
                                                or play.get("custom_target")
                                            )

                                        if choice:
                                            st.caption(f"Choice: {choice}")
                            elif show_weekly_item_details:
                                if item_info.get("name"):
                                    st.write(f"**{item_name}**")
                                    if item_description:
                                        st.caption(item_description)
                                    st.caption("No item selection recorded.")
                                else:
                                    st.write("**No items this week**")
                            else:
                                st.write("**Manager Item**")
                                st.caption(timing_context["item_details_message"])

with st.sidebar:
    st.divider()
    st.subheader(f"🎒 Your Week {item_week} Item")

    if not timing_context["drops_open"]:
        st.info(timing_context["sidebar_message"])
    else:
        if item_week == selected_week:
            item_events = weekly_events
        else:
            try:
                item_events = weekly_events_by_week.get(item_week, [])
                if item_week not in weekly_events_by_week:
                    item_events_res = (
                        supabase.table("league_events")
                        .select("week, event_name, description")
                        .eq("league_id", league_id)
                        .eq("week", item_week)
                        .execute()
                    )
                    item_events = item_events_res.data or []
            except Exception as exc:
                item_events = []
                st.sidebar.error(
                    f"Could not load this week's league events: {exc}"
                )

        item_unavailable_reason = item_service.get_item_unavailable_reason(
            item_week,
            item_events,
        )
        item_matchups = get_week_matchups(item_week)
        item_matchup_data_by_roster = {
            str(matchup.get("roster_id")): matchup
            for matchup in item_matchups
            if matchup.get("roster_id") is not None
        }

        if item_unavailable_reason:
            st.warning(item_unavailable_reason)
            auto_select_expired_item_plays(
                item_week,
                league_id,
                timing_context["item_use_deadline_passed"],
                roster_map,
                item_matchup_data_by_roster,
                players_data,
            )
        else:
            if all_plays_error:
                previous_gp_standings = []
                st.sidebar.error(
                    f"Could not load prior item plays for GP rankings: "
                    f"{all_plays_error}"
                )
            else:
                try:
                    standings_matchups_by_week = {
                        week: get_week_matchups(week)
                        for week in range(1, item_week)
                    }
                    previous_week_plays = [
                        play for play in revealed_all_plays
                        if play.get("week", 0) < item_week
                    ]
                    if any(standings_matchups_by_week.values()):
                        previous_gp_standings = scoring.calculate_gp_standings(
                            standings_matchups_by_week,
                            previous_week_plays,
                            players_data,
                            list(roster_map),
                            fallback_player_points_by_week,
                            weekly_events_by_week,
                        )
                    else:
                        previous_gp_standings = []
                except Exception as exc:
                    previous_gp_standings = []
                    st.sidebar.error(
                        f"Could not calculate prior GP standings for item odds: {exc}"
                    )

            previous_gp_ranks = {
                team["roster_id"]: rank
                for rank, team in enumerate(previous_gp_standings, start=1)
            }
            if previous_gp_ranks:
                item_service.generate_weekly_drops(
                    supabase=supabase,
                    league_id=league_id,
                    week=item_week,
                    standings_ranks=previous_gp_ranks,
                )
            else:
                st.info(
                    f"Week {item_week} drops need GP standings through "
                    f"Week {item_week - 1}."
                )

            auto_select_expired_item_plays(
                item_week,
                league_id,
                timing_context["item_use_deadline_passed"],
                roster_map,
                item_matchup_data_by_roster,
                players_data,
            )

            try:
                sidebar_inventory_res = (
                    supabase.table("team_inventory")
                    .select(
                        "id, item_id, is_used, "
                        "items(name, description, target_type)"
                    )
                    .eq("league_id", league_id)
                    .eq("roster_id", st.session_state["roster_id"])
                    .eq("week", item_week)
                    .execute()
                )
                sidebar_inventory = sidebar_inventory_res.data or []
            except Exception:
                sidebar_inventory = []

            if not sidebar_inventory:
                st.info("Item drop not available yet.")
            else:
                sidebar_item = sidebar_inventory[0]
                sidebar_item_info = sidebar_item.get("items") or {}
                st.image(
                    get_item_image_path(sidebar_item.get("item_id")),
                    width=56,
                )
                st.write(f"**{sidebar_item_info.get('name', 'Your item')}**")
                st.caption(sidebar_item_info.get("description", ""))
                active_preview = st.session_state.get("item_preview")
                if (
                    active_preview
                    and active_preview.get("league_id") == league_id
                    and active_preview.get("week") == item_week
                    and str(active_preview.get("roster_id"))
                    == str(st.session_state["roster_id"])
                ):
                    st.info("Test preview is active in Strategize.")

                if sidebar_item.get("is_used"):
                    st.success("Selection submitted for this week.")
                else:
                    allow_lock_in = timing_context["allow_lock_in"]
                    if not allow_lock_in:
                        st.caption(timing_context["lock_in_message"])

                    selection_action = render_item_selection_form(
                        str(sidebar_item.get("item_id")),
                        league_id,
                        item_week,
                        st.session_state["roster_id"],
                        roster_map,
                        item_matchup_data_by_roster,
                        players_data,
                        "sidebar_play_item_form",
                        allow_lock_in=allow_lock_in,
                    )
                    if selection_action:
                        selection, action = selection_action
                        if action == "test":
                            st.session_state["item_preview"] = {
                                "league_id": league_id,
                                "week": item_week,
                                "roster_id": st.session_state["roster_id"],
                                "item_id": sidebar_item.get("item_id"),
                                "selection": selection,
                            }
                            st.rerun()

                        if action == "lock_in":
                            try:
                                save_item_play(
                                    sidebar_item,
                                    selection,
                                    league_id,
                                    item_week,
                                    st.session_state["roster_id"],
                                )
                            except ValueError as exc:
                                st.sidebar.error(str(exc))
                            else:
                                st.session_state.pop("item_preview", None)
                                st.sidebar.success("Selection saved.")
                                st.rerun()

    st.divider()
    st.selectbox(
        "Active league",
        list(active_league_options),
        key="active_league_selection",
    )
    st.write(f"Logged in as: **{st.session_state['team_name']}**")
    if st.button("Log Out", key="sidebar_log_out"):
        remember_token = st.session_state.get("remember_token") or cookie_manager.get(AUTH_COOKIE_NAME)
        revoke_login_session(supabase, remember_token)
        st.session_state["pending_cookie_delete"] = True
        st.session_state["authenticated"] = False
        st.session_state["roster_id"] = None
        st.session_state["team_name"] = None
        st.session_state["is_commissioner"] = False
        st.session_state["user_id"] = None
        st.session_state["active_league_id"] = None
        st.session_state["active_league_selection"] = None
        st.session_state["remember_token"] = None
        st.session_state["login_rosters"] = []
        st.rerun()

    st.divider()
    st.subheader("Timing test")
    st.checkbox("Use test timing setting", key="use_test_timing")
    if st.session_state["use_test_timing"]:
        st.caption("Test values override live NFL timing.")
    else:
        st.caption("Using live NFL week and local day. Test selectors are disabled.")
    st.selectbox(
        "Current NFL week",
        options=list(range(1, 19)),
        key="timing_test_week",
        disabled=not st.session_state["use_test_timing"],
    )
    st.selectbox(
        "Day of week",
        options=list(range(7)),
        format_func=lambda day: [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ][day],
        key="timing_test_day",
        disabled=not st.session_state["use_test_timing"],
    )

# -----------------------------------------------------------------------------
# TAB 2: Overall Season Standings (Card Layout)
# -----------------------------------------------------------------------------
with tab2:
    st.header("🏆 Season-Wide Grand Prix Standings")
    st.caption("Points accumulated across all played weeks based on placement.")

    with st.spinner("Calculating season GP scores..."):
        gp_standings = scoring.calculate_gp_standings(
            {
                week: get_week_matchups(week)
                for week in range(1, selected_week + 1)
            },
            [
                play for play in revealed_all_plays
                if play.get("week", 0) <= selected_week
            ],
            players_data,
            list(roster_map),
            fallback_player_points_by_week,
            weekly_events_by_week,
        )
        season_totals = {
            team["roster_id"]: team["gp_points"]
            for team in gp_standings
        }
        season_raw_pts = {
            team["roster_id"]: team["modified_score"]
            for team in gp_standings
        }
        weekly_leaderboard = sorted(
            calculated_matchups,
            key=lambda team: (
                team.get("modified_score", 0.0),
                team.get("raw_score", 0.0),
            ),
            reverse=True,
        )
        weekly_gp_points = {
            team.get("roster_id"): scoring.GP_POINTS_MAP.get(rank, 0)
            for rank, team in enumerate(weekly_leaderboard, start=1)
        }

        overall_leaderboard = sorted(
            roster_map.items(),
            key=lambda item: (season_totals.get(item[0], 0), season_raw_pts.get(item[0], 0.0)),
            reverse=True,
        )

        rank_icons = {1: "🥇", 2: "🥈", 3: "🥉"}

        for idx, (r_id, t_name) in enumerate(overall_leaderboard, start=1):
            gp_pts = season_totals.get(r_id, 0)
            this_week_gp_pts = weekly_gp_points.get(r_id, 0)
            total_fantasy_pts = season_raw_pts.get(r_id, 0.0)
            t_avatar = avatar_map.get(r_id, sleeper_api.get_avatar_url(None))
            icon = rank_icons.get(idx, "")

            with st.container(border=True):
                col_rank, col_avatar, col_details = st.columns([1, 1, 4])

                with col_rank:
                    st.markdown(
                        f"<h2 style='text-align: center; margin: 0;'>{icon} #{idx}</h2>",
                        unsafe_allow_html=True,
                    )

                with col_avatar:
                    st.image(t_avatar, width="stretch")

                with col_details:
                    col_info, col_metric = st.columns([2, 1])

                    with col_info:
                        st.subheader(t_name)
                        st.caption(f"Cumulative Fantasy Score: **{total_fantasy_pts:.2f} pts**")

                    with col_metric:
                        st.metric(
                            label="Total GP Points",
                            value=f"{gp_pts} pts",
                            delta=f"+{this_week_gp_pts} GP pts this week",
                        )

# -----------------------------------------------------------------------------
# TAB 3: Strategy workspace
# -----------------------------------------------------------------------------
with tab3:
    st.header("🧠 Strategize")
    st.caption(
        "Test item choices from the sidebar. Your roster and player modifiers "
        "update for the preview; testing does not save the play."
    )
    user_roster_id = st.session_state["roster_id"]
    user_roster_players = sleeper_api.get_roster_players(
        league_id,
        user_roster_id,
        matchup_data=matchup_data_by_roster.get(str(user_roster_id)),
    ) or []
    user_roster_players = include_flex_item_players(
        user_roster_players,
        modifier_plays,
        players_data,
        matchup_data_by_roster,
    )
    if user_roster_players:
        strategize_calculated_matchups = scoring.calculate_modified_scores(
            raw_matchups,
            modifier_plays,
            players_data,
            previous_week_matchups,
            fallback_player_points_by_week.get(selected_week, {}),
            fallback_player_points_by_week.get(selected_week - 1, {}),
            weekly_events,
        )
        strategize_team = next(
            (
                team for team in strategize_calculated_matchups
                if str(team.get("roster_id")) == str(user_roster_id)
            ),
            {},
        )
        strategize_starter_slots = assign_starter_slots(
            [
                str(player_id)
                for player_id in (
                    matchup_data_by_roster.get(str(user_roster_id), {}).get(
                        "starters"
                    )
                    or []
                )
            ],
            league_roster_positions,
            players_data,
        )
        with st.expander(f"Your roster · Week {selected_week}", expanded=True):
            st.dataframe(
                make_roster_dataframe(
                    user_roster_players,
                    roster_player_modifiers.get(str(user_roster_id), {}),
                    strategize_team.get("player_scores", {}),
                    strategize_starter_slots,
                    roster_player_effect_icons.get(str(user_roster_id), {}),
                ),
                width="stretch",
                hide_index=True,
            )

# -----------------------------------------------------------------------------
# NFL Player Database with Event Indicators
# -----------------------------------------------------------------------------
with tab3:
    st.subheader("🏈 NFL Player Database")

    pruned_file_path = PROJECT_ROOT / "data" / "pruned_players.json"

    if not os.path.exists(pruned_file_path):
        st.error(f"⚠️ `{pruned_file_path}` not found in root directory.")
    else:
        with open(pruned_file_path, "r", encoding="utf-8") as f:
            pruned_players = json.load(f)

        roster_names_by_id = {
            str(roster_id): team_name
            for roster_id, team_name in roster_map.items()
        }
        player_owners_by_id = {}
        for roster_id, matchup in matchup_data_by_roster.items():
            for player_id in matchup.get("players") or []:
                player_owners_by_id[str(player_id)] = roster_names_by_id.get(
                    roster_id,
                    f"Roster {roster_id}",
                )

        # 2. Format player data into tabular format
        formatted_players = []
        for p_id, info in pruned_players.items():
            if isinstance(info, dict):
                full_name = (
                    info.get("full_name")
                    or f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
                    or f"Player {p_id}"
                )

                formatted_players.append({
                    "Name": (
                        f"{full_name} "
                        f"{player_database_effect_icons.get(str(p_id), '')}"
                    ).rstrip(),
                    "Position": info.get("position") or "N/A",
                    "Team": info.get("team") or "FA",
                    "Current Owner": player_owners_by_id.get(
                        str(p_id),
                        "Free Agent",
                    ),
                    "Depth Chart Order": info.get("depth_chart_order", "N/A"),
                    "Modifier": player_database_modifiers.get(str(p_id), "—"),
                    "Injury Status": format_injury_status(
                        info.get("injury_status")
                    ),
                })

        df_players = pd.DataFrame(formatted_players)

        # Clean depth chart order column for proper sorting
        if "Depth Chart Order" in df_players.columns:
            df_players["Depth Chart Order"] = pd.to_numeric(
                df_players["Depth Chart Order"], errors="coerce"
            ).astype("Int64")
            df_players = df_players.sort_values(
                by=["Team", "Depth Chart Order", "Name"],
                na_position="last",
            )

            # 3. Expandable Filter Section with Dropdowns
            with st.expander("🔎 Filter Players", expanded=True):
                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    name_search = st.text_input("Search Name")

                with col2:
                    # Get unique teams sorted, excluding empty ones
                    team_options = sorted([t for t in df_players["Team"].unique() if t])
                    selected_teams = st.multiselect("Team", options=team_options)

                with col3:
                    pos_options = sorted([p for p in df_players["Position"].unique() if p])
                    selected_positions = st.multiselect("Position", options=pos_options)

                with col4:
                    owner_options = sorted(
                        df_players["Current Owner"].dropna().unique().tolist()
                    )
                    selected_owners = st.multiselect(
                        "Owner",
                        options=owner_options,
                    )

            filtered_df = df_players.copy()

            if name_search:
                filtered_df = filtered_df[filtered_df["Name"].str.contains(name_search, case=False, na=False)]

            if selected_teams:
                filtered_df = filtered_df[filtered_df["Team"].isin(selected_teams)]

            if selected_positions:
                filtered_df = filtered_df[filtered_df["Position"].isin(selected_positions)]

            if selected_owners:
                filtered_df = filtered_df[
                    filtered_df["Current Owner"].isin(selected_owners)
                ]

            # 4. Display the player database without injury-status row shading
            st.dataframe(filtered_df, width="stretch", hide_index=True)

# -----------------------------------------------------------------------------
# TAB 4: Commissioner Administration
# -----------------------------------------------------------------------------
if not st.session_state["is_commissioner"]:
    st.stop()

with tab4:
    st.header(f"👑 Commissioner Tools · Week {selected_week}")
    saved_score_notice = st.session_state.pop(
        "player_score_saved_notice",
        None,
    )
    if saved_score_notice:
        st.success(f"Saved raw score for {saved_score_notice}.")
    if fallback_score_error:
        st.error(
            "Commissioner-entered player scores could not be loaded. Verify "
            "the player_score_inputs table migration and Supabase connection. "
            f"Details: {fallback_score_error}"
        )

    previous_gp_standings = []
    if selected_week > 1 and not all_plays_error:
        try:
            commissioner_matchups_by_week = {
                week: get_week_matchups(week)
                for week in range(1, selected_week)
            }
            previous_week_plays = [
                play
                for play in revealed_all_plays
                if int(play.get("week") or 0) < selected_week
            ]
            if any(commissioner_matchups_by_week.values()):
                previous_gp_standings = scoring.calculate_gp_standings(
                    commissioner_matchups_by_week,
                    previous_week_plays,
                    players_data,
                    list(roster_map),
                    fallback_player_points_by_week,
                    weekly_events_by_week,
                )
        except Exception as exc:
            st.error(f"Could not calculate previous GP standings: {exc}")
    elif selected_week > 1 and all_plays_error:
        st.error(f"Could not load prior item plays for GP ordering: {all_plays_error}")

    gp_rank_by_roster = {
        str(team["roster_id"]): rank
        for rank, team in enumerate(previous_gp_standings, start=1)
    }

    def commissioner_order_key(record: dict) -> tuple[int, str, str]:
        roster_id = str(record.get("roster_id"))
        team_name = next(
            (
                name for key, name in roster_map.items()
                if str(key) == roster_id
            ),
            f"Roster {roster_id}",
        )
        return (
            gp_rank_by_roster.get(roster_id, len(roster_map) + 1),
            str(team_name).casefold(),
            str(record.get("item_id") or ""),
        )

    if not gp_rank_by_roster:
        st.caption(
            "Previous-week GP standings are unavailable; teams are listed "
            "alphabetically."
        )

    st.subheader(
        "Weekly item choices" if show_weekly_item_details
        else "Weekly item lock-in status"
    )
    plays_by_roster_item = {
        (str(play.get("roster_id")), str(play.get("item_id"))): play
        for play in weekly_plays
    }
    lock_in_window_open = (
        timing_context["week"] == selected_week
        and timing_context["weekday"] in {1, 2}
    )
    item_records = []
    inventory_item_keys = set()
    for item in weekly_inventory:
        roster_id = str(item.get("roster_id"))
        item_id = str(item.get("item_id") or "")
        item_key = (roster_id, item_id)
        inventory_item_keys.add(item_key)
        play = plays_by_roster_item.get(item_key)
        selection = _commissioner_selection(play) if play else {}
        selection_details = (
            describe_item_selection(selection, roster_map, players_data)
            if selection
            else []
        )
        if play and not selection_details:
            selection_text = (
                "No selection required"
                if selection.get("mode") == "none"
                else "Selection recorded"
            )
        elif selection_details:
            selection_text = "; ".join(selection_details)
        elif play:
            selection_text = "No selection details recorded"
        else:
            selection_text = (
                "Pending selection"
                if lock_in_window_open
                else "No selection recorded"
            )

        item_records.append({
            "roster_id": roster_id,
            "item_id": item_id,
            "Manager": next(
                (
                    name for key, name in roster_map.items()
                    if str(key) == roster_id
                ),
                f"Roster {roster_id}",
            ),
            "Item": (
                item_names.get(item_id)
                or item_id.replace("_", " ").title()
                or "Item"
            ),
            "Selection": selection_text,
            "Lock-in Status": (
                "Autogenerated (late)"
                if selection.get("auto_selected")
                else "Locked in"
            ) if play else (
                "Pending selection"
                if lock_in_window_open
                else "No selection recorded"
            ),
        })

    for item_key, play in plays_by_roster_item.items():
        if item_key in inventory_item_keys:
            continue
        roster_id, item_id = item_key
        selection = _commissioner_selection(play)
        selection_details = (
            describe_item_selection(selection, roster_map, players_data)
            if selection
            else []
        )
        item_records.append({
            "roster_id": roster_id,
            "item_id": item_id,
            "Manager": next(
                (
                    name for key, name in roster_map.items()
                    if str(key) == roster_id
                ),
                f"Roster {roster_id}",
            ),
            "Item": (
                item_names.get(item_id)
                or item_id.replace("_", " ").title()
                or "Item"
            ),
            "Selection": (
                "; ".join(selection_details)
                or (
                    "No selection required"
                    if selection.get("mode") == "none"
                    else "No selection details recorded"
                )
            ),
            "Lock-in Status": (
                "Autogenerated (late)"
                if selection.get("auto_selected")
                else "Locked in"
            ),
        })

    item_records.sort(key=commissioner_order_key)
    if item_records:
        st.dataframe(
            pd.DataFrame(item_records)[
                ["Manager", "Item", "Selection", "Lock-in Status"]
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No item drops or choices are recorded for this week.")

    st.divider()
    left_column, right_column = st.columns(2, gap="large")
    with left_column:
        st.subheader("Weekly item recap · previous week's GP order")
        ordered_plays = sorted(weekly_plays, key=commissioner_order_key)
        report_lines = []
        for play in ordered_plays:
            roster_id = str(play.get("roster_id"))
            team_name = next(
                (
                    name for key, name in roster_map.items()
                    if str(key) == roster_id
                ),
                f"Roster {roster_id}",
            )
            item_id = str(play.get("item_id") or "")
            item_name = (
                item_names.get(item_id)
                or item_id.replace("_", " ").title()
                or "Item"
            )
            report_lines.append(
                _commissioner_item_summary(
                    team_name,
                    item_name,
                    play,
                    roster_map,
                    players_data,
                    item_descriptions.get(item_id, ""),
                )
            )
        st.text_area(
            "Copy and paste this week's item choices (ordered by previous week's GP standings)",
            value="\n".join(report_lines)
            or "No item choices have been recorded this week.",
            height=320,
            key=f"commissioner_item_recap_{league_id}_{selected_week}",
        )

    with right_column:
        st.subheader("Commissioner to-do list")
        st.caption("Checklist marks are kept for this app session.")
        checkbox_item_ids = {
            "COIN",
            "MASTER_BALL",
            "RECALL",
            "SMASH_BALL",
        }
        checklist_plays = [
            play for play in ordered_plays
            if str(play.get("item_id") or "").upper() in checkbox_item_ids
        ]
        if checklist_plays:
            for play in checklist_plays:
                roster_id = str(play.get("roster_id"))
                team_name = next(
                    (
                        name for key, name in roster_map.items()
                        if str(key) == roster_id
                    ),
                    f"Roster {roster_id}",
                )
                item_id = str(play.get("item_id") or "").upper()
                item_name = (
                    item_names.get(item_id)
                    or item_id.replace("_", " ").title()
                    or "Item"
                )
                todo_label = _commissioner_item_summary(
                    team_name,
                    item_name,
                    play,
                    roster_map,
                    players_data,
                    item_descriptions.get(item_id, ""),
                )
                if item_id == "COIN":
                    custom_target = play.get("custom_target")
                    try:
                        coin_target = (
                            json.loads(custom_target)
                            if isinstance(custom_target, str)
                            else {}
                        )
                    except json.JSONDecodeError:
                        coin_target = {}
                    if not isinstance(coin_target, dict):
                        coin_target = {}
                    stored_amount = coin_target.get("coin_faab_amount")
                    coin_target = item_service.ensure_coin_faab_amount(
                        coin_target
                    )
                    coin_amount = coin_target["coin_faab_amount"]
                    if stored_amount != coin_amount:
                        coin_target.setdefault("mode", "none")
                        try:
                            supabase.table("weekly_plays").update({
                                "custom_target": json.dumps(coin_target)
                            }).eq("id", play.get("id")).eq(
                                "league_id", league_id
                            ).execute()
                            play["custom_target"] = json.dumps(coin_target)
                        except APIError as exc:
                            st.error(
                                "Could not save this Coin's FAAB amount to "
                                f"the weekly play: {exc}"
                            )
                            coin_amount = None
                    if coin_amount is None:
                        todo_label = (
                            "Coin FAAB amount could not be saved; resolve the "
                            "database error before applying it in Sleeper: "
                            f"{todo_label}"
                        )
                    else:
                        todo_label = (
                            f"Apply {coin_amount} FAAB in Sleeper: {todo_label}"
                        )
                elif item_id == "MASTER_BALL":
                    todo_label = f"Make this Master Ball trade in Sleeper: {todo_label}"
                st.checkbox(
                    todo_label,
                    key=(
                        f"commissioner_todo_{league_id}_{selected_week}_"
                        f"{roster_id}_{item_id}"
                    ),
                )
        else:
            st.caption("No Coin, Master Ball, Recall, or Smash Ball items this week.")

        missing_score_targets = scoring.get_missing_item_player_score_targets(
            weekly_plays,
            raw_matchups,
            previous_week_matchups,
            players_data,
            selected_week,
            fallback_player_points_by_week,
        )
        unique_missing_score_targets = {}
        for target in missing_score_targets:
            target_key = (
                target["scoring_week"],
                target["player_key"],
            )
            unique_missing_score_targets.setdefault(target_key, target)

        st.subheader("Missing player scores")
        if unique_missing_score_targets:
            st.caption(
                "Sleeper matchup scores are checked across every league roster "
                "first. Enter the player's raw weekly points only when Sleeper "
                "does not provide a score."
            )
            for (score_week, player_key), target in unique_missing_score_targets.items():
                score_label = (
                    f"{target['player_name']} · Week {score_week} · "
                    f"{target['item_label']}"
                )
                with st.form(
                    key=(
                        f"commissioner_player_score_{league_id}_{score_week}_"
                        f"{player_key}"
                    )
                ):
                    st.caption(score_label)
                    raw_points_text = st.text_input(
                        "Raw weekly fantasy points",
                        key=(
                            f"commissioner_player_score_value_{league_id}_"
                            f"{score_week}_{player_key}"
                        ),
                    )
                    score_submitted = st.form_submit_button("Save raw score")
                if score_submitted:
                    try:
                        raw_points = float(raw_points_text)
                    except ValueError:
                        st.error("Enter a valid numeric score before saving.")
                    else:
                        try:
                            save_player_score_input(
                                supabase,
                                league_id,
                                score_week,
                                target["player_id"],
                                target["player_name"],
                                raw_points,
                            )
                        except Exception as exc:
                            st.error(f"Could not save the player score: {exc}")
                        else:
                            st.session_state["player_score_saved_notice"] = (
                                score_label
                            )
                            st.rerun()
        else:
            st.caption(
                "No selected player targets are missing weekly scores."
            )