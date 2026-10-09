CREATE TABLE IF NOT EXISTS public.player_score_inputs (
    league_id TEXT NOT NULL,
    week INTEGER NOT NULL CHECK (week BETWEEN 1 AND 18),
    player_key TEXT NOT NULL,
    player_id TEXT,
    player_name TEXT NOT NULL,
    points NUMERIC NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (league_id, week, player_key)
);

ALTER TABLE public.player_score_inputs ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.player_score_inputs FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.player_score_inputs TO service_role;
