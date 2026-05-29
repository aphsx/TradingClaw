import json
import re
from playwright.sync_api import sync_playwright

h2h = "https://www.oddsportal.com/football/h2h/morocco-8Moi5uId/senegal-zkknLuM0/#QJbIJBqA"
m = re.search(r"#(\w+)$", h2h)
eid = m.group(1) if m else ""
url = f"https://www.oddsportal.com/football/world/{eid}/#1X2;2" if eid else h2h

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    for test in [h2h, h2h.replace("/h2h/", "/").replace("#" + eid, f"#1X2;2")]:
        page.goto(test, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(5000)
        data = page.evaluate(
            """() => {
            const out = [];
            document.querySelectorAll('[class*="odd"], [class*="border-black"], tr').forEach(el => {
                const t = el.innerText.trim();
                if (t && (t.includes('Bet') || /^\\d\\.\\d/.test(t)) && t.length < 120) out.push(t);
            });
            return {url: location.href, snippets: [...new Set(out)].slice(0,25)};
        }"""
        )
        print(json.dumps(data, ensure_ascii=False)[:2000])
    b.close()
