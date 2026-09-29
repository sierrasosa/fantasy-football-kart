# Fantasy Football Kart App Logic

This document explains how the main app in [app.py](app.py) works, in plain terms.

## 1. App startup and global setup

At the top of [app.py](app.py), the app initializes the Streamlit page and connects to Supabase.

- It sets the UI page title and icon using `st.set_page_config(...)`.
- It defines `init_supabase()` and creates a cached Supabase client using secrets from `st.secrets`.
- It includes a helper, `hash_pin()`, which hashes the manager PIN using SHA-256 before comparing it to a stored value.

This makes the app ready to:
- authenticate managers,
- read roster data,
- fetch weekly items and results,
- update data in Supabase.

## 2. Session state and login flow

The app uses Streamlit session state to track:

- `authenticated`
- `roster_id`
- `team_name`

If these values are not present, it initializes them to `False` and `None`.

The sidebar is the login area:

- It loads all rosters from Supabase.
- It presents a team selector and PIN field.
- If the entered PIN matches the stored hash, the user is authenticated and their roster ID and team name are saved in session state.
- If the PIN is wrong, an error is shown.

When logged in, the sidebar shows the current team name and includes a logout button that clears the session state and reruns the app.

## 3. Week selector and league context

The app exposes a sidebar widget for picking the NFL week:

- `selected_week = st.sidebar.number_input(...)`
- It is limited to 1 through 18.

The league ID is also loaded from `st.secrets["SLEEPER_LEAGUE_ID"]`.

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

This data tells the app which players/items were used by each roster and what they targeted.

## 5. Scoring modifier flow

The app calls the scoring function:

- `scoring.calculate_modified_scores(raw_matchups, weekly_plays, players_data)`

This is the main scoring engine for affecting scores with custom item mechanics. The function is defined in [scoring.py](scoring.py).

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

This tab loads a pruned player database from `pruned_players.json`.

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
- Sleeper API layer: league and player data
- Supabase layer: persistent roster, inventory, weekly plays, and event data
- custom scoring logic: modifying raw fantasy points using item effects

The app behaves like a dashboard and game engine for a fantasy football / Mario Kart-themed custom league system.

## 14. High-level mental model

The app is essentially running a custom fantasy league simulation where:

- raw NFL/scoring data comes from Sleeper,
- weekly item usage is tracked in Supabase,
- custom item effects are applied by the scoring engine,
- standings are displayed as a playable league leaderboard,
- managers interact with items and selections through the app.

That is the core logic behind everything in [app.py](app.py).
