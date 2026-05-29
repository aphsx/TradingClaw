from __future__ import annotations

from collections import defaultdict
from typing import Any

from models import RawEvent


def detect_h2h_arbitrage(
    events: list[RawEvent],
    event_uuid_by_external: dict[str, str],
    market_key: str = "h2h",
) -> list[dict[str, Any]]:
    """
    For each event, take the best decimal price per outcome across all bookmakers.
    If sum(1/odds) < 1, there is a theoretical arbitrage margin.
    """
    opportunities: list[dict[str, Any]] = []

    for ev in events:
        event_id = event_uuid_by_external.get(ev.id)
        if not event_id:
            continue

        # outcome_name -> (best_price, bookmaker_key)
        best: dict[str, tuple[float, str]] = {}

        for bm in ev.bookmakers:
            for market in bm.get("markets") or []:
                if market["key"] != market_key:
                    continue
                for outcome in market.get("outcomes") or []:
                    name = outcome["name"]
                    price = float(outcome["price"])
                    if price <= 1:
                        continue
                    prev = best.get(name)
                    if prev is None or price > prev[0]:
                        best[name] = (price, bm["key"])

        if len(best) < 2:
            continue

        implied_sum = sum(1.0 / p[0] for p in best.values())
        if implied_sum >= 1.0:
            continue

        margin_pct = (1.0 - implied_sum) * 100.0
        outcomes_detail = {
            name: {"decimal_odds": odds, "bookmaker": bk}
            for name, (odds, bk) in best.items()
        }
        opportunities.append(
            {
                "event_id": event_id,
                "market_key": market_key,
                "best_implied_sum": round(implied_sum, 8),
                "profit_margin_pct": round(margin_pct, 4),
                "outcomes": outcomes_detail,
            }
        )

    return opportunities


def favorite_steam_note(events: list[RawEvent]) -> None:
    """Log which side is shortest-priced (market favorite) per event — for manual review."""
    for ev in events:
        prices: dict[str, list[float]] = defaultdict(list)
        for bm in ev.bookmakers:
            for market in bm.get("markets") or []:
                if market["key"] != "h2h":
                    continue
                for outcome in market.get("outcomes") or []:
                    prices[outcome["name"]].append(float(outcome["price"]))
        if not prices:
            continue
        avg = {k: sum(v) / len(v) for k, v in prices.items()}
        fav = min(avg, key=avg.get)
        print(
            f"  {ev.home_team} vs {ev.away_team} | market fav (lowest avg odds): {fav}"
        )
