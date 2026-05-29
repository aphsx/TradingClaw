import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    for url in [
        "https://www.oddsportal.com/sure-bets/",
        "https://www.oddsportal.com/esports/",
    ]:
        page.goto(url, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(3000)
        data = page.evaluate(
            """() => {
            const rows = [...document.querySelectorAll('[class*="eventRow"]')];
            const samples = rows.slice(0,2).map(el => el.innerText.trim().slice(0,250));
            return {url: location.href, rows: rows.length, samples};
        }"""
        )
        print(json.dumps(data, ensure_ascii=False, indent=2))
    browser.close()
