"""SQLite storage when Supabase keys are unavailable (LOCAL_STORAGE=1)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from models import RawEvent

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "odds_local.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookmakers (
  key TEXT PRIMARY KEY,
  title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tracked_events (
  id TEXT PRIMARY KEY,
  external_id TEXT UNIQUE NOT NULL,
  sport_key TEXT NOT NULL,
  sport_category TEXT NOT NULL,
  home_team TEXT NOT NULL,
  away_team TEXT NOT NULL,
  commence_at TEXT NOT NULL,
  match_url TEXT,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS scrape_runs (
  id TEXT PRIMARY KEY,
  run_type TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  events_polled INTEGER DEFAULT 0,
  snapshots_inserted INTEGER DEFAULT 0,
  arbitrage_found INTEGER DEFAULT 0,
  error_message TEXT
);
CREATE TABLE IF NOT EXISTS odds_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scrape_run_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  bookmaker_key TEXT NOT NULL,
  market_key TEXT NOT NULL,
  outcome_name TEXT NOT NULL,
  price_decimal REAL NOT NULL,
  point REAL,
  scraped_at TEXT NOT NULL,
  hours_before_kickoff REAL
);
CREATE TABLE IF NOT EXISTS arbitrage_opportunities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scrape_run_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  market_key TEXT NOT NULL,
  best_implied_sum REAL NOT NULL,
  profit_margin_pct REAL NOT NULL,
  outcomes TEXT NOT NULL,
  detected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS odds_movement_summary (
  event_id TEXT NOT NULL,
  bookmaker_key TEXT NOT NULL,
  market_key TEXT NOT NULL,
  outcome_name TEXT NOT NULL,
  first_price REAL NOT NULL,
  last_price REAL NOT NULL,
  first_scraped_at TEXT NOT NULL,
  last_scraped_at TEXT NOT NULL,
  pct_change REAL NOT NULL,
  snapshot_count INTEGER NOT NULL,
  PRIMARY KEY (event_id, bookmaker_key, market_key, outcome_name)
);
"""


