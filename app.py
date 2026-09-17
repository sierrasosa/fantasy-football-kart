import streamlit as st
import hashlib
from supabase import create_client, Client
import sleeper_api
import scoring

# -----------------------------------------------------------------------------
# 1. Page Configuration & Supabase Initialization
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Fantasy Football Kart 🏎️",
    page_icon="🏎️",
    layout="wide"
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
    
    # Fetch team rosters from Supabase
    try:
        rosters_res = supabase.table("rosters").select("*").execute()
        rosters = rosters_res.data or []
    except Exception as e:
        rosters = []
        st.sidebar.error(f"Error loading rosters from Supabase: {e}")

    if rosters:
        team_options = {r["team_name"]: r for r in rosters}
        selected_team_name = st.sidebar.selectbox("Select Your Team", list(team_options.keys()))
        entered_pin = st.sidebar.text_input("Enter 4-Digit PIN", type="password")

        if st.sidebar.button("Log In"):
            selected_roster = team_options[selected_team_name]
            # Verify PIN against stored hash
            if hash_pin(entered_pin) == selected_roster.get("pin_hash"):
                st.session_state["authenticated"] = True
                st.session_state["roster_id"] = selected_roster["roster_id"]
                st.session_state["team_name"] = selected_roster["team_name"]
                st.sidebar.success(f"Welcome, {selected_roster['team_name']}!")
                st.rerun()
            else:
                st.sidebar.error("Incorrect PIN.")
    else:
        st.sidebar.info("No rosters found in Supabase. Please seed your 'rosters' table.")
else:
    st.sidebar.write(f"Logged in as: **{st.session_state['team_name']}**")
    if st.sidebar.button("Log Out"):
        st.session_state["authenticated"] = False
        st.session_state["roster_id"] = None
        st.session_state["team_name"] = None
        st.rerun()

# Global League Week Selector
selected_week = st.sidebar.number_input("NFL Week", min_value=1, max_value=18, value=1, step=1)

# -----------------------------------------------------------------------------
# 4. Data Loading (Sleeper & Supabase)
# -----------------------------------------------------------------------------
league_id = st.secrets["SLEEPER_LEAGUE_ID"]

# Load NFL player master map (cached)
with st.spinner("Loading NFL player database..."):
    players_data = sleeper_api.get_nfl_players()

# Fetch weekly matchups from Sleeper API
raw_matchups = sleeper_api.get_league_matchups(league_id, selected_week)

# Fetch played items for selected week from Supabase
try:
    plays_res = supabase.table("weekly_plays").select("*").eq("week", selected_week).execute()
    weekly_plays = plays_res.data or []
except Exception:
    weekly_plays = []

# Calculate modified scores with chaos modifiers applied
calculated_matchups = scoring.calculate_modified_scores(raw_matchups, weekly_plays, players_data)

# Map roster_ids to team names from Supabase
roster_map = {}
try:
    r_data = supabase.table("rosters").select("roster_id, team_name").execute().data
    roster_map = {r["roster_id"]: r["team_name"] for r in r_data}
except Exception:
    pass

# -----------------------------------------------------------------------------
# 5. Main UI Tabs
# -----------------------------------------------------------------------------
st.title("🏎️ Fantasy Football Kart Dashboard WHEE")

tab1, tab2 = st.tabs(["📊 Live Matchup Scoreboard", "🎒 Item Inventory & Play Portal"])

