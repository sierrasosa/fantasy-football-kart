from helpers import sleeper_api
from game_logic import scoring, item_service
import streamlit as st
import extra_streamlit_components as stx
import pandas as pd
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
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


def make_roster_dataframe(roster_players: list[dict]) -> pd.DataFrame:
    """Build a consistently sorted roster table with weekly points and injuries."""
    roster_df = pd.DataFrame([
        {
            "Player": player.get("name", "Unknown"),
            "Pos": player.get("pos", "N/A"),
            "Team": player.get("team", "FA"),
            "Starter": "Yes" if player.get("is_starter") else "No",
            "Points": player.get("points"),
            "Injury Status": player.get("injury_status", "Active"),
        }
        for player in roster_players
    ])
    if not roster_df.empty:
        position_order = ["QB", "RB", "WR", "TE", "K", "DEF", "FLEX", "BN"]
        roster_df["sort_pos"] = roster_df["Pos"].map(
            {position: index for index, position in enumerate(position_order)}
        ).fillna(len(position_order))
        roster_df = roster_df.sort_values(
            by=["Starter", "sort_pos", "Player"],
            ascending=[False, True, True],
        ).drop(columns=["sort_pos"])
    return roster_df


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
st.sidebar.title("🏎️ FF Kart League")


if not st.session_state["authenticated"]:
    st.sidebar.subheader("Manager Login")
    username = st.sidebar.text_input("Sleeper username", key="sleeper_username")

    if st.sidebar.button("Find account", key="find_sleeper_account"):
        st.session_state["login_error"] = None
        st.session_state["setup_account"] = None
        st.session_state["setup_is_commissioner"] = False
        st.session_state["login_rosters"] = []
        st.session_state["setup_leagues"] = []
        st.session_state["current_setup_season"] = None
        st.session_state["loaded_setup_season"] = None
        account = sleeper_api.get_user(username.strip()) if username.strip() else {}
        account = account or {}
        user_id = account.get("user_id")
        if not user_id:
            st.session_state["setup_account"] = None
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
            except Exception as exc:
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
    ):
        st.sidebar.info(
            "Please contact your commissioner to initialize the league in this app."
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
    league_options = {
        f"{row.get('league_name', row['league_id'])} · {row.get('team_name', 'Team')}": row
        for row in user_rosters
    }
    current_index = next(
        (i for i, row in enumerate(league_options.values())
         if str(row.get("league_id")) == str(st.session_state["active_league_id"])),
        0,
    )
    active_label = st.sidebar.selectbox("Active league", list(league_options), index=current_index)
    active_roster = league_options[active_label]
    st.session_state["active_league_id"] = active_roster.get("league_id")
    st.session_state["roster_id"] = active_roster.get("roster_id")
    st.session_state["team_name"] = active_roster.get("team_name")
    update_login_session_league(
        supabase,
        st.session_state.get("remember_token"),
        str(active_roster.get("league_id")),
    )
    st.sidebar.write(f"Logged in as: **{st.session_state['team_name']}**")
    if st.sidebar.button("Log Out"):
        remember_token = st.session_state.get("remember_token") or cookie_manager.get(AUTH_COOKIE_NAME)
        revoke_login_session(supabase, remember_token)
        st.session_state["pending_cookie_delete"] = True
        st.session_state["authenticated"] = False
        st.session_state["roster_id"] = None
        st.session_state["team_name"] = None
        st.session_state["user_id"] = None
        st.session_state["active_league_id"] = None
        st.session_state["remember_token"] = None
        st.session_state["login_rosters"] = []
        st.rerun()

if st.session_state["new_league_pins"]:
    pin_setup = st.session_state["new_league_pins"]
    st.warning("Share these one-time manager PINs with the matching league members, then dismiss this list.")
    st.subheader(f"PINs for {pin_setup['league_name']}")
    st.dataframe(pd.DataFrame(pin_setup["pins"]), hide_index=True, use_container_width=True)
    if st.button("I have shared/saved these PINs"):
        st.session_state["new_league_pins"] = None
        st.rerun()

if not st.session_state["authenticated"]:
    st.info("Log in from the sidebar to view a league.")
    st.stop()

# Global League Week Selector
selected_week = st.sidebar.number_input(
    "NFL Week", min_value=1, max_value=18, value=1, step=1
)

# -----------------------------------------------------------------------------
# 4. Data Loading (Sleeper & Supabase)
# -----------------------------------------------------------------------------
league_id = str(st.session_state["active_league_id"])

with st.spinner("Loading NFL player database..."):
    players_data = sleeper_api.get_nfl_players() or {}

raw_matchups = sleeper_api.get_league_matchups(league_id, selected_week) or []
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

calculated_matchups = scoring.calculate_modified_scores(
    raw_matchups, weekly_plays, players_data
) or []

# Build roster mapping from Supabase
roster_map = {}
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


# -----------------------------------------------------------------------------
# 5. Main UI Tabs
# -----------------------------------------------------------------------------
st.title("🏎️ Fantasy Football Kart")

now = datetime.now()
current_weekday = now.weekday()

if current_weekday == 1:  # Tuesday
    st.header("ITEM DROP TODAY! Go to the item tab and make your selection!")
elif 1 <= current_weekday <= 3:  # Tuesday - Thursday window
    days_until_thursday = (3 - current_weekday) % 7
    target_deadline = (now + timedelta(days=days_until_thursday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if target_deadline <= now:
        target_deadline += timedelta(days=7)

    time_remaining = target_deadline - now
    hours_remaining = round(time_remaining.total_seconds() / 3600, 1)

    st.header(f"You have {hours_remaining} hours left to use your item!")
else:
    st.header(
        "ITEMS IN PLAY! Go to the item tab to see what other players used!"
    )


tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🏎️ Weekly Standings",
    "🏆 Overall GP Standings",
    "🎒 Item Inventory & Play Portal",
    "🏈 Players Database",
    "👑 Commissioner",
])

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

        for idx, team in enumerate(leaderboard, start=1):
            r_id = team.get("roster_id")
            t_name = roster_map.get(r_id, f"Team {r_id}")
            t_avatar = avatar_map.get(r_id, sleeper_api.get_avatar_url(None))
            mod_score = team.get("modified_score", 0.0)
            raw_score = team.get("raw_score", 0.0)
            delta_score = round(mod_score - raw_score, 2)
            effects = team.get("effects", [])
            gp_pts = scoring.GP_POINTS_MAP.get(idx, 0)

            icon = rank_icons.get(idx, "")

            with st.container(border=True):
                col_rank, col_avatar, col_details = st.columns([1, 1, 4])

                with col_rank:
                    st.markdown(
                        f"<h2 style='text-align: center; margin: 0;'>{icon} #{idx}</h2>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<p style='text-align: center; font-weight: bold; color: #ff4b4b; margin: 0;'>+{gp_pts} GP Pts</p>",
                        unsafe_allow_html=True,
                    )

                with col_avatar:
                    st.image(t_avatar, width="stretch")

                with col_details:
                    col_info, col_metric = st.columns([2, 1])

                    with col_info:
                        st.subheader(t_name)
                        st.caption(f"Raw Sleeper Score: **{raw_score:.2f} pts**")

                        roster_players = sleeper_api.get_roster_players(
                            league_id,
                            r_id,
                            matchup_data=matchup_data_by_roster.get(str(r_id)),
                        ) or []
                        if roster_players:
                            roster_df = make_roster_dataframe(roster_players)
                            with st.expander("View roster"):
                                st.dataframe(
                                    roster_df,
                                    use_container_width=True,
                                    hide_index=True,
                                )

                        if effects:
                            st.write("**Active Chaos Effects:**")
                            for eff in effects:
                                st.markdown(f"- {eff}")

                    with col_metric:
                        st.metric(
                            label="Modified Score",
                            value=f"{mod_score:.2f} pts",
                            delta=f"{delta_score:+.2f} pts" if delta_score != 0 else None,
                        )

# -----------------------------------------------------------------------------
# TAB 2: Overall Season Standings (Card Layout)
# -----------------------------------------------------------------------------
with tab2:
    st.header("🏆 Season-Wide Grand Prix Standings")
    st.caption("Points accumulated across all played weeks based on placement.")

    with st.spinner("Calculating season GP scores..."):
        season_totals = {r_id: 0 for r_id in roster_map.keys()}
        season_raw_pts = {r_id: 0.0 for r_id in roster_map.keys()}

        try:
            all_plays_res = (
                supabase.table("weekly_plays")
                .select("*")
                .eq("league_id", league_id)
                .lte("week", selected_week)
                .execute()
            )
            all_plays = all_plays_res.data or []
        except Exception:
            all_plays = []

        for w in range(1, selected_week + 1):
            w_matchups = sleeper_api.get_league_matchups(league_id, w) or []
            if not w_matchups:
                continue
            w_plays = [p for p in all_plays if p.get("week") == w]
            w_calculated = scoring.calculate_modified_scores(
                w_matchups, w_plays, players_data
            ) or []

            w_sorted = sorted(
                w_calculated,
                key=lambda t: (t.get("modified_score", 0.0), t.get("raw_score", 0.0)),
                reverse=True,
            )

            for r_rank, team in enumerate(w_sorted, start=1):
                r_id = team.get("roster_id")
                if r_id is not None:
                    gp_gained = scoring.GP_POINTS_MAP.get(r_rank, 0)
                    season_totals[r_id] = season_totals.get(r_id, 0) + gp_gained
                    season_raw_pts[r_id] = season_raw_pts.get(r_id, 0.0) + team.get(
                        "modified_score", 0.0
                    )

        overall_leaderboard = sorted(
            roster_map.items(),
            key=lambda item: (season_totals.get(item[0], 0), season_raw_pts.get(item[0], 0.0)),
            reverse=True,
        )

        rank_icons = {1: "🥇", 2: "🥈", 3: "🥉"}

        for idx, (r_id, t_name) in enumerate(overall_leaderboard, start=1):
            gp_pts = season_totals.get(r_id, 0)
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
                        )

# -----------------------------------------------------------------------------
# TAB 3: Item Inventory & Action Portal
# -----------------------------------------------------------------------------
with tab3:
    st.header("🎒 Item Inventory & Action Portal")

    user_roster_id = st.session_state["roster_id"]
    # Roll weekly items or check for existing
    if current_weekday >= 1:  # Tuesday (1) through Sunday (6)
        # 1. Fetch current standings/ranks map {roster_id: rank}
        standings_ranks = {
            team["roster_id"]: rank 
            for rank, team in enumerate(leaderboard, start=1)
        }

        # 2. Automatically check and roll drops if not already generated
        success, message = item_service.generate_weekly_drops(
            supabase=supabase,
            league_id=league_id,
            week=selected_week,
            standings_ranks=standings_ranks,
        )

        # Check for Active League Event
        try:
            event_res = (
                supabase.table("league_events")
                .select("*")
                .eq("league_id", league_id)
                .eq("week", selected_week)
                .execute()
            )
            active_event = event_res.data[0] if event_res.data else None
        except Exception:
            active_event = None

        if active_event:
            st.info(
                f"📢 **Week {selected_week} Global Event: {active_event['event_name']}**\n\n"
                f"{active_event['description']}\n\n"
                "*Individual item drops are replaced by this league-wide event for the week.*"
            )
        elif not st.session_state["authenticated"]:
            st.warning("🔒 Please log in via the sidebar to view your rolled item and make selections.")
        else:
            # Fetch Manager's Rolled Item for the Week
            try:
                inv_res = (
                    supabase.table("team_inventory")
                    .select("id, item_id, is_used, items(name, description, target_type)")
                    .eq("league_id", league_id)
                    .eq("roster_id", user_roster_id)
                    .eq("week", selected_week)
                    .execute()
                )
                inventory = inv_res.data or []
            except Exception:
                inventory = []

            if not inventory:
                st.info("🕒 Item drops reveal Tuesday morning. Check back soon!")
            else:
                item_record = inventory[0]
                item_info = item_record.get("items") or {}
                target_type = item_info.get("target_type")
                is_used = item_record.get("is_used", False)

                st.success(f"### Your Week {selected_week} Item: **{item_info.get('name')}**")
                st.write(item_info.get("description"))

                if is_used:
                    st.info("✅ You have submitted your item selection for this week!")
                else:
                    st.subheader("Submit Your Selection (Deadline: Thursday Midnight)")

                    with st.form("play_item_form"):
                        target_player_id = None
                        target_team = None
                        custom_text = None

                        if target_type == "ROSTER_PLAYER":
                            # Fetch player's active roster from Sleeper
                            roster_players = sleeper_api.get_roster_players(league_id, user_roster_id)
                            player_opts = {
                                f"{p['name']} ({p['pos']} - {p['team']})": p["id"]
                                for p in roster_players
                            }
                            sel_player = st.selectbox("Select Roster Player", list(player_opts.keys()))
                            target_player_id = player_opts.get(sel_player)

                        elif target_type == "OPPONENT":
                            opponents = {
                                name: r_id for r_id, name in roster_map.items() if r_id != user_roster_id
                            }
                            target_team = st.selectbox("Select Target Manager", list(opponents.keys()))

                        elif target_type == "NFL_TEAM":
                            all_teams = sorted(list(set(p["team"] for p in players_data.values() if p.get("team"))))
                            target_team = st.selectbox("Select NFL Team", all_teams)

                        elif target_type == "FREE_TEXT":
                            custom_text = st.text_input("Enter Player/Target Name (e.g. LeBron James / Player Name)")

                        submitted = st.form_submit_button("🚀 Lock In Item Selection")

                        if submitted:
                            supabase.table("weekly_plays").insert({
                                "league_id": league_id,
                                "week": selected_week,
                                "roster_id": user_roster_id,
                                "item_id": item_record.get("item_id"),
                                "target_player_id": target_player_id,
                                "target_nfl_team": target_team,
                                "custom_target": custom_text,
                            }).execute()

                            supabase.table("team_inventory").update({"is_used": True}).eq(
                                "id", item_record.get("id")
                            ).eq("league_id", league_id).execute()

                            st.success("🎉 Selection saved successfully!")
                            st.rerun()

    user_roster_players = sleeper_api.get_roster_players(
        league_id,
        user_roster_id,
        matchup_data=matchup_data_by_roster.get(str(user_roster_id)),
    ) or []
    if user_roster_players:
        with st.expander(f"Your roster · Week {selected_week}", expanded=True):
            st.dataframe(
                make_roster_dataframe(user_roster_players),
                use_container_width=True,
                hide_index=True,
            )

