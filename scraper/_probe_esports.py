from playwright.sync_api import sync_playwright

urls = [
    "https://www.oddsportal.com/esports/",
    "https://www.oddsportal.com/esports/counter-strike/",
    "https://www.oddsportal.com/matches/esports/",
    "https://www.oddsportal.com/esports/counter-strike-2/",
]
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    for u in urls:
        page.goto(u, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(2000)
        n = page.locator("[class*='eventRow']").count()
        print(u, "rows", n)
    b.close()
