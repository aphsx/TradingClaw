-- Odds movement: how prices changed from first scrape to kickoff
SELECT
  te.sport_category,
  te.home_team || ' vs ' || te.away_team AS match_name,
  te.commence_at,
  oms.bookmaker_key,
  oms.outcome_name,
  oms.first_price,
  oms.last_price,
  oms.pct_change,
  oms.snapshot_count
FROM odds_movement_summary oms
JOIN tracked_events te ON te.id = oms.event_id
ORDER BY te.commence_at, oms.pct_change DESC;

-- Arbitrage opportunities detected (cross-bookmaker)
SELECT
  te.home_team || ' vs ' || te.away_team AS match_name,
  ao.detected_at,
  ao.profit_margin_pct,
  ao.best_implied_sum,
  ao.outcomes
FROM arbitrage_opportunities ao
JOIN tracked_events te ON te.id = ao.event_id
WHERE ao.profit_margin_pct > 0
ORDER BY ao.detected_at DESC;

-- Hourly line for one match (favorite steam)
SELECT
  os.scraped_at,
  os.hours_before_kickoff,
  os.bookmaker_key,
  os.outcome_name,
  os.price_decimal
FROM odds_snapshots os
JOIN tracked_events te ON te.id = os.event_id
WHERE te.home_team ILIKE '%Arsenal%'  -- change filter
  AND os.market_key = 'h2h'
ORDER BY os.scraped_at, os.bookmaker_key, os.outcome_name;

-- Best odds per outcome at each scrape hour (arb building blocks)
SELECT
  os.scrape_run_id,
  os.scraped_at,
  os.outcome_name,
  MAX(os.price_decimal) AS best_decimal,
  (SELECT bookmaker_key FROM odds_snapshots x
   WHERE x.scrape_run_id = os.scrape_run_id
     AND x.event_id = os.event_id
     AND x.outcome_name = os.outcome_name
     AND x.market_key = 'h2h'
   ORDER BY x.price_decimal DESC LIMIT 1) AS at_bookmaker
FROM odds_snapshots os
WHERE os.market_key = 'h2h'
GROUP BY os.scrape_run_id, os.scraped_at, os.event_id, os.outcome_name
ORDER BY os.scraped_at;
