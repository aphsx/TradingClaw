"""
Scrape OddsPortal listing pages with Playwright (no API key).

- Football: https://www.oddsportal.com/matches/football/
- Esports:  https://www.oddsportal.com/matches/esports/

List rows include consensus 1X2 (avg) odds. Per-bookmaker rows are loaded on
match pages when available (often 1+ books depending on region).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, sync_playwright

from models import RawEvent

LIST_PAGES = {
    "football": "https://www.oddsportal.com/matches/football/",
    "esports": "https://www.oddsportal.com/matches/esports/",
}

EXTRACT_ROWS_JS = """
() => {
  const rows = [...document.querySelectorAll('[class*="eventRow"]')];
  const out = [];
  for (const el of rows) {
    const matchA = [...el.querySelectorAll('a[href*="/h2h/"]')][0];
    if (!matchA) continue;
    const href = matchA.href.split('#')[0];
    const text = el.innerText.replace(/\\r/g, '');
    const lines = text.split('\\n').map(s => s.trim()).filter(Boolean);
    const odds = [...text.matchAll(/\\b(\\d\\.\\d{2})\\b/g)].map(m => parseFloat(m[1]));
    let home = '', away = '';
    const slug = href.split('/').filter(Boolean);
    const last = slug[slug.length - 1] || '';
    if (last.includes('-')) {
      const parts = last.split('-');
      if (parts.length >= 2) {
        home = parts[0].replace(/-/g, ' ');
        away = parts[parts.length - 1].replace(/-/g, ' ');
      }
    }
    const parts = matchA.innerText.split('\\n').map(s => s.trim()).filter(s => {
      if (!s || s.length < 2) return false;
      if (/^\\d+$/.test(s)) return false;
      if (/^(After Pen\\.|Today|Play Offs|1|X|2)$/i.test(s)) return false;
      if (/^[\\d\\s\\-:]+$/.test(s)) return false;
      if (/^[a-zA-Z0-9]{6,12}$/.test(s)) return false;
      return true;
    });
    if (parts.length >= 2) {
      home = parts[0];
      away = parts[parts.length - 1];
    }
    let commenceHint = '';
    for (const ln of lines) {
      if (/\\d{1,2}:\\d{2}/.test(ln) || /Today|Tomorrow|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec/i.test(ln)) {
        commenceHint = ln;
        break;
      }
    }
    out.push({
      match_url: href,
      home_team: home || 'Home',
      away_team: away || 'Away',
      commence_hint: commenceHint,
      odds: odds.slice(-3),
      raw_lines: lines.slice(0, 12),
    });
  }
  return out;
}
"""

EXTRACT_MATCH_BOOKIES_JS = """
() => {
  const bookies = [];
  const body = document.body.innerText;
  const blocks = body.split('\\n\\n');
  for (const block of blocks) {
    const lines = block.split('\\n').map(s => s.trim()).filter(Boolean);
    if (lines.length < 4) continue;
    const nums = lines.filter(l => /^\\d\\.\\d{2}$/.test(l)).map(Number);
    if (nums.length >= 2 && nums.length <= 3) {
      const name = lines.find(l => !/^\\d\\.\\d{2}$/.test(l) && l.length > 2 && l.length < 40);
      if (name && !/^(1|X|2|1X2|Bookmakers|Payout)$/i.test(name)) {
        bookies.push({ name, odds: nums });
      }
    }
  }
  return bookies.slice(0, 30);
}
"""


def _external_id(match_url: str) -> str:
    return hashlib.sha256(match_url.encode()).hexdigest()[:24]


def _parse_commence(hint: str, now: datetime) -> datetime:
    """Best-effort; listing often lacks exact kickoff UTC."""
    if not hint:
        return now + timedelta(days=1)
    lower = hint.lower()
    base = now.date()
    if "tomorrow" in lower:
        base = base + timedelta(days=1)
    time_m = re.search(r"(\d{1,2}):(\d{2})", hint)
    hour, minute = (20, 0)
    if time_m:
        hour, minute = int(time_m.group(1)), int(time_m.group(2))
    return datetime(
        base.year, base.month, base.day, hour, minute, tzinfo=timezone.utc
    )


def _consensus_bookmaker(odds: list[float]) -> dict[str, Any]:
    outcomes: list[dict[str, Any]] = []
    labels = ["Home", "Draw", "Away"] if len(odds) >= 3 else ["Home", "Away"]
    use = odds[-3:] if len(odds) >= 3 else odds[-2:]
    for label, price in zip(labels, use):
        if price > 1:
            outcomes.append({"name": label, "price": price})
    return {
        "key": "oddsportal_consensus",
        "title": "OddsPortal (consensus)",
        "markets": [{"key": "h2h", "outcomes": outcomes}],
    }


class OddsPortalScraper:
    def __init__(self, headless: bool = True, fetch_match_bookies: bool = True) -> None:
        self._headless = headless
        self._fetch_match_bookies = fetch_match_bookies
        self._playwright = None
        self._browser: Browser | None = None

    def _ensure_browser(self) -> Browser:
        if self._browser is None:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self._headless)
        return self._browser

    def close(self) -> None:
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def _scrape_list(self, page: Page, category: str) -> list[RawEvent]:
        url = LIST_PAGES[category]
        page.goto(url, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(2500)
        rows = page.evaluate(EXTRACT_ROWS_JS)
        now = datetime.now(timezone.utc)
        events: list[RawEvent] = []
        for row in rows:
            odds = row.get("odds") or []
            if len(odds) < 2:
                continue
            if re.fullmatch(r"[a-zA-Z0-9]{6,14}", row["home_team"] or ""):
                continue
            if (row["home_team"] or "").lower() in ("team", "home", "away"):
                continue
            if re.search(r"[A-Z][a-z]{0,2}[A-Z0-9]{4,}", row["away_team"] or ""):
                continue
            match_url = row["match_url"]
            eid = _external_id(match_url)
            sport_key = f"oddsportal_{category}"
            bookmakers = [_consensus_bookmaker(odds)]
            events.append(
                RawEvent(
                    id=eid,
                    sport_key=sport_key,
                    sport_category=category,
                    home_team=row["home_team"],
                    away_team=row["away_team"],
                    commence_at=_parse_commence(row.get("commence_hint", ""), now),
                    bookmakers=bookmakers,
                    match_url=match_url,
                )
            )
        return events

    def _scrape_match_bookmakers(self, page: Page, match_url: str) -> list[dict[str, Any]]:
        parsed = urlparse(match_url)
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        odds_url = base.replace("/h2h/", "/") + "#1X2;2"
        if "/h2h/" in match_url:
            odds_url = match_url.split("#")[0] + "#1X2;2"
        try:
            page.goto(odds_url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2500)
            raw = page.evaluate(EXTRACT_MATCH_BOOKIES_JS)
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for item in raw:
            name = str(item.get("name", "")).strip()
            nums = item.get("odds") or []
            if not name or len(nums) < 2:
                continue
            key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]
            labels = ["Home", "Draw", "Away"] if len(nums) >= 3 else ["Home", "Away"]
            use = nums[-3:] if len(nums) >= 3 else nums[-2:]
            outcomes = [
                {"name": lab, "price": float(p)}
                for lab, p in zip(labels, use)
                if float(p) > 1
            ]
            if outcomes:
                out.append(
                    {
                        "key": key or "book_unknown",
                        "title": name,
                        "markets": [{"key": "h2h", "outcomes": outcomes}],
                    }
                )
        return out

    def fetch_upcoming(
        self,
        categories: list[str],
        window_end: datetime,
        now: datetime | None = None,
    ) -> list[RawEvent]:
        now = now or datetime.now(timezone.utc)
        browser = self._ensure_browser()
        page = browser.new_page()
        try:
            pool: list[RawEvent] = []
            seen: set[str] = set()
            for cat in categories:
                for ev in self._scrape_list(page, cat):
                    if ev.id in seen:
                        continue
                    if ev.commence_at <= now:
                        continue
                    if ev.commence_at > window_end:
                        continue
                    seen.add(ev.id)
                    pool.append(ev)
            pool.sort(key=lambda e: e.commence_at)
            return pool
        finally:
            page.close()

    def enrich_bookmakers(self, events: list[RawEvent]) -> None:
        """Visit match pages for tracked events only (not the full listing)."""
        if not self._fetch_match_bookies or not events:
            return
        browser = self._ensure_browser()
        page = browser.new_page()
        try:
            for ev in events:
                if not ev.match_url:
                    continue
                extra = self._scrape_match_bookmakers(page, ev.match_url)
                keys = {b["key"] for b in ev.bookmakers}
                for b in extra:
                    if b["key"] not in keys:
                        ev.bookmakers.append(b)
                        keys.add(b["key"])
        finally:
            page.close()

    def fetch_events_by_ids(
        self, external_ids: set[str], category_by_id: dict[str, str] | None = None
    ) -> list[RawEvent]:
        """Re-scrape lists and filter to tracked external ids."""
        browser = self._ensure_browser()
        page = browser.new_page()
        try:
            found: list[RawEvent] = []
            cats = set((category_by_id or {}).values()) or {"football", "esports"}
            for cat in cats:
                for ev in self._scrape_list(page, cat):
                    if ev.id in external_ids:
                        found.append(ev)
            self.enrich_bookmakers(found)
            return found
        finally:
            page.close()
