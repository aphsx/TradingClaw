"""Unified client: web scraping (default) or The Odds API (optional)."""

from __future__ import annotations

from datetime import datetime

from config import Settings
from models import RawEvent


def pick_events(pool: list[RawEvent], category: str, count: int) -> list[RawEvent]:
    filtered = [e for e in pool if e.sport_category == category]
    return filtered[:count]


class ScrapeClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._backend = None

    def _get_backend(self):
        if self._backend is not None:
            return self._backend
        source = self._settings.scrape_source
        if source == "odds_api":
            from odds_client import OddsApiClient

            self._backend = OddsApiClient(self._settings)
        else:
            from sources.oddsportal import OddsPortalScraper

            self._backend = OddsPortalScraper(
                headless=self._settings.headless,
                fetch_match_bookies=self._settings.fetch_match_bookies,
            )
        return self._backend

    def close(self) -> None:
        if self._backend is not None:
            self._backend.close()

    def collect_upcoming(
        self, now: datetime, window_end: datetime
    ) -> list[RawEvent]:
        backend = self._get_backend()
        if hasattr(backend, "collect_upcoming"):
            from config import ESPORTS_SPORT_KEYS, FOOTBALL_SPORT_KEYS

            pool: list[RawEvent] = []
            seen: set[str] = set()
            for key in FOOTBALL_SPORT_KEYS + ESPORTS_SPORT_KEYS:
                for ev in backend.fetch_sport_odds(key):
                    if ev.id not in seen and now < ev.commence_at <= window_end:
                        seen.add(ev.id)
                        pool.append(ev)
            pool.sort(key=lambda e: e.commence_at)
            return pool
        return backend.fetch_upcoming(
            ["football", "esports"], window_end, now
        )

    def fetch_tracked(
        self,
        tracked_rows: list[dict],
        external_ids: set[str],
    ) -> list[RawEvent]:
        backend = self._get_backend()
        if hasattr(backend, "fetch_sport_odds"):
            sport_keys = list({r["sport_key"] for r in tracked_rows})
            return backend.fetch_tracked_events(sport_keys, external_ids)
        cat_map = {r["external_id"]: r["sport_category"] for r in tracked_rows}
        return backend.fetch_events_by_ids(external_ids, cat_map)
