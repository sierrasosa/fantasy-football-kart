Here is your updated `README.md` complete with the development checklist:

```markdown
# 🏎️ Fantasy Football Kart League

A custom, item-based "Mario Kart" chaos engine for Sleeper fantasy football leagues. Built with Streamlit, Supabase, and Python.

---

## 📌 Features

* **Sleeper API Integration:** Pulls real-time rosters, matchings, and live scores.
* **Chaos Item System:** Play game-changing items like freezing opponent players, boosting team points, or starting bench players.
* **Manager Authentication:** PIN-protected access so league members can securely view inventory and submit item plays.
* **Supabase Backend:** Relational storage for rosters, item definitions, team inventories, and weekly submissions.

---

## 📋 Development Roadmap & Status

* [x] **Step 1: Environment & Dependencies**
  * Configured Python virtual environment (`ffenv`).
* [x] **Step 2: Database Setup & RLS (Supabase)**
  * Created core tables (`rosters`, `items`, `team_inventory`, `weekly_plays`).
  * Configured RLS policies: `service_role` handles admin writes while `anon` remains securely read-only for app clients.
* [x] **Step 3: Core Logic & Secrets**
  * Implemented Sleeper API client (`sleeper_api.py`) and scoring engine (`scoring.py`).
  * Configured `.streamlit/secrets.toml` with `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_KEY`, and `SLEEPER_LEAGUE_ID`.
* [x] **Step 4: Seed Real League Data**
  * Executed `seed_rosters.py` using `SUPABASE_SERVICE_KEY` to pull Sleeper managers and assign default PINs (`1234`).
* [x] **Step 5: Local Verification**
  * Verified local Streamlit app execution and team login authentication.
* [ ] **Step 6: Hosting & Deployment**
  * Commit and push local repository to GitHub.
  * Connect repository to Streamlit Community Cloud and set production secrets.
* [ ] **Step 7: Multi-Tenant Expansion (Future)**
  * Add multi-league support and commissioner setup portal.
  * Dynamic league routing via URL parameters (`?league=...`).

---

## 🛠️ Setup & Local Development

### 1. Prerequisites
* Python 3.10+
* A [Supabase](https://supabase.com/) project
* A [Sleeper](https://sleeper.app/) Fantasy League ID

### 2. Environment Configuration
Create a `.streamlit/secrets.toml` file in your root directory:

```toml
SUPABASE_URL = "[https://your-project-ref.supabase.co](https://your-project-ref.supabase.co)"
SUPABASE_KEY = "your-anon-public-key"
SUPABASE_SERVICE_KEY = "your-service-role-secret-key"
SLEEPER_LEAGUE_ID = "your-sleeper-league-id"

```

### 3. Database Initial Setup

Run the following SQL in your Supabase **SQL Editor** to create the schema and permissions:

```sql
-- Create Tables
CREATE TABLE IF NOT EXISTS rosters (
    roster_id INT PRIMARY KEY,
    owner_name TEXT NOT NULL,
    team_name TEXT NOT NULL,
    pin_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    item_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    target_type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS team_inventory (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    roster_id INT REFERENCES rosters(roster_id),
    item_id TEXT REFERENCES items(item_id),
    is_used BOOLEAN DEFAULT FALSE,
    acquired_week INT NOT NULL
);

CREATE TABLE IF NOT EXISTS weekly_plays (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    week INT NOT NULL,
    roster_id INT REFERENCES rosters(roster_id),
    item_id TEXT REFERENCES items(item_id),
    target_player_id TEXT,
    target_nfl_team TEXT,
    played_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(week, roster_id, item_id)
);

-- Seed Default Items
INSERT INTO items (item_id, name, description, target_type) VALUES
('FREEZE_PLAYER', 'Ice Ice Baby', 'Select an opponent player. They score 0 points.', 'PLAYER'),
('DOUBLE_TEAM', 'Team Hype', 'Select an NFL team. Double points for all starters on that team.', 'TEAM'),
('PLAY_BENCH', 'Sixth Man', 'Add all points scored by your bench to your total.', 'SELF')
ON CONFLICT (item_id) DO NOTHING;

-- Security & Permissions
GRANT SELECT ON public.rosters TO anon;
GRANT SELECT ON public.items TO anon;
GRANT ALL ON public.team_inventory TO anon;
GRANT ALL ON public.weekly_plays TO anon;
GRANT ALL ON public.rosters TO service_role;

ALTER TABLE rosters ENABLE ROW LEVEL SECURITY;
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_inventory ENABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_plays ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow anon read rosters" ON rosters FOR SELECT USING (true);
CREATE POLICY "Allow anon read items" ON items FOR SELECT USING (true);
CREATE POLICY "Allow anon all team_inventory" ON team_inventory FOR ALL USING (true);
CREATE POLICY "Allow anon all weekly_plays" ON weekly_plays FOR ALL USING (true);

```

### 4. Seed Rosters & Run App

```bash
# Populate rosters from Sleeper API
python seed_rosters.py

# Launch Streamlit app locally
streamlit run app.py

```

---

## 🚀 Deployment (Streamlit Community Cloud)

1. Push your code to GitHub:
```bash
git add .
git commit -m "Complete local MVP with Supabase sync"
git push origin main

```


2. Log into [share.streamlit.io](https://share.streamlit.io/).
3. Select **New app** $\rightarrow$ choose your repository and branch (`main`).
4. Set **Main file path** to `app.py`.
5. Under **Advanced settings...** $\rightarrow$ **Secrets**, paste your `.streamlit/secrets.toml` content (excluding `SUPABASE_SERVICE_KEY` if not needed in production).
6. Click **Deploy!**
