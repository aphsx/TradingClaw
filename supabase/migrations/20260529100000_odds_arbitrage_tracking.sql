-- Reset public schema and create odds-tracking tables for hourly multi-bookmaker scraping.
-- Apply via Supabase Dashboard → SQL Editor, or: supabase db push (after link)

DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO postgres;
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TYPE sport_category AS ENUM ('football', 'esports');

CREATE TABLE bookmakers (
  key TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  region TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tracked_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  external_id TEXT NOT NULL UNIQUE,
  sport_key TEXT NOT NULL,
  sport_category sport_category NOT NULL,
  home_team TEXT NOT NULL,
  away_team TEXT NOT NULL,
  commence_at TIMESTAMPTZ NOT NULL,
  match_url TEXT,
  selected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  active BOOLEAN NOT NULL DEFAULT true,
  CONSTRAINT tracked_events_commence_future CHECK (commence_at > selected_at - interval '1 day')
);

CREATE INDEX idx_tracked_events_commence ON tracked_events (commence_at) WHERE active;
CREATE INDEX idx_tracked_events_category ON tracked_events (sport_category) WHERE active;

CREATE TABLE scrape_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_type TEXT NOT NULL DEFAULT 'hourly'
    CHECK (run_type IN ('init', 'hourly', 'manual')),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'running'
    CHECK (status IN ('running', 'success', 'failed')),
  events_polled INT NOT NULL DEFAULT 0,
  snapshots_inserted INT NOT NULL DEFAULT 0,
  arbitrage_found INT NOT NULL DEFAULT 0,
  error_message TEXT
);

CREATE TABLE odds_snapshots (
  id BIGSERIAL PRIMARY KEY,
  scrape_run_id UUID NOT NULL REFERENCES scrape_runs (id) ON DELETE CASCADE,
  event_id UUID NOT NULL REFERENCES tracked_events (id) ON DELETE CASCADE,
  bookmaker_key TEXT NOT NULL REFERENCES bookmakers (key),
  market_key TEXT NOT NULL,
  outcome_name TEXT NOT NULL,
  price_decimal NUMERIC(12, 6) NOT NULL CHECK (price_decimal > 1),
  price_american INTEGER,
  point NUMERIC(8, 3),
  scraped_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  hours_before_kickoff NUMERIC(10, 3),
  UNIQUE (scrape_run_id, event_id, bookmaker_key, market_key, outcome_name, point)
);

CREATE INDEX idx_odds_snapshots_event_time ON odds_snapshots (event_id, scraped_at DESC);
CREATE INDEX idx_odds_snapshots_run ON odds_snapshots (scrape_run_id);
CREATE INDEX idx_odds_snapshots_bookmaker ON odds_snapshots (bookmaker_key, scraped_at DESC);

CREATE TABLE arbitrage_opportunities (
  id BIGSERIAL PRIMARY KEY,
  scrape_run_id UUID NOT NULL REFERENCES scrape_runs (id) ON DELETE CASCADE,
  event_id UUID NOT NULL REFERENCES tracked_events (id) ON DELETE CASCADE,
  market_key TEXT NOT NULL,
  best_implied_sum NUMERIC(12, 8) NOT NULL,
  profit_margin_pct NUMERIC(10, 4) NOT NULL,
  outcomes JSONB NOT NULL,
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_arbitrage_event_time ON arbitrage_opportunities (event_id, detected_at DESC);

CREATE TABLE odds_movement_summary (
  id BIGSERIAL PRIMARY KEY,
  event_id UUID NOT NULL REFERENCES tracked_events (id) ON DELETE CASCADE,
  bookmaker_key TEXT NOT NULL REFERENCES bookmakers (key),
  market_key TEXT NOT NULL,
  outcome_name TEXT NOT NULL,
  first_price NUMERIC(12, 6) NOT NULL,
  last_price NUMERIC(12, 6) NOT NULL,
  first_scraped_at TIMESTAMPTZ NOT NULL,
  last_scraped_at TIMESTAMPTZ NOT NULL,
  pct_change NUMERIC(10, 4) NOT NULL,
  snapshot_count INT NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (event_id, bookmaker_key, market_key, outcome_name)
);

-- RLS: service role bypasses; anon read-only for dashboard later
ALTER TABLE bookmakers ENABLE ROW LEVEL SECURITY;
ALTER TABLE tracked_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE scrape_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE odds_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE arbitrage_opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE odds_movement_summary ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public read bookmakers" ON bookmakers FOR SELECT USING (true);
CREATE POLICY "public read tracked_events" ON tracked_events FOR SELECT USING (true);
CREATE POLICY "public read scrape_runs" ON scrape_runs FOR SELECT USING (true);
CREATE POLICY "public read odds_snapshots" ON odds_snapshots FOR SELECT USING (true);
CREATE POLICY "public read arbitrage" ON arbitrage_opportunities FOR SELECT USING (true);
CREATE POLICY "public read movement" ON odds_movement_summary FOR SELECT USING (true);

COMMENT ON TABLE tracked_events IS '20 events (10 football + 10 esports) tracked for 1 week';
COMMENT ON TABLE odds_snapshots IS 'Hourly odds from multiple bookmakers per outcome';
COMMENT ON TABLE arbitrage_opportunities IS 'Cross-bookmaker arb when sum(1/best_odds) < 1';
