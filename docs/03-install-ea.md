# ขั้นที่ 3 — ติดตั้ง EA + แปะ XAUUSDc M15

ชื่อในภาพ: **XAU Aggression Burst EA v3.00**

## 3.1 หา EA

ดูรายละเอียด: [find-ea-mql5.md](find-ea-mql5.md)

แหล่งที่มักได้ไฟล์:

- กลุ่ม/คนที่โพสต์ภาพ (ไฟล์ `.ex5` หรือ `.mq5` ให้ compile)
- [MQL5 Market](https://www.mql5.com/en/market) ค้นหา `aggression burst`, `XAU scalper`, `velocity scalper`

## 3.2 ติดตั้งไฟล์ .ex5

1. MT5 → **File → Open Data Folder**
2. เปิดโฟลเดอร์ `MQL5\Experts\`
3. Copy ไฟล์ `XAU_Aggression_Burst_EA.ex5` (ชื่อจริงตามที่ได้รับ)
4. ปิด/เปิด MT5 หรือคลิกขวา Navigator → **Refresh**
5. ใน **Navigator → Expert Advisors** ต้องเห็นชื่อ EA

## 3.3 แปะ EA บนบัญชี #1

1. เปิด chart **XAUUSDc**, timeframe **M15**
2. ลาก EA จาก Navigator ลงบน chart
3. หน้าต่าง Properties:

| แท็บ | ตั้งค่า |
|------|--------|
| Common | [x] Allow Algo Trading, [x] Allow live trading |
| Inputs | ดู [ea-settings-checklist.md](ea-settings-checklist.md) — Lot **0.01**, Basket Target **3.00** |

4. กด **OK**
5. มุมขวาบน chart ต้องมี **ชื่อ EA + smiley** (ไม่ใช่กากบาท)

## 3.4 แปะ EA บนบัญชี #2

ทำซ้ำขั้น 3.3 บน **MT5 หน้าต่างบัญชี #2** (chart XAUUSDc M15)

> ใช้ **Inputs เหมือนกัน** ทั้งสองบัญชีเพื่อเปรียบผลได้

## 3.5 ตรวจว่า EA ทำงาน

| สัญญาณ | แปลว่า |
|--------|--------|
| Smiley บน chart | EA รันอยู่ |
| Cross / กากบาท | ปิด Algo หรือ error — ดูแท็บ **Experts** ด้านล่าง |
| Dashboard มุมซ้ายบน | แสดง Mode, Signal, Velocity, Basket (ตามภาพ) |

แท็บ **Experts** ถ้ามี error บ่อยๆ:

- `trade context busy` — รอสักครู่
- `not enough money` — ทุนไม่พอสำหรับ lot
- `invalid stops` — ปรับ SL/TP ใน Inputs

## 3.6 ตั้งค่าหลักให้ตรงภาพ

ค่าที่เห็นบน dashboard ตัวอย่าง:

- **Mode:** SINGLE (เริ่มต้น)
- **Basket Target:** 3.00
- **Lot:** 0.01
- **ChopLock:** OFF (ถ้ามีใน Inputs)
- **EquityStop:** เปิดตามความเสี่ยง (แนะนำเปิดแม้ยอมเสี่ยง)

รายละเอียดทุกช่อง: [ea-settings-checklist.md](ea-settings-checklist.md)

---

**เสร็จขั้นนี้เมื่อ:** EA smiley บน XAUUSDc M15 ทั้งบัญชี #1 และ #2

**ถัดไป:** [04-multi-charts.md](04-multi-charts.md)
