import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        locale="en-US",
    )
    page = ctx.new_page()
    page.goto(
        "https://www.oddsportal.com/matches/football/",
        wait_until="networkidle",
        timeout=90000,
    )
    page.wait_for_timeout(4000)
    info = page.evaluate(
        """() => {
        const rows = document.querySelectorAll('[class*="eventRow"]');
        const out = [];
        for (const el of [...rows].slice(0, 3)) {
            const ma = el.querySelector('a[href*="/football/"]');
            const ps = [...el.querySelectorAll('p, span, div')].map(x => x.innerText.trim()).filter(t => /^\\d\\.\\d+$/.test(t));
            out.push({
                matchHref: ma ? ma.href : null,
                matchText: ma ? ma.innerText.trim() : el.innerText.trim().slice(0,120),
                decimalOdds: ps.slice(0,5),
            });
        }
        return {rowCount: rows.length, samples: out};
    }"""
    )
    print(json.dumps(info, indent=2))
    browser.close()
