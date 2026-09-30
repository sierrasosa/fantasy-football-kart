# 🏎️ Fantasy Football Kart League

A custom, item-based "Mario Kart" chaos engine for Sleeper fantasy football leagues. Built with Streamlit, Supabase, and Python.

---

## 📌 Features

* **Sleeper API Integration:** Pulls real-time rosters, matchups, and live scores.
* **Chaos Item System:** Play game-changing items like freezing opponent players, boosting team points, or starting bench players.
* **Manager Authentication:** Sleeper username lookup and per-manager PINs, with an optional 30-day remembered browser session.
* **Supabase Backend:** League-scoped rosters, item inventories, events, and weekly submissions.

## 📁 Project Layout

- `database/`: Supabase schema/migrations, persistence services, and seed commands
- `game_logic/`: scoring, timing, and item rules/operations
- `helpers/`: Sleeper API integration
- `data/`: item rules workbook and player snapshots
- Root: Streamlit entry point, deployment configuration, requirements, and documentation

---

## 📋 Development Roadmap & Status

* [x] **Step 1: Environment & Dependencies**
  * Configured Python virtual environment (`ffenv`).
* [x] **Step 2: Database Setup & RLS (Supabase)**
  * Schema supports independent leagues with composite league-scoped keys.
  * RLS is enabled; the app uses the server-only service-role key and anon has no table access.
* [x] **Step 3: Core Logic & Secrets**
  * Sleeper API client lives in `helpers/`; scoring and item rules live in `game_logic/`.
  * Configured `.streamlit/secrets.toml` with `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_KEY`, and `SLEEPER_LEAGUE_ID`.
* [x] **Step 4: Seed Real League Data**
  * Commissioners initialize eligible leagues with a setup code; each manager receives a unique generated PIN.
* [x] **Step 5: Local Verification**
  * Verified local Streamlit app execution and team login authentication.
* [ ] **Step 6: Hosting & Deployment**
  * Commit and push local repository to GitHub.
  * Connect repository to Streamlit Community Cloud and set production secrets.
* [x] **Step 7: Multi-League Support**
  * Managers select an active initialized league in the sidebar.

---

## 🛠️ Setup & Local Development

### 1. Prerequisites
* Python 3.10+
* A [Supabase](https://supabase.com/) project
* A [Sleeper](https://sleeper.app/) account

### 2. Environment Configuration
For local development, create `.streamlit/secrets.toml`. On Streamlit Community Cloud, add these values under **App settings → Secrets** instead:

```toml
SUPABASE_URL = "https://your-project-ref.supabase.co"
SUPABASE_SERVICE_KEY = "your-supabase-service-role-key"
LEAGUE_SETUP_CODE = "a-long-random-secret-value"
# Optional: used by the manual roster seed command.
SLEEPER_LEAGUE_ID = "your-sleeper-league-id"
```

The Streamlit server uses `SUPABASE_SERVICE_KEY` from Python only. Never print it, commit it, or send it to browser JavaScript. The service-role key bypasses RLS, so keep database writes behind app-side checks. Rotate it immediately if it is exposed.

League initialization requires the Sleeper account to be a commissioner, except for the `sierrabellum` account, and also requires the shared setup code. Sleeper username lookup does not prove account ownership; distribute the setup code only to trusted commissioners. Login blocks an account for 15 minutes after five incorrect PINs.

### 3. Database Initial Setup

For a new database, run [database/supabase_schema.sql](database/supabase_schema.sql) in the Supabase SQL Editor. For the existing single-league database, first replace `REPLACE_WITH_EXISTING_LEAGUE_ID` in [database/supabase_migrate_multileague.sql](database/supabase_migrate_multileague.sql) with the current league ID, then run that migration once. If the database was already rebuilt or migrated before remember-browser support was added, run [database/supabase_login_sessions.sql](database/supabase_login_sessions.sql). Back up the database before migrations.

Remember-browser login stores a random bearer token in a secure, SameSite cookie and stores only its SHA-256 hash in Supabase. The cookie lasts 30 days and is revoked on logout. The Streamlit cookie component cannot mark the cookie HttpOnly, so the token is opaque but still accessible to JavaScript running on the app origin; avoid unsafe HTML and third-party scripts.

### 4. Seed Rosters & Run App

```bash
# Optional: import item and event templates from data/item_rules.xlsx
python -m database.seed_items

# Optional manual roster initialization; the app also supports setup-code initialization
python -m database.seed_rosters

# Launch Streamlit app locally
streamlit run app.py

```

---

## 🚀 Deployment (Streamlit Community Cloud)

1. Log into [share.streamlit.io](https://share.streamlit.io/).
2. Select **New app** $\rightarrow$ choose your repository and branch (`main`).
3. Set **Main file path** to `app.py`.
4. Under **Advanced settings...** $\rightarrow$ **Secrets**, add `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and `LEAGUE_SETUP_CODE`.
5. Click **Deploy!**
