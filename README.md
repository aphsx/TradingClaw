# TradingClaw — EA + Exness (2 บัญชี)

คู่มือทำตามภาพ: **MetaTrader 5 + Exness Cent + Expert Advisor** (XAU Aggression Burst)  
ไม่มี Python / ไม่ต้อง VPS — แค่ 2 บัญชีคนละ server + แปะ EA หลาย chart

## ทุนเป้าหมาย

- Demo ก่อน 1–2 สัปดาห์
- Real: **$100–200**, lot **0.01**, Basket target **$3**

## ลำดับทำ (อ่านตามเลข)

| ขั้น | ไฟล์ | ทำอะไร |
|------|------|--------|
| 1 | [docs/01-setup-account-1.md](docs/01-setup-account-1.md) | บัญชี Exness Cent #1 + MT5 + Market Watch |
| 2 | [docs/02-setup-account-2.md](docs/02-setup-account-2.md) | บัญชี #2 คนละ server (Real20 / Real37) |
| 3 | [docs/03-install-ea.md](docs/03-install-ea.md) | หา/ติดตั้ง EA + แปะ XAUUSDc M15 |
| 4 | [docs/04-multi-charts.md](docs/04-multi-charts.md) | แปะ EA หลาย symbol |
| 5 | [docs/05-demo-observation.md](docs/05-demo-observation.md) | รัน Demo + จด Velocity / Basket / RECOVERY |
| 6 | [docs/06-go-live.md](docs/06-go-live.md) | ย้าย Real $100–200 |

## เอกสารเสริม

- [docs/ea-settings-checklist.md](docs/ea-settings-checklist.md) — ตั้งค่า EA ทีละช่อง (Properties)
- [docs/find-ea-mql5.md](docs/find-ea-mql5.md) — หา EA บน MQL5 Market
- [docs/ea-dashboard-reference.md](docs/ea-dashboard-reference.md) — ความหมายค่าบน dashboard
- [docs/lead-lag-reference.md](docs/lead-lag-reference.md) — ลิสต์ GC→XAU ฯลฯ (ความรู้ประกอบ)

## Checklist รวม

ดู [CHECKLIST.md](CHECKLIST.md) — ติ๊กทีละข้อตั้งแต่เปิดบัญชีจนถึง Real

## สิ่งที่ไม่รวมในโปรเจกต์นี้

- เขียนบอท Python / API เทรดเอง
- VPS (ไม่บังคับ — เปิด MT5 2 หน้าต่างที่บ้านได้)
