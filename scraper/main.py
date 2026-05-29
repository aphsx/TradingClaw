"""
Odds tracking — scrape OddsPortal (no API) or The Odds API, store hourly.

  python -m scraper.main init
  python -m scraper.main scrape
  python -m scraper.main loop
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))

from arbitrage import detect_h2h_arbitrage, favorite_steam_note
from config import Settings
from scrape_client import ScrapeClient, pick_events


def _storage(settings: Settings):
    if settings.use_local:
        import local_store as storage
    else:
        import db as storage
    return storage


def _client(settings: Settings):
    s = _storage(settings)
    if settings.use_local:
        return s.make_client()
    return s.make_client(settings)


def cmd_init(settings: Settings) -> None:
    storage = _storage(settings)
    db = _client(settings)
    # Fast list scrape first (no per-match browser hops)
    fast = replace(settings, fetch_match_bookies=False)
    api = ScrapeClient(fast)
    run_id = storage.start_run(db, "init")
    now = datetime.now(timezone.utc)
    window_end = now + settings.tracking_window

    try:
        print(f"Scraping upcoming matches ({settings.scrape_source}, no API)...")
        pool = api.collect_upcoming(now, window_end)
        football = pick_events(pool, "football", settings.football_count)
        esports = pick_events(pool, "esports", settings.esports_count)

        if len(football) < settings.football_count:
            print(f"Warning: only {len(football)} football (want {settings.football_count})")
        if len(esports) < settings.esports_count:
            print(f"Warning: only {len(esports)} esports (want {settings.esports_count})")

        selected = football + esports
        if not selected:
            raise RuntimeError("No events found. Try again when more matches are listed.")

        print(f"\nSelected {len(selected)} events:")
        for e in selected:
            print(
                f"  [{e.sport_category}] {e.commence_at:%Y-%m-%d %H:%M} UTC | "
                f"{e.home_team} vs {e.away_team}"
            )

        rows = storage.insert_tracked_events(db, selected)
        event_map = {r["external_id"]: UUID(r["id"]) for r in rows}

        api.close()
        api = ScrapeClient(settings)
        polled = api.fetch_tracked(rows, set(event_map.keys()))
        scraped_at = datetime.now(timezone.utc)
        count, bms = storage.insert_snapshots(
            db, run_id, event_map, polled, scraped_at
        )
        storage.upsert_bookmakers(db, bms)
        arb = detect_h2h_arbitrage(
            polled, {k: str(v) for k, v in event_map.items()}
        )
        storage.insert_arbitrage_rows(db, run_id, arb)
        favorite_steam_note(polled)
        storage.refresh_movement_summary(db)
        storage.finish_run(
            db,
            run_id,
            status="success",
            events_polled=len(polled),
            snapshots_inserted=count,
            arbitrage_found=len(arb),
        )
        dest = "data/odds_local.db" if settings.use_local else "Supabase"
        print(f"\nInit done -> {dest}. Snapshots: {count}, arb: {len(arb)}")
    except Exception as exc:
        storage.finish_run(
            db,
            run_id,
            status="failed",
            events_polled=0,
            snapshots_inserted=0,
            arbitrage_found=0,
            error_message=str(exc),
        )
        raise
    finally:
        api.close()


def cmd_scrape(settings: Settings) -> None:
    storage = _storage(settings)
    db = _client(settings)
    api = ScrapeClient(settings)
    run_id = storage.start_run(db, "hourly")
    now = datetime.now(timezone.utc)

    try:
        storage.deactivate_past_events(db, now)
        tracked = storage.get_active_tracked(db)
        if not tracked:
            print("No active events. Run: python -m scraper.main init")
            storage.finish_run(
                db,
                run_id,
                status="failed",
                events_polled=0,
                snapshots_inserted=0,
                arbitrage_found=0,
                error_message="no active events",
            )
            return

        event_map = {r["external_id"]: UUID(r["id"]) for r in tracked}
        print(f"Hourly scrape @ {now:%Y-%m-%d %H:%M:%S} UTC — {len(tracked)} events")
        polled = api.fetch_tracked(tracked, set(event_map.keys()))
        scraped_at = datetime.now(timezone.utc)
        count, bms = storage.insert_snapshots(
            db, run_id, event_map, polled, scraped_at
        )
        storage.upsert_bookmakers(db, bms)
        arb = detect_h2h_arbitrage(
            polled, {k: str(v) for k, v in event_map.items()}
        )
        storage.insert_arbitrage_rows(db, run_id, arb)
        favorite_steam_note(polled)
        storage.refresh_movement_summary(db)
        storage.finish_run(
            db,
            run_id,
            status="success",
            events_polled=len(polled),
            snapshots_inserted=count,
            arbitrage_found=len(arb),
        )
        print(f"Done. Snapshots: {count}, arbitrage: {len(arb)}")
    except Exception as exc:
        storage.finish_run(
            db,
            run_id,
            status="failed",
            events_polled=0,
            snapshots_inserted=0,
            arbitrage_found=0,
            error_message=str(exc),
        )
        raise
    finally:
        api.close()


def cmd_loop(settings: Settings) -> None:
    print("Hourly loop (Ctrl+C to stop)...")
    while True:
        try:
            cmd_scrape(settings)
        except Exception as exc:
            print(f"Scrape error: {exc}")
        print("Sleeping 3600s...")
        time.sleep(3600)


def main() -> None:
    parser = argparse.ArgumentParser(description="Odds tracker (scrape or API)")
    parser.add_argument("command", choices=["init", "scrape", "loop"])
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "init":
        cmd_init(settings)
    elif args.command == "scrape":
        cmd_scrape(settings)
    else:
        cmd_loop(settings)


if __name__ == "__main__":
    main()
