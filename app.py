import hashlib
import sleeper_api
import scoring
import streamlit as st
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
    team_options = {r["team_name"]: r for r in rosters}
    selected_team_name = st.sidebar.selectbox(
        "Select Your Team", list(team_options.keys())
    )
    entered_pin = st.sidebar.text_input("Enter 4-Digit PIN", type="password")

    if st.sidebar.button("Log In"):
      selected_roster = team_options[selected_team_name]
      if hash_pin(entered_pin) == selected_roster.get("pin_hash"):
        st.session_state["authenticated"] = True
        st.session_state["roster_id"] = selected_roster["roster_id"]
        st.session_state["team_name"] = selected_roster["team_name"]
        st.sidebar.success(f"Welcome, {selected_roster['team_name']}!")
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
  players_data = sleeper_api.get_nfl_players()

raw_matchups = sleeper_api.get_league_matchups(league_id, selected_week)

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
)

roster_map = {}
try:
  r_data = (
      supabase.table("rosters").select("roster_id, team_name").execute().data
  )
  roster_map = {r["roster_id"]: r["team_name"] for r in r_data}
except Exception:
  pass

# -----------------------------------------------------------------------------
# 5. Main UI Tabs
# -----------------------------------------------------------------------------
st.title("🏎️ Fantasy Football Kart")

tab1, tab2, tab3, tab4 = st.tabs([
    "🏎️ Weekly Standings",
    "🏆 Overall GP Standings",
    "🏈 Players Database",
    "🎒 Item Inventory & Play Portal",
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
        key=lambda t: (t.get("modified_score", 0), t.get("raw_score", 0)),
        reverse=True,
    )

    rank_icons = {1: "🥇", 2: "🥈", 3: "🥉"}

    for idx, team in enumerate(leaderboard, start=1):
      t_name = roster_map.get(
          team["roster_id"], f"Team {team.get('roster_id')}"
      )
      mod_score = team.get("modified_score", 0)
      raw_score = team.get("raw_score", 0)
      delta_score = round(mod_score - raw_score, 2)
      effects = team.get("effects", [])
      gp_pts = GP_POINTS_MAP.get(idx, 0)

      icon = rank_icons.get(idx, "")

      with st.container(border=True):
        col_rank, col_details = st.columns([1, 4])

        with col_rank:
          st.markdown(
              f"<h1 style='text-align: center; font-size: 3rem; margin: 0;'>{icon} #{idx}</h1>",
              unsafe_allow_html=True,
          )
          st.markdown(
              f"<p style='text-align: center; font-weight: bold; font-size: 1.2rem; color: #ff4b4b;'>+{gp_pts} GP Pts</p>",
              unsafe_allow_html=True,
          )

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
# TAB 2: Overall Season Standings (Summed GP Points)
# -----------------------------------------------------------------------------
with tab2:
  st.header("🏆 Season-Wide Grand Prix Standings")
  st.caption("Points accumulated across all played weeks based on placement.")

  with st.spinner("Calculating season GP scores..."):
    # Aggregate GP points across all weeks 1 to selected_week
    season_totals = {r_id: 0 for r_id in roster_map.keys()}
    season_raw_pts = {r_id: 0.0 for r_id in roster_map.keys()}

    # Fetch plays across all weeks
    try:
      all_plays_res = (
          supabase.table("weekly_plays").select("*").lte("week", selected_week).execute()
      )
      all_plays = all_plays_res.data or []
    except Exception:
      all_plays = []

    for w in range(1, selected_week + 1):
      w_matchups = sleeper_api.get_league_matchups(league_id, w)
      if not w_matchups:
        continue
      w_plays = [p for p in all_plays if p.get("week") == w]
      w_calculated = scoring.calculate_modified_scores(
          w_matchups, w_plays, players_data
      )

      w_sorted = sorted(
          w_calculated,
          key=lambda t: (t.get("modified_score", 0), t.get("raw_score", 0)),
          reverse=True,
      )

      for r_rank, team in enumerate(w_sorted, start=1):
        r_id = team["roster_id"]
        gp_gained = GP_POINTS_MAP.get(r_rank, 0)
        season_totals[r_id] = season_totals.get(r_id, 0) + gp_gained
        season_raw_pts[r_id] = season_raw_pts.get(r_id, 0.0) + team.get(
            "modified_score", 0.0
        )

    # Sort overall leaderboard by GP Points descending, secondary sort by total modified fantasy score
    overall_leaderboard = sorted(
        roster_map.items(),
        key=lambda item: (season_totals.get(item[0], 0), season_raw_pts.get(item[0], 0.0)),
        reverse=True,
    )

    table_data = []
    for rank, (r_id, t_name) in enumerate(overall_leaderboard, start=1):
      table_data.append({
          "Rank": f"#{rank}",
          "Team Name": t_name,
          "Total GP Points": season_totals.get(r_id, 0),
          "Total Fantasy Points": round(season_raw_pts.get(r_id, 0.0), 2),
      })

    st.dataframe(
        table_data,
        column_config={
            "Rank": st.column_config.TextColumn("Rank", width="small"),
            "Team Name": st.column_config.TextColumn("Team", width="medium"),
            "Total GP Points": st.column_config.NumberColumn(
                "GP Points 🏎️", format="%d pts"
            ),
            "Total Fantasy Points": st.column_config.NumberColumn(
                "Fantasy Score", format="%.2f pts"
            ),
        },
        use_container_width=True,
        hide_index=True,
    )

# -----------------------------------------------------------------------------
# TAB 3: Sleeper-Style Player Database
# -----------------------------------------------------------------------------
with tab3:
  st.header("🏈 NFL Player Database")

  col_search, col_pos, col_team = st.columns([2, 1, 1])

  with col_search:
    search_query = st.text_input("🔍 Search Player Name", value="")

  with col_pos:
    pos_filter = st.selectbox(
        "Position", ["ALL", "QB", "RB", "WR", "TE", "K", "DEF"]
    )

  # Get list of unique non-empty NFL teams
  all_nfl_teams = sorted(
      list(
          set(
              info["team"]
              for info in players_data.values()
              if info.get("team")
          )
      )
  )
  with col_team:
    team_filter = st.selectbox("NFL Team", ["ALL"] + all_nfl_teams)

  # Filter player dataset
  filtered_players = []
  for p_id, p in players_data.items():
    pos = p.get("pos")
    team = p.get("team")
    name = p.get("name", "")

    if pos not in ["QB", "RB", "WR", "TE", "K", "DEF"]:
      continue
    if search_query and search_query.lower() not in name.lower():
      continue
    if pos_filter != "ALL" and pos != pos_filter:
      continue
    if team_filter != "ALL" and team != team_filter:
      continue

    filtered_players.append({
        "Player ID": p_id,
        "Name": name,
        "Position": pos,
        "NFL Team": team or "FA",
        "Age": p.get("age", "N/A"),
    })

  st.caption(f"Showing {len(filtered_players)} players")

  st.dataframe(
      filtered_players[:200],  # Limit to 200 rows for performance
      column_config={
          "Name": st.column_config.TextColumn("Player", width="medium"),
          "Position": st.column_config.TextColumn("Pos", width="small"),
          "NFL Team": st.column_config.TextColumn("Team", width="small"),
          "Player ID": st.column_config.TextColumn("ID", width="small"),
      },
      use_container_width=True,
      hide_index=True,
  )

# -----------------------------------------------------------------------------
# TAB 4: Item Inventory & Play Submission
# -----------------------------------------------------------------------------
with tab4:
  st.header("🎒 Item Inventory & Action Portal")

  if not st.session_state["authenticated"]:
    st.warning(
        "🔒 Please log in via the sidebar to view your inventory and play"
        " chaos items."
    )
  else:
    user_roster_id = st.session_state["roster_id"]

    inv_res = (
        supabase.table("team_inventory")
        .select("id, item_id, items(name, description, target_type)")
        .eq("roster_id", user_roster_id)
        .eq("is_used", False)
        .execute()
    )

    inventory = inv_res.data or []

    col_inv, col_play = st.columns([1, 1])

    with col_inv:
      st.subheader("Your Available Items")
      if not inventory:
        st.info("You currently have no unplayed items in your inventory.")
      else:
        for item in inventory:
          details = item.get("items", {})
          st.success(
              f"**{details.get('name')}** (`{item['item_id']}`)\n\n"
              f"{details.get('description')}"
          )

    with col_play:
      st.subheader("Play an Item")
      if not inventory:
        st.write("Acquire items to play them during the week.")
      else:
        item_options = {
            f"{i['items']['name']} (ID: {i['id']})": i for i in inventory
        }
        selected_item_label = st.selectbox(
            "Select Item to Play", list(item_options.keys())
        )
        chosen_inv_item = item_options[selected_item_label]
        target_type = chosen_inv_item["items"]["target_type"]

        target_player_id = None
        target_nfl_team = None

        if target_type == "PLAYER":
          player_search = {
              f"{info['name']} ({info['pos']} - {info['team']})": p_id
              for p_id, info in players_data.items()
              if info.get("pos") in ["QB", "RB", "WR", "TE", "K", "DEF"]
          }
          selected_player = st.selectbox(
              "Target Player", sorted(list(player_search.keys()))
          )
          target_player_id = player_search[selected_player]

        elif target_type == "TEAM":
          nfl_teams = sorted(
              list(
                  set(
                      info["team"]
                      for info in players_data.values()
                      if info.get("team")
                  )
              )
          )
          target_nfl_team = st.selectbox("Target NFL Team", nfl_teams)

        elif target_type == "SELF":
          st.info("This item applies directly to your team roster.")

        if st.button("🚀 Confirm & Play Item", type="primary"):
          try:
            supabase.table("weekly_plays").insert({
                "week": selected_week,
                "roster_id": user_roster_id,
                "item_id": chosen_inv_item["item_id"],
                "target_player_id": target_player_id,
                "target_nfl_team": target_nfl_team,
            }).execute()

            supabase.table("team_inventory").update({"is_used": True}).eq(
                "id", chosen_inv_item["id"]
            ).execute()

            st.success(
                "🎉 Item played successfully! Updating leaderboard..."
            )
            st.rerun()

          except Exception as e:
            st.error(f"Failed to play item: {e}")