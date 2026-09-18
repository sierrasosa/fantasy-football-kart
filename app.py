import hashlib
import sleeper_api
import scoring
import streamlit as st
import item_engine
from datetime import datetime, timedelta
from supabase import Client, create_client

# -----------------------------------------------------------------------------
# 1. Page Configuration & Supabase Initialization
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Fantasy Football Kart 🏎️", page_icon="🏎️", layout="wide"
)


@st.cache_resource
def init_supabase() -> Client:
    """Initialize Supabase client connection."""
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


supabase = init_supabase()


def hash_pin(pin_str: str) -> str:
    """Hashes a PIN string for secure comparison."""
    return hashlib.sha256(pin_str.encode()).hexdigest()


# Mario Kart Grand Prix points allocation table
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

# -----------------------------------------------------------------------------
# 2. Session State Initialization
# -----------------------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "roster_id" not in st.session_state:
    st.session_state["roster_id"] = None
if "team_name" not in st.session_state:
    st.session_state["team_name"] = None

# -----------------------------------------------------------------------------
# 3. Sidebar Authentication Engine
# -----------------------------------------------------------------------------
st.sidebar.title("🏎️ FF Kart League")

if not st.session_state["authenticated"]:
    st.sidebar.subheader("Manager Login")

    try:
        rosters_res = supabase.table("rosters").select("*").execute()
        rosters = rosters_res.data or []
    except Exception as e:
        rosters = []
        st.sidebar.error(f"Error loading rosters from Supabase: {e}")

    if rosters:
        team_options = {r.get("team_name", f"Roster {r.get('roster_id')}"): r for r in rosters}
        selected_team_name = st.sidebar.selectbox(
            "Select Your Team", list(team_options.keys())
        )
        entered_pin = st.sidebar.text_input("Enter 4-Digit PIN", type="password")

        if st.sidebar.button("Log In"):
            selected_roster = team_options[selected_team_name]
            if hash_pin(entered_pin) == selected_roster.get("pin_hash"):
                st.session_state["authenticated"] = True
                st.session_state["roster_id"] = selected_roster.get("roster_id")
                st.session_state["team_name"] = selected_roster.get("team_name")
                st.sidebar.success(f"Welcome, {selected_roster.get('team_name')}!")
                st.rerun()
            else:
                st.sidebar.error("Incorrect PIN.")
    else:
        st.sidebar.info(
            "No rosters found in Supabase. Please seed your 'rosters' table."
        )
else:
    st.sidebar.write(f"Logged in as: **{st.session_state['team_name']}**")
    if st.sidebar.button("Log Out"):
        st.session_state["authenticated"] = False
        st.session_state["roster_id"] = None
        st.session_state["team_name"] = None
        st.rerun()

# Global League Week Selector
selected_week = st.sidebar.number_input(
    "NFL Week", min_value=1, max_value=18, value=1, step=1
)

# -----------------------------------------------------------------------------
# 4. Data Loading (Sleeper & Supabase)
# -----------------------------------------------------------------------------
league_id = st.secrets["SLEEPER_LEAGUE_ID"]

with st.spinner("Loading NFL player database..."):
    players_data = sleeper_api.get_nfl_players() or {}

raw_matchups = sleeper_api.get_league_matchups(league_id, selected_week) or []

try:
    plays_res = (
        supabase.table("weekly_plays")
        .select("*")
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
    r_data = supabase.table("rosters").select("roster_id, team_name").execute().data or []
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

        rank_icons = {1: "🥇", 2: "🥈", 3: "🥉"}

        for idx, team in enumerate(leaderboard, start=1):
            r_id = team.get("roster_id")
            t_name = roster_map.get(r_id, f"Team {r_id}")
            t_avatar = avatar_map.get(r_id, sleeper_api.get_avatar_url(None))
            mod_score = team.get("modified_score", 0.0)
            raw_score = team.get("raw_score", 0.0)
            delta_score = round(mod_score - raw_score, 2)
            effects = team.get("effects", [])
            gp_pts = GP_POINTS_MAP.get(idx, 0)

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
                    st.image(t_avatar, use_container_width=True)

                with col_details:
                    col_info, col_metric = st.columns([2, 1])

                    with col_info:
                        st.subheader(t_name)
                        st.caption(f"Raw Sleeper Score: **{raw_score:.2f} pts**")
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
                supabase.table("weekly_plays").select("*").lte("week", selected_week).execute()
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
                    gp_gained = GP_POINTS_MAP.get(r_rank, 0)
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
                    st.image(t_avatar, use_container_width=True)

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

# Roll weekly items or check for existing
if current_weekday >= 1:  # Tuesday (1) through Sunday (6)
    # 1. Fetch current standings/ranks map {roster_id: rank}
    standings_ranks = {
        team["roster_id"]: rank 
        for rank, team in enumerate(leaderboard, start=1)
    }
    
    # 2. Automatically check and roll drops if not already generated
    success, message = item_engine.generate_weekly_drops(
        supabase=supabase, 
        week=selected_week, 
        standings_ranks=standings_ranks
    )


    # Check for Active League Event
    try:
        event_res = supabase.table("league_events").select("*").eq("week", selected_week).execute()
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
        user_roster_id = st.session_state["roster_id"]

        # Fetch Manager's Rolled Item for the Week
        try:
            inv_res = (
                supabase.table("team_inventory")
                .select("id, item_id, is_used, items(name, description, target_type)")
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
                        roster_players = sleeper_api.get_roster_players(user_roster_id)
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
                            "week": selected_week,
                            "roster_id": user_roster_id,
                            "item_id": item_record.get("item_id"),
                            "target_player_id": target_player_id,
                            "target_nfl_team": target_team,
                            "custom_target": custom_text
                        }).execute()

                        supabase.table("team_inventory").update({"is_used": True}).eq(
                            "id", item_record.get("id")
                        ).execute()

                        st.success("🎉 Selection saved successfully!")
                        st.rerun()

# -----------------------------------------------------------------------------
# TAB 4: NFL Player Database with Event Indicators
# -----------------------------------------------------------------------------
with tab4:
    st.header("🏈 NFL Player Database")

    # Check for active event indicators (e.g., Remix or Rookie of the Week)
    is_rookie_week = active_event and active_event.get("event_name") == "Rookie of the Week"
    is_remix_week = active_event and active_event.get("event_name") == "Remix"

    filtered_players = []
    for p_id, p in players_data.items():
        pos = p.get("pos")
        team = p.get("team")
        name = p.get("name", "")
        years_exp = p.get("years_exp", 0)

        if pos not in ["QB", "RB", "WR", "TE", "K", "DEF"]:
            continue

        status_tag = "ACTIVE"
        if is_rookie_week and years_exp == 0:
            status_tag = "⭐ ROOKIE (SUPERCHARGED)"
        elif is_remix_week and p.get("is_top_banned"):
            status_tag = "🚫 BANNED (REMIX)"

        filtered_players.append({
            "Status": status_tag,
            "Name": name,
            "Position": pos,
            "NFL Team": team or "FA",
            "Age": p.get("age", "N/A"),
        })

    st.dataframe(
        filtered_players[:200],
        column_config={
            "Status": st.column_config.TextColumn("Status / Indicator", width="medium"),
            "Name": st.column_config.TextColumn("Player", width="medium"),
        },
        use_container_width=True,
        hide_index=True,
    )
# -----------------------------------------------------------------------------
# TAB 5: Commissioner Administration
# -----------------------------------------------------------------------------
with tab5:
    st.header("👑 Commissioner Tools")
    st.info(
        "🛠️ Commissioner panel pending specification. Let me know what administrative features you'd like to include here!"
    )