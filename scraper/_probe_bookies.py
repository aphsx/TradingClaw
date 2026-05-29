import json
from playwright.sync_api import sync_playwright

url = "https://www.oddsportal.com/football/h2h/morocco-8Moi5uId/senegal-zkknLuM0/#QJbIJBqA:1X2;2"

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.goto(url, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(3000)
    try:
        page.get_by_text("Show more", exact=False).first.click(timeout=3000)
        page.wait_for_timeout(2000)
    except Exception:
        pass
    data = page.evaluate(
        """() => {
        const bookies = [];
        document.querySelectorAll('[class*="border-black-better"], [class*="bookmaker"], table tr').forEach(el => {
            const t = el.innerText.trim();
            if (t.length > 5 && t.length < 180 && /\\d\\.\\d{2}/.test(t)) bookies.push(t.replace(/\\n/g, ' | '));
        });
        return [...new Set(bookies)];
    }"""
    )
    print("count", len(data))
    for line in data[:20]:
        print(line)
    b.close()