class LocalClient:
    def __init__(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(DB_PATH)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(tracked_events)")}
        if "match_url" not in cols:
            self._conn.execute("ALTER TABLE tracked_events ADD COLUMN match_url TEXT")
            self._conn.commit()

    def table(self, name: str) -> "_Table":
        return _Table(self._conn, name)

    def commit(self) -> None:
        self._conn.commit()


class _Table:
    def __init__(self, conn: sqlite3.Connection, name: str) -> None:
        self._conn = conn
        self._name = name
        self._data: list[dict] | None = None

    def insert(self, row: dict | list[dict]) -> "_Table":
        rows = row if isinstance(row, list) else [row]
        if not rows:
            return self
        keys = list(rows[0].keys())
        cols = ", ".join(keys)
        placeholders = ", ".join("?" for _ in keys)
        sql = f"INSERT INTO {self._name} ({cols}) VALUES ({placeholders})"
        for r in rows:
            self._conn.execute(sql, [r[k] for k in keys])
        self._conn.commit()
        self._data = rows
        return self

    def upsert(self, rows: list[dict], on_conflict: str) -> "_Table":
        for r in rows:
            if self._name == "tracked_events":
                self._conn.execute(
                    """INSERT INTO tracked_events
                    (id, external_id, sport_key, sport_category, home_team, away_team, commence_at, match_url, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(external_id) DO UPDATE SET
                      active=excluded.active, match_url=excluded.match_url""",
                    [
                        r.get("id", str(uuid4())),
                        r["external_id"],
                        r["sport_key"],
                        r["sport_category"],
                        r["home_team"],
                        r["away_team"],
                        r["commence_at"],
                        r.get("match_url", ""),
                        1 if r.get("active", True) else 0,
                    ],
                )
            elif self._name == "bookmakers":
                self._conn.execute(
                    "INSERT OR REPLACE INTO bookmakers (key, title) VALUES (?, ?)",
                    [r["key"], r["title"]],
                )
            elif self._name == "odds_movement_summary":
                self._conn.execute(
                    """INSERT OR REPLACE INTO odds_movement_summary
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    [
                        r["event_id"],
                        r["bookmaker_key"],
                        r["market_key"],
                        r["outcome_name"],
                        r["first_price"],
                        r["last_price"],
                        r["first_scraped_at"],
                        r["last_scraped_at"],
                        r["pct_change"],
                        r["snapshot_count"],
                    ],
                )
        self._conn.commit()
        cur = self._conn.execute(f"SELECT * FROM {self._name}")
        self._data = [dict(row) for row in cur.fetchall()]
        return self

    def update(self, data: dict) -> "_Query":
        return _Query(self._conn, self._name, data)

    def select(self, cols: str) -> "_Query":
        return _Query(self._conn, self._name, None, cols)

    def execute(self) -> "_Result":
        return _Result(self._data or [])


class _Query:
    def __init__(
        self,
        conn: sqlite3.Connection,
        table: str,
        update: dict | None = None,
        select: str = "*",
    ) -> None:
        self._conn = conn
        self._table = table
        self._update = update
        self._select = select
        self._filters: list[tuple[str, Any]] = []
        self._order: str | None = None

    def eq(self, col: str, val: Any) -> "_Query":
        self._filters.append((f"{col} = ?", val))
        return self

    def lt(self, col: str, val: Any) -> "_Query":
        self._filters.append((f"{col} < ?", val))
        return self

    def order(self, col: str) -> "_Query":
        self._order = col
        return self

    def execute(self) -> "_Result":
        if self._update is not None:
            sets = ", ".join(f"{k}=?" for k in self._update)
            vals = list(self._update.values())
            where, wvals = self._where()
            self._conn.execute(
                f"UPDATE {self._table} SET {sets}{where}", vals + wvals
            )
            self._conn.commit()
            return _Result([])
        sql = f"SELECT {self._select} FROM {self._table}"
        where, wvals = self._where()
        sql += where
        if self._order:
            sql += f" ORDER BY {self._order}"
        cur = self._conn.execute(sql, wvals)
        return _Result([dict(r) for r in cur.fetchall()])

    def _where(self) -> tuple[str, list]:
        if not self._filters:
            return "", []
        parts, vals = [], []
        for frag, v in self._filters:
            parts.append(frag)
            vals.append(v)
        return " WHERE " + " AND ".join(parts), vals


class _Result:
    def __init__(self, data: list) -> None:
        self.data = data


def make_client(_settings: Any = None) -> LocalClient:
    return LocalClient()


def start_run(client: LocalClient, run_type: str) -> UUID:
    rid = uuid4()
    client.table("scrape_runs").insert(
        {
            "id": str(rid),
            "run_type": run_type,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
        }
    )
    return rid


def finish_run(client: LocalClient, run_id: UUID, **kwargs: Any) -> None:
    client.table("scrape_runs").update(
        {
            "status": kwargs.get("status", "success"),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "events_polled": kwargs.get("events_polled", 0),
            "snapshots_inserted": kwargs.get("snapshots_inserted", 0),
            "arbitrage_found": kwargs.get("arbitrage_found", 0),
            "error_message": kwargs.get("error_message"),
        }
    ).eq("id", str(run_id)).execute()


def upsert_bookmakers(client: LocalClient, keys: dict[str, str]) -> None:
    if keys:
        client.table("bookmakers").upsert(
            [{"key": k, "title": t} for k, t in keys.items()], on_conflict="key"
        )


def insert_tracked_events(client: LocalClient, events: list[RawEvent]) -> list[dict]:
    rows = [
        {
            "id": str(uuid4()),
            "external_id": e.id,
            "sport_key": e.sport_key,
            "sport_category": e.sport_category,
            "home_team": e.home_team,
            "away_team": e.away_team,
            "commence_at": e.commence_at.isoformat(),
            "active": True,
        }
        for e in events
    ]
    client.table("tracked_events").upsert(rows, on_conflict="external_id")
    if not events:
        return []
    placeholders = ",".join("?" * len(events))
    cur = client._conn.execute(
        f"SELECT * FROM tracked_events WHERE external_id IN ({placeholders})",
        [e.id for e in events],
    )
    return [dict(r) for r in cur.fetchall()]


def get_active_tracked(client: LocalClient) -> list[dict]:
    return (
        client.table("tracked_events")
        .select("*")
        .eq("active", 1)
        .order("commence_at")
        .execute()
        .data
    )


def deactivate_past_events(client: LocalClient, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    client.table("tracked_events").update({"active": 0}).lt(
        "commence_at", now.isoformat()
    ).eq("active", 1).execute()


def insert_snapshots(
    client: LocalClient,
    run_id: UUID,
    event_map: dict[str, UUID],
    events: list[RawEvent],
    scraped_at: datetime,
) -> tuple[int, dict[str, str]]:
    import json

    rows: list[dict] = []
    bookmakers: dict[str, str] = {}
    for ev in events:
        event_uuid = event_map.get(ev.id)
        if not event_uuid:
            continue
        hours_before = (ev.commence_at - scraped_at).total_seconds() / 3600.0
        for bm in ev.bookmakers:
            bookmakers[bm["key"]] = bm["title"]
            for market in bm.get("markets") or []:
                for outcome in market.get("outcomes") or []:
                    rows.append(
                        {
                            "scrape_run_id": str(run_id),
                            "event_id": str(event_uuid),
                            "bookmaker_key": bm["key"],
                            "market_key": market["key"],
                            "outcome_name": outcome["name"],
                            "price_decimal": outcome["price"],
                            "point": outcome.get("point"),
                            "scraped_at": scraped_at.isoformat(),
                            "hours_before_kickoff": round(hours_before, 3),
                        }
                    )
    if rows:
        client.table("odds_snapshots").insert(rows)
    return len(rows), bookmakers


def insert_arbitrage_rows(
    client: LocalClient, run_id: UUID, rows: list[dict[str, Any]]
) -> int:
    import json

    if not rows:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        r["scrape_run_id"] = str(run_id)
        r["outcomes"] = json.dumps(r["outcomes"])
        r["detected_at"] = now
    client.table("arbitrage_opportunities").insert(rows)
    return len(rows)


def refresh_movement_summary(client: LocalClient) -> None:
    snaps = (
        client.table("odds_snapshots")
        .select(
            "event_id, bookmaker_key, market_key, outcome_name, price_decimal, scraped_at"
        )
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
        series.sort(key=lambda x: x["scraped_at"])
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
        client.table("odds_movement_summary").upsert(upserts, on_conflict="")


# Re-export for main.py dynamic import
__all__ = [
    "make_client",
    "start_run",
    "finish_run",
    "upsert_bookmakers",
    "insert_tracked_events",
    "get_active_tracked",
    "deactivate_past_events",
    "insert_snapshots",
    "insert_arbitrage_rows",
    "refresh_movement_summary",
]
