from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(
        "https://www.oddsportal.com/matches/football/",
        wait_until="networkidle",
        timeout=60000,
    )
    page.wait_for_timeout(3000)
    links = page.eval_on_selector_all(
        "a[href*='/football/']",
        "els => els.slice(0,15).map(e => ({href: e.href, text: e.innerText.trim().slice(0,80)}))",
    )
    print("links", len(links))
    for L in links[:8]:
        print(L)
    rows = page.locator("[class*='eventRow']").count()
    print("eventRow count", rows)
    text = page.inner_text("body")[:500]
    print("body sample:", text.replace("\n", " ")[:300])
    browser.close()
