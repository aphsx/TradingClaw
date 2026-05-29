import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(
        "https://www.oddsportal.com/matches/football/",
        wait_until="networkidle",
        timeout=90000,
    )
    page.wait_for_timeout(3000)
    info = page.evaluate(
        """() => {
        const rows = document.querySelectorAll('[class*="eventRow"]');
        const el = rows[1] || rows[0];
        if (!el) return null;
        const links = [...el.querySelectorAll('a')].map(a => ({href: a.href, t: a.innerText.trim()}));
        return {links, inner: el.innerText.trim().slice(0,300)};
    }"""
    )
    print(json.dumps(info, indent=2, ensure_ascii=False))
    browser.close()
