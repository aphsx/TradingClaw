from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from config import ESPORTS_SPORT_KEYS, FOOTBALL_SPORT_KEYS, MARKETS, ODDS_API_BASE, REGIONS, Settings


from models import RawEvent  # noqa: F401 — re-export


class OddsApiClient:
    def __init__(self, settings: Settings) -> None:
        self._key = settings.odds_api_key
        self._client = httpx.Client(timeout=60.0)

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        p = {"apiKey": self._key, **(params or {})}
        r = self._client.get(f"{ODDS_API_BASE}{path}", params=p)
        r.raise_for_status()
        remaining = r.headers.get("x-requests-remaining")
        if remaining is not None:
            print(f"  [odds-api] requests remaining: {remaining}")
        return r.json()

    def fetch_sport_odds(self, sport_key: str) -> list[RawEvent]:
        data = self._get(
            f"/sports/{sport_key}/odds",
            {
                "regions": REGIONS,
                "markets": MARKETS,
                "oddsFormat": "decimal",
            },
        )
        events: list[RawEvent] = []
        category = "esports" if sport_key.startswith("esports_") else "football"
        for row in data:
            commence = datetime.fromisoformat(
                row["commence_time"].replace("Z", "+00:00")
            )
            events.append(
                RawEvent(
                    id=row["id"],
                    sport_key=row["sport_key"],
                    sport_category=category,
                    home_team=row["home_team"],
                    away_team=row["away_team"],
                    commence_at=commence,
                    bookmakers=row.get("bookmakers") or [],
                )
            )
        return events

    def collect_upcoming(
        self,
        sport_keys: list[str],
        window_end: datetime,
        now: datetime | None = None,
    ) -> list[RawEvent]:
        now = now or datetime.now(timezone.utc)
        out: list[RawEvent] = []
        seen: set[str] = set()
        for key in sport_keys:
            try:
                batch = self.fetch_sport_odds(key)
            except httpx.HTTPStatusError as e:
                print(f"  skip {key}: {e.response.status_code}")
                continue
            for ev in batch:
                if ev.id in seen:
                    continue
                if ev.commence_at <= now:
                    continue
                if ev.commence_at > window_end:
                    continue
                seen.add(ev.id)
                out.append(ev)
        out.sort(key=lambda e: e.commence_at)
        return out

    def fetch_tracked_events(
        self, sport_keys: list[str], external_ids: set[str]
    ) -> list[RawEvent]:
        """Poll only sports that have tracked events (saves API quota)."""
        found: list[RawEvent] = []
        for key in sport_keys:
            try:
                batch = self.fetch_sport_odds(key)
            except httpx.HTTPStatusError as e:
                print(f"  skip {key}: {e.response.status_code}")
                continue
            for ev in batch:
                if ev.id in external_ids:
                    found.append(ev)
        return found


def pick_events(
    pool: list[RawEvent], category: str, count: int
) -> list[RawEvent]:
    filtered = [e for e in pool if e.sport_category == category]
    return filtered[:count]