# -----------------------------------------------------------------------------
# TAB 1: Live Scoreboard
# -----------------------------------------------------------------------------
with tab1:
    st.header(f"Week {selected_week} Scoreboard")
    
    if not calculated_matchups:
        st.info("No matchup data available for this week yet.")
    else:
        # Group calculated matchups by matchup_id
        matchup_groups = {}
        for m in calculated_matchups:
            m_id = m.get("matchup_id")
            if m_id not in matchup_groups:
                matchup_groups[m_id] = []
            matchup_groups[m_id].append(m)

        # Display side-by-side matchup cards
        for m_id, teams in matchup_groups.items():
            if len(teams) == 2:
                t1, t2 = teams[0], teams[1]
                t1_name = roster_map.get(t1["roster_id"], f"Team {t1['roster_id']}")
                t2_name = roster_map.get(t2["roster_id"], f"Team {t2['roster_id']}")
                
                with st.expander(f"⚔️ Matchup {m_id}: {t1_name} vs {t2_name}", expanded=True):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.subheader(t1_name)
                        st.metric("Modified Score", f"{t1['modified_score']} pts", delta=round(t1['modified_score'] - t1['raw_score'], 2))
                        st.caption(f"Raw Sleeper Score: {t1['raw_score']} pts")
                        if t1["effects"]:
                            st.write("**Active Effects:**")
                            for eff in t1["effects"]:
                                st.write(f"- {eff}")

                    with col2:
                        st.subheader(t2_name)
                        st.metric("Modified Score", f"{t2['modified_score']} pts", delta=round(t2['modified_score'] - t2['raw_score'], 2))
                        st.caption(f"Raw Sleeper Score: {t2['raw_score']} pts")
                        if t2["effects"]:
                            st.write("**Active Effects:**")
                            for eff in t2["effects"]:
                                st.write(f"- {eff}")

# -----------------------------------------------------------------------------
# TAB 2: Item Inventory & Play Submission
# -----------------------------------------------------------------------------
with tab2:
    st.header("🎒 Item Inventory & Action Portal")

    if not st.session_state["authenticated"]:
        st.warning("🔒 Please log in via the sidebar to view your inventory and play chaos items.")
    else:
        user_roster_id = st.session_state["roster_id"]
        
        # Fetch available inventory for logged-in team
        inv_res = supabase.table("team_inventory") \
            .select("id, item_id, items(name, description, target_type)") \
            .eq("roster_id", user_roster_id) \
            .eq("is_used", False) \
            .execute()
        
        inventory = inv_res.data or []
        
        col_inv, col_play = st.columns([1, 1])
        
        with col_inv:
            st.subheader("Your Available Items")
            if not inventory:
                st.info("You currently have no unplayed items in your inventory.")
            else:
                for item in inventory:
                    details = item.get("items", {})
                    st.success(f"**{details.get('name')}** (`{item['item_id']}`)\n\n{details.get('description')}")

        with col_play:
            st.subheader("Play an Item")
            if not inventory:
                st.write("Acquire items to play them during the week.")
            else:
                # Format dropdown options
                item_options = {
                    f"{i['items']['name']} (ID: {i['id']})": i 
                    for i in inventory
                }
                selected_item_label = st.selectbox("Select Item to Play", list(item_options.keys()))
                chosen_inv_item = item_options[selected_item_label]
                target_type = chosen_inv_item["items"]["target_type"]
                
                target_player_id = None
                target_nfl_team = None

                # Collect required targeting input based on item definition
                if target_type == "PLAYER":
                    # Create player search options
                    player_search = {
                        f"{info['name']} ({info['pos']} - {info['team']})": p_id
                        for p_id, info in players_data.items()
                        if info.get("pos") in ["QB", "RB", "WR", "TE", "K", "DEF"]
                    }
                    selected_player = st.selectbox("Target Player", sorted(list(player_search.keys())))
                    target_player_id = player_search[selected_player]

                elif target_type == "TEAM":
                    nfl_teams = sorted(list(set(
                        info["team"] for info in players_data.values() if info.get("team")
                    )))
                    target_nfl_team = st.selectbox("Target NFL Team", nfl_teams)

                elif target_type == "SELF":
                    st.info("This item applies directly to your team roster.")

                if st.button("🚀 Confirm & Play Item", type="primary"):
                    try:
                        # 1. Record play in weekly_plays
                        supabase.table("weekly_plays").insert({
                            "week": selected_week,
                            "roster_id": user_roster_id,
                            "item_id": chosen_inv_item["item_id"],
                            "target_player_id": target_player_id,
                            "target_nfl_team": target_nfl_team
                        }).execute()

                        # 2. Mark item as used in team_inventory
                        supabase.table("team_inventory") \
                            .update({"is_used": True}) \
                            .eq("id", chosen_inv_item["id"]) \
                            .execute()

                        st.success("🎉 Item played successfully! Updating scoreboard...")
                        st.rerun()

                    except Exception as e:
                        st.error(f"Failed to play item: {e}")