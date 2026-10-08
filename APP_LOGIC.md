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

The scoring logic starts with Sleeper's team score, then adjusts starter points
for team/division byes and supercharges, Superstar, and Snow Game/Dome Game.
Snow Game/Dome Game affects only the roster's RBs and WRs: the selected
position receives 2x and the other of those two positions receives 0.5x;
other positions are unchanged.
Mushroom, Hyperflex, Ultraflex (for NFL players in the player database), and
Golden Mushroom add eligible player points. Bullet Bill uses the chosen
player's adjusted points ten times; Smash Ball replaces the team's score with
its chosen dream lineup, ignoring team/division bye effects for that lineup.
Recall replaces one current starter's score with that player's score from the
previous week.
Scores return with `roster_id`, `raw_score`, `modified_score`, and an `effects`
breakdown.

Master Ball trades, Shell/Triple Shell transfers, non-NFL Ultraflex players,
and league-wide scoring events still need scoring implementation.
Those pending item mechanics are called out in the effects breakdown rather
than silently changing a score.

The app then sorts these modified results to create rankings.

## 6. Roster and avatar mapping

After computing scores, the app builds:

- `roster_map`: roster ID -> team name
- `avatar_map`: roster ID -> avatar URL

It gets roster names from Supabase and player avatars from Sleeper APIs.

These maps are used to display the team name and profile picture next to race standings.

## 7. Main UI layout

The app creates four tabs:

1. Weekly Standings
2. Overall GP Standings
3. Strategize
4. Commissioner

This is the main dashboard structure.

## 8. Tab 1: Weekly race standings

This tab shows the current week’s standings after item effects have been applied.

The flow is:

- take `calculated_matchups`
- show NFL teams targeted by team/division Bye and Supercharge items
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

## 10. Tab 3: Strategize

Strategize shows the manager's roster followed by the NFL player database. The
roster identifies starters and bench players with distinct role labels and
shows each player's score after implemented modifiers. Starter labels include
the assigned league lineup slot (for example, `FLEX 1 · RB`); bench labels
continue to show the player's position. Starters are ordered by lineup slot:
QB, RB, WR, TE, FLEX, K, and DEF, with numbered slots in ascending order;
bench players follow. Effect icons appear after affected player names in the
roster and player database: 🚫 bye (shown as `0x`), ✨ supercharge, 🍄 mushroom,
❄️ snow game, 🏟️ dome game, 🔄 Recall, ♾️ Hyperflex/Ultraflex, ⭐ Superstar,
🚀 Bullet Bill, and 🪩 Smash Ball. Master Ball has no icon. Shell icons are not
shown until the item identifies a specific affected player. The database
supports name, team, position, and current owner filters. Injury statuses also show
icons while retaining their text: ✅ Active, ❓ Questionable, ⚠️ Doubtful,
❌ Out, 🏥 IR, and ⛔ Inactive. The player database does not shade rows based on
injury status. Eligible rookies show 🐣 during Rookie of the Week.
The player database omits its Rookie column and instead shows each player's
current-week roster owner, or `Free Agent` if the player is not on a league
roster.

The sidebar contains the item selection controls. Managers can test a selection
to preview its existing player modifier labels on the roster and player database;
testing does not write to Supabase or change scores. Locking in a selection
persists it in `weekly_plays` and marks the inventory item as used.

The bottom of the sidebar has a “Use test timing setting” toggle, off by default.
When off, timing messages, item-detail visibility, drop week, and drop eligibility
use the live NFL week and Los Angeles local day. When on, the test week/day
selectors override those values; simulating Tuesday or later can generate and
persist drops for the simulated week. With test timing enabled, lock-in is
available on simulated Tuesday and Wednesday even when they differ from live
timing; the selection is saved for the simulated week. In live mode, lock-in is
available Tuesday and Wednesday only. The deadline is Thursday 12:00 AM (the
start of Thursday); Thursday no longer counts forward to the next week's
deadline. Manager item details are revealed on Thursday for the active week.

After that deadline, the app checks all inventory items for the active league
and item week. Any unused item without a saved play is assigned a random valid
selection using the same item-specific eligibility rules as the manual form,
then saved as a weekly play and marked used. Items with no eligible target stay
unused, and the app reports the reason instead of recording an invalid play.
This sweep is idempotent: existing plays are not duplicated, and inventory
items with an existing play are marked used if necessary.

For a week's item odds, the app calculates cumulative GP standings through the
previous week and uses each roster's overall GP rank. A week's existing inventory
is never rerolled, even if the timing test or standings later change. Week 1 has
no item drops.

League-wide event rows in the `League-wide` item-rules sheet are occurrence odds,
not simultaneous events. When a league is initialized, the app rolls at most one
event per week using those odds and stores the selected event; unused probability
means no event that week. The database enforces one league event per week, and
`supabase_migrate_single_event_per_week.sql` resolves any existing duplicate
event rows.

## 11. Tab 4: Commissioner tools

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