# -----------------------------------------------------------------------------
# TAB 4: NFL Player Database with Event Indicators
# -----------------------------------------------------------------------------
with tab4:
    st.header("🏈 NFL Player Database")

    pruned_file_path = PROJECT_ROOT / "data" / "pruned_players.json"

    if not os.path.exists(pruned_file_path):
        st.error(f"⚠️ `{pruned_file_path}` not found in root directory.")
    else:
        with open(pruned_file_path, "r", encoding="utf-8") as f:
            pruned_players = json.load(f)

        # 2. Format player data into tabular format
        formatted_players = []
        for p_id, info in pruned_players.items():
            if isinstance(info, dict):
                full_name = (
                    info.get("full_name")
                    or f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
                    or f"Player {p_id}"
                )

                years_exp = info.get("years_exp")
                is_rookie = "Yes" if years_exp == 0 or years_exp == "0" else "No"

                formatted_players.append({
                    "Name": full_name,
                    "Position": info.get("position") or "N/A",
                    "Team": info.get("team") or "FA",
                    "Rookie": is_rookie,
                    "Depth Chart Order": info.get("depth_chart_order", "N/A"),
                    "Injury Status": info.get("injury_status") or "Active",
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
                col1, col2 = st.columns(2)
                col3, col4 = st.columns(2)

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
                    rookie_options = sorted([r for r in df_players["Rookie"].unique() if r])
                    selected_rookie = st.multiselect("Rookie", options=rookie_options)

            filtered_df = df_players.copy()

            if name_search:
                filtered_df = filtered_df[filtered_df["Name"].str.contains(name_search, case=False, na=False)]

            if selected_teams:
                filtered_df = filtered_df[filtered_df["Team"].isin(selected_teams)]

            if selected_positions:
                filtered_df = filtered_df[filtered_df["Position"].isin(selected_positions)]

            if selected_rookie:
                filtered_df = filtered_df[filtered_df["Rookie"].isin(selected_rookie)]

            # 4. Apply styling to grey out inactive/injured players by severity
            def style_ir_players(row):
                """Greys out injured players by injury designation severity."""
                injury_status = str(row.get("Injury Status", "")).upper()

                if injury_status in {"IR", "INACTIVE"}:
                    return ["background-color: #3f444c; color: #a0a6b0;"] * len(row)
                if injury_status in {"OUT", "DOUBTFUL", "QUESTIONABLE"}:
                    return ["background-color: #5b4d42; color: #d9c8b2;"] * len(row)
                return [""] * len(row)

            styled_df = filtered_df.style.apply(style_ir_players, axis=1)

            # 5. Display rendered styled table
            st.dataframe(styled_df, width="stretch", hide_index=True)

# -----------------------------------------------------------------------------
# TAB 5: Commissioner Administration
# -----------------------------------------------------------------------------
with tab5:
    st.header("👑 Commissioner Tools")
    st.info(
        "🛠️ Commissioner panel pending specification. Let me know what administrative features you'd like to include here!"
    )