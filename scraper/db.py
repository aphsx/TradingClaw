from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from supabase import Client, create_client

from config import Settings
from models import RawEvent


def make_client(settings: Settings) -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_key)


def start_run(client: Client, run_type: str) -> UUID:
    row = (
        client.table("scrape_runs")
        .insert({"run_type": run_type, "status": "running"})
        .execute()
    )
    return UUID(row.data[0]["id"])


def finish_run(
    client: Client,
    run_id: UUID,
    *,
    status: str,
    events_polled: int,
    snapshots_inserted: int,
    arbitrage_found: int,
    error_message: str | None = None,
) -> None:
    client.table("scrape_runs").update(
        {
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "events_polled": events_polled,
            "snapshots_inserted": snapshots_inserted,
            "arbitrage_found": arbitrage_found,
            "error_message": error_message,
        }
    ).eq("id", str(run_id)).execute()


def upsert_bookmakers(client: Client, keys: dict[str, str]) -> None:
    if not keys:
        return
    rows = [{"key": k, "title": t} for k, t in keys.items()]
    client.table("bookmakers").upsert(rows, on_conflict="key").execute()


def insert_tracked_events(client: Client, events: list[RawEvent]) -> list[dict]:
    rows = [
        {
            "external_id": e.id,
            "sport_key": e.sport_key,
            "sport_category": e.sport_category,
            "home_team": e.home_team,
            "away_team": e.away_team,
            "commence_at": e.commence_at.isoformat(),
            "match_url": getattr(e, "match_url", "") or "",
            "active": True,
        }
        for e in events
    ]
    result = (
        client.table("tracked_events")
        .upsert(rows, on_conflict="external_id")
        .execute()
    )
    return result.data


def get_active_tracked(client: Client) -> list[dict]:
    return (
        client.table("tracked_events")
        .select("*")
        .eq("active", True)
        .order("commence_at")
        .execute()
        .data
    )


def deactivate_past_events(client: Client, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    client.table("tracked_events").update({"active": False}).lt(
        "commence_at", now.isoformat()
    ).eq("active", True).execute()


def insert_snapshots(
    client: Client,
    run_id: UUID,
    event_map: dict[str, UUID],
    events: list[RawEvent],
    scraped_at: datetime,
) -> tuple[int, dict[str, str]]:
    """Returns (count, bookmaker_key -> title)."""
    rows: list[dict[str, Any]] = []
    bookmakers: dict[str, str] = {}
    for ev in events:
        event_uuid = event_map.get(ev.id)
        if not event_uuid:
            continue
        hours_before = (ev.commence_at - scraped_at).total_seconds() / 3600.0
        for bm in ev.bookmakers:
            bkey = bm["key"]
            bookmakers[bkey] = bm["title"]
            for market in bm.get("markets") or []:
                mkey = market["key"]
                for outcome in market.get("outcomes") or []:
                    rows.append(
                        {
                            "scrape_run_id": str(run_id),
                            "event_id": str(event_uuid),
                            "bookmaker_key": bkey,
                            "market_key": mkey,
                            "outcome_name": outcome["name"],
                            "price_decimal": outcome["price"],
                            "price_american": None,
                            "point": outcome.get("point"),
                            "scraped_at": scraped_at.isoformat(),
                            "hours_before_kickoff": round(hours_before, 3),
                        }
                    )
    if not rows:
        return 0, bookmakers
    # Batch insert (Supabase default chunk ~1000)
    chunk = 500
    for i in range(0, len(rows), chunk):
        client.table("odds_snapshots").insert(rows[i : i + chunk]).execute()
    return len(rows), bookmakers


def insert_arbitrage_rows(
    client: Client, run_id: UUID, rows: list[dict[str, Any]]
) -> int:
    if not rows:
        return 0
    for r in rows:
        r["scrape_run_id"] = str(run_id)
    client.table("arbitrage_opportunities").insert(rows).execute()
    return len(rows)


def refresh_movement_summary(client: Client) -> None:
    """Recompute first/last price per event×bookmaker×outcome from snapshots."""
    snaps = (
        client.table("odds_snapshots")
        .select(
            "event_id, bookmaker_key, market_key, outcome_name, price_decimal, scraped_at"
        )
        .order("scraped_at")
        .execute()
        .data
    )
    buckets: dict[tuple, list] = {}
    for s in snaps:
        k = (
            s["event_id"],
            s["bookmaker_key"],
            s["market_key"],
            s["outcome_name"],
        )
        buckets.setdefault(k, []).append(s)
    upserts = []
    for key, series in buckets.items():
        if len(series) < 2:
            continue
        first, last = series[0], series[-1]
        fp, lp = float(first["price_decimal"]), float(last["price_decimal"])
        pct = ((lp - fp) / fp) * 100.0 if fp else 0.0
        upserts.append(
            {
                "event_id": key[0],
                "bookmaker_key": key[1],
                "market_key": key[2],
                "outcome_name": key[3],
                "first_price": fp,
                "last_price": lp,
                "first_scraped_at": first["scraped_at"],
                "last_scraped_at": last["scraped_at"],
                "pct_change": round(pct, 4),
                "snapshot_count": len(series),
            }
        )
    if upserts:
        client.table("odds_movement_summary").upsert(
            upserts,
            on_conflict="event_id,bookmaker_key,market_key,outcome_name",
        ).execute()
