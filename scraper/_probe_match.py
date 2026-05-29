import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(
        "https://www.oddsportal.com/football/h2h/morocco-8Moi5uId/senegal-zkknLuM0/",
        wait_until="networkidle",
        timeout=90000,
    )
    page.wait_for_timeout(3000)
    hrefs = page.evaluate(
        """() => [...document.querySelectorAll('a[href]')].map(a => a.href).filter(h => h.includes('odds') || h.includes('1X2') || h.includes('comparison'))"""
    )
    print("odds links", json.dumps(hrefs[:15], indent=2))
    if hrefs:
        page.goto(hrefs[0], wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(5000)
        txt = page.evaluate(
            """() => document.body.innerText.split('\\n').filter(l => l.trim()).slice(0,80)"""
        )
        print("body lines", txt[:40])
    browser.close()
