# Fantasy Football Kart App Logic

This document explains how the main app in [app.py](app.py) works, in plain terms.

## 1. App startup and global setup

At the top of [app.py](app.py), the app initializes the Streamlit page and connects to Supabase.

- It sets the UI page title and icon using `st.set_page_config(...)`.
- It defines `init_supabase()` and creates a cached Supabase client using secrets from `st.secrets`.
- PIN hashing and validation are handled by `database/auth_service.py` using salted PBKDF2, with legacy SHA-256 hash compatibility.

The app uses the Supabase service-role key from Streamlit secrets on the Python server. RLS is enabled and anon has no direct table access; service-role operations bypass RLS and must remain behind the app's checks.

## 2. Session state and login flow

The app uses Streamlit session state to track:

- `authenticated`
- `roster_id`
- `team_name`
- `user_id`
- `active_league_id`

If these values are not present, it initializes them to `False` and `None`.

The sidebar is the login and league setup area:

- The manager enters a Sleeper username. The app resolves it to a Sleeper `user_id` and checks for initialized roster records.
- Existing managers choose a league/team and enter the PIN stored for that roster.
- If no app roster exists, eligible leagues are listed for the selected Sleeper season. The season selector defaults to the current NFL season and includes prior seasons back to 2022. Only Sleeper commissioners can initialize a league, except `sierrabellum`, who is explicitly allowed.
- Initialization also requires `LEAGUE_SETUP_CODE` from Streamlit secrets. A server-side service-role client imports the league's rosters and generates unique manager PINs; only salted PIN hashes are stored.
- The generated PINs are shown once to the initializing commissioner for out-of-band sharing. The app does not verify control of Sleeper usernames.
- Five incorrect PINs for a Sleeper user trigger a 15-minute lockout tracked in the server-only `login_attempts` table.
- Managers can select “Remember this browser for 30 days.” The browser stores a random cookie token; Supabase stores only its hash, user ID, selected league, and expiry. Logging out revokes the server-side token and removes the cookie.
- An authenticated manager can choose among their initialized leagues in the sidebar. Logging out clears the active session.

When logged in, the sidebar shows the current team name and includes a logout button that clears the session state and reruns the app.

## 3. Week selector and league context

The app exposes a sidebar widget for picking the NFL week:

- `selected_week = st.sidebar.number_input(...)`
- It is limited to 1 through 18.

The active league ID comes from the authenticated manager's selected roster, not a single fixed secret.

This means the rest of the app calculates data for whatever week the user selects.

## 4. Loading live fantasy data

The app loads three primary data sources:

### a) NFL player database

It calls `sleeper_api.get_nfl_players()` and stores the result in `players_data`.

This is used later for:
- scoring player points,
- filtering players in the player table,
- understanding team assignments and player metadata.

### b) League matchups for the selected week

It calls:

- `sleeper_api.get_league_matchups(league_id, selected_week)`

This returns raw Sleeper matchup data for the selected week.

### c) Weekly item play data from Supabase

It queries Supabase for `weekly_plays` rows matching the current week.

This data tells the app which players/items were used by each roster and what they targeted. Queries and writes for rosters, weekly plays, inventory, and events include the active `league_id` so separate leagues remain isolated.

## 5. Scoring modifier flow

The app calls the scoring function:

- `scoring.calculate_modified_scores(raw_matchups, weekly_plays, players_data)`

This is the main scoring engine for affecting scores with custom item mechanics. The function is defined in [game_logic/scoring.py](game_logic/scoring.py).

The scoring logic:

- looks at all matchup scores,
- checks for active item effects like freeze, double team, and bench boost,
- modifies the players’ and teams’ points accordingly,
- returns a list of matchup records with:
  - `roster_id`
  - `raw_score`
  - `modified_score`
  - `effects`

The app then sorts these modified results to create rankings.

## 6. Roster and avatar mapping

After computing scores, the app builds:

- `roster_map`: roster ID -> team name
- `avatar_map`: roster ID -> avatar URL

It gets roster names from Supabase and player avatars from Sleeper APIs.

These maps are used to display the team name and profile picture next to race standings.

## 7. Main UI layout

The app creates five tabs:

1. Weekly Standings
2. Overall GP Standings
3. Item Inventory & Play Portal
4. Players Database
5. Commissioner

This is the main dashboard structure.

## 8. Tab 1: Weekly race standings

This tab shows the current week’s standings after item effects have been applied.

The flow is:

- take `calculated_matchups`
- sort by highest `modified_score` first
- assign rank positions and GP points based on placement
- build a row for each team with:
  - rank badge,
  - avatar,
  - team name,
  - raw score,
  - modified score,
  - active effects,
  - GP points awarded

This is the main “race leaderboard” experience.

## 9. Tab 2: Overall Grand Prix standings

This tab calculates cumulative season rankings.

The flow is:

- loop through each week up to the selected week,
- fetch the week’s matchup data,
- apply scoring modifications,
- sort each week by modified score,
- award GP points based on placement,
- accumulate totals by roster ID,
- display season-wide leaderboard.

This is how the app tracks long-term championship standings.

## 10. Tab 3: Item inventory and action portal

This is the most game-like part of the app.

The code checks the current weekday and then determines whether to generate weekly item drops. If the user is authenticated:

- it fetches the roster’s inventory from `team_inventory`
- it looks up the item details (name, description, target type)
- it decides how the item should be played based on the item’s target type

### Supported target types

The app supports different kinds of item targeting:

- `ROSTER_PLAYER`: select one of the user’s own rostered players
- `OPPONENT`: target another manager
- `NFL_TEAM`: target an NFL team
- `FREE_TEXT`: custom text input for a player or target name

When the user submits a selection, the app inserts a record into `weekly_plays` and marks the item as used in `team_inventory`.

This makes the item system function as a weekly fantasy-game mechanic layered on top of the league standings.

## 11. Tab 4: Player database

This tab loads a pruned player database from `data/pruned_players.json`.

The app:

- reads the JSON file,
- formats player data into a DataFrame,
- calculates rookie status,
- sorts by team and depth chart order,
- adds filter controls for:
  - name,
  - team,
  - position,
  - rookie status,
  - current status

It then styles players with a greyed-out appearance if they are on IR and displays the final table as a Streamlit dataframe.

This is a read-only roster/player inspection tool.

## 12. Tab 5: Commissioner tools

This tab is a placeholder UI for future commissioner functionality. It currently only shows a message indicating that admin features are pending specification.

## 13. Overall app architecture

The app combines a few layers:

- Streamlit UI layer: all visible tabs and forms
- `database/auth_service.py`: PIN hashing/verification and persistent login rate limiting
- `database/league_service.py`: roster lookup, commissioner league discovery, and league initialization persistence
- `game_logic/item_service.py`: league-scoped event checks and weekly item-drop persistence
- `helpers/sleeper_api.py`: Sleeper account, league, roster, and player data
- Supabase service client: persistent roster, inventory, weekly plays, and event data
- custom scoring logic: modifying raw fantasy points using item effects

`app.py` owns Streamlit widgets and session-state transitions. `database/`, `game_logic/`, and `helpers/` separate persistence, game rules, and external API support. Service modules can be tested independently of the rendered UI. `game_logic/item_engine.py` remains as a compatibility import for weekly drop generation.

The app behaves like a dashboard and game engine for a fantasy football / Mario Kart-themed custom league system.

## 14. High-level mental model

The app is essentially running a custom fantasy league simulation where:

- raw NFL/scoring data comes from Sleeper,
- weekly item usage is tracked in Supabase,
- custom item effects are applied by the scoring engine,
- standings are displayed as a playable league leaderboard,
- managers interact with items and selections through the app.

That is the core logic behind everything in [app.py](app.py).
