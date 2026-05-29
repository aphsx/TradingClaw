# TradingClaw — Odds Arbitrage Tracker

ระบบเก็บค่าน้ำ **โดย scraping** จาก [OddsPortal](https://www.oddsportal.com/) (Playwright, **ไม่ต้องมี API key**) ทุก **1 ชั่วโมง** เป็นเวลา **7 วัน** สำหรับ:

- ฟุตบอล **10 คู่**
- Esports **10 คู่**

ใช้วิเคราะห์พฤติกรรมน้ำก่อนแข่ง (steam ทีมเต็ง, arbitrage ข้ามเจ้า ฯลฯ)

**Supabase project:** `bjmqwerbslpdbfrkedqj`

---

## 1. ล้าง DB และสร้าง schema ใหม่

Supabase MCP ใน Cursor ยังไม่ได้เชื่อม — ทำอย่างใดอย่างหนึ่ง:

### วิธี A — SQL Editor (แนะนำ)

1. เปิด [Supabase Dashboard](https://supabase.com/dashboard/project/bjmqwerbslpdbfrkedqj/sql/new)
2. วางเนื้อหาทั้งไฟล์ `supabase/migrations/20260529100000_odds_arbitrage_tracking.sql`
3. กด **Run** (จะลบทุกตารางใน `public` แล้วสร้างใหม่)

### วิธี B — Supabase MCP

เพิ่ม MCP ใน Cursor:

```json
{
  "mcpServers": {
    "supabase": {
      "url": "https://mcp.supabase.com/mcp?project_ref=bjmqwerbslpdbfrkedqj"
    }
  }
}
```

จากนั้นให้ agent รัน `apply_migration` ด้วยไฟล์ migration เดียวกัน

---

## 2. ตั้งค่า environment

```powershell
cd c:\Users\aphis\Desktop\TradingClaw
copy .env.example .env
```

แก้ `.env`:

| ตัวแปร | ที่มา |
|--------|--------|
| `SUPABASE_URL` | Project Settings → API |
| `SUPABASE_SERVICE_ROLE_KEY` | Project Settings → API (service_role) |
| `SCRAPE_SOURCE` | `oddsportal` (ค่าเริ่มต้น, ไม่ต้อง API) หรือ `odds_api` |
| `LOCAL_STORAGE` | `1` = เก็บ SQLite ที่ `data/odds_local.db` |
| `ODDS_API_KEY` | ใช้เมื่อ `SCRAPE_SOURCE=odds_api` เท่านั้น |

---

## 3. ติดตั้งและรัน scraper

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r scraper\requirements.txt

# เลือก 20 คู่ + snapshot แรก
python -m scraper.main init

# scrape ครั้งเดียว (ทดสอบ)
python -m scraper.main scrape

# รันทุก 1 ชม. ตลอดสัปดาห์ (เปิดทิ้งไว้)
python -m scraper.main loop
```

### รันด้วย Windows Task Scheduler (ทางเลือก)

- Program: `C:\Users\aphis\Desktop\TradingClaw\.venv\Scripts\python.exe`
- Arguments: `-m scraper.main scrape`
- Trigger: ทุก 1 ชั่วโมง
- Start in: `C:\Users\aphis\Desktop\TradingClaw`

---

## 4. ดูผลใน Supabase

ตัวอย่าง query อยู่ใน `supabase/queries/analysis.sql`

| ตาราง | ความหมาย |
|--------|-----------|
| `tracked_events` | 20 คู่ที่ติดตาม |
| `odds_snapshots` | น้ำรายชั่วโมงต่อเจ้า×ผล |
| `arbitrage_opportunities` | จังหวะ arb เมื่อ Σ(1/ราคาดีที่สุด) < 1 |
| `odds_movement_summary` | % เปลี่ยนจาก snapshot แรก→ล่าสุด |
| `scrape_runs` | log แต่ละรอบ |

---

## ข้อจำกัดสำคัญ

1. **แหล่งข้อมูล:** OddsPortal (เว็บเปรียบเทียบราคา) — ไม่ใช่เว็บพนันไทยโดยตรง; บางภูมิภาคเห็นเจ้ามือน้อย
2. **รายการแมตช์:** ได้ consensus 1X2 จากหน้ารายการ + เจ้ามือรายแมตช์เมื่อเปิดได้ (ขึ้นกับ region)
3. **ช้ากว่า API:** ครั้งแรกต้องติดตั้ง Chromium (`playwright install chromium`)
4. **Arbitrage ในตารางเป็น theoretical** — ยังไม่หัก commission, limit, ความล่าช้า

---

## โครงสร้าง

```
TradingClaw/
├── supabase/migrations/   # schema (ลบ public + สร้างใหม่)
├── supabase/queries/      # SQL วิเคราะห์
├── scraper/               # Python hourly collector
├── .env.example
└── README.md
```
