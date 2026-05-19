# ตั้งค่า EA — Properties ทีละช่อง

ใช้เมื่อลาก EA ลง chart → หน้าต่าง **Properties**  
ชื่อช่องจริงอาจต่างตามเวอร์ชัน EA — จับคู่ตามความหมาย

## แท็บ Common

| ช่อง | ตั้งค่า |
|------|--------|
| Long & Short | เปิดทั้งซื้อและขาย (ถ้า EA รองรับ) |
| Allow Algo Trading | เปิด |
| Allow live trading | เปิด (ตอน Real) |
| Confirm before trade | ปิด (ให้ EA อัตโนมัติ) |

## แท็บ Inputs — ตรงภาพ (เป้าหมาย)

| ช่อง (ชื่อโดยประมาณ) | ค่าแนะนำ | หมายเหตุ |
|---------------------|----------|----------|
| Lot / Fixed Lot | **0.01** | ตรง history ในภาพ |
| Basket Target / Target Profit | **3.00** | ปิดรวมที่ $3 |
| Max Spread (points) | 250–300 ทอง, 15–20 ยูโร | ไม่เข้าถ้า spread กว้าง |
| Magic Number | คนละเลขต่อ chart | แยกออเดอร์ |
| ATR Period | ค่า default EA | กรอง volatility |
| Velocity Threshold | default หรือสูงขึ้นถ้าเข้าบ่อยเกิน | เงื่อนไข burst |
| TickRate Min | default | |
| Score threshold | default | BUY vs SELL |
| ChopLock | **OFF** ตามภาพ | ไม่บล็อก sideway |
| EquityStop | **ON** แนะนำ | หยุดเมื่อ equity ต่ำ |
| Max Recovery Steps | **2–3** ถ้ายอมเสี่ยง | สูง = อันตราย |
| Recovery Mode / Ladder | ตาม EA | RECOVERY ในภาพ |
| Show Dashboard | **ON** | เห็น Mode, Signal, Basket |

## แท็บ Inputs — BTC (v3.01 ในภาพ)

ถ้าใช้เวอร์ชัน CFD_Absorption:

| ช่อง | ภาพตัวอย่าง |
|------|-------------|
| TrendBias | PERIOD_M15 |
| SigGate | FORCE_FLOW |
| FootprintMode | AUTO |
| DeltaP | 4 |
| Engine | AGGRESSIVE |
| LotMode EntryRR | MANUAL |
| Recovery | LADDER |

อ่านคู่มือ EA ก่อนปรับ — ไม่แนะนำกับทุน $100 จนกว่าทองจะ demo ดี

## หลังกด OK

1. มุมขวาบน: **smiley**
2. Dashboard แสดง:
   - `Mode: SINGLE | Signal: SELL`
   - `Spread: ... | ATR: ... | Velocity: ... | TickRate: ...`
   - `Score BUY: x | SELL: y`
   - `Basket: ... | Target: 3.00`

## Copy settings ไปบัญชี #2

1. คลิกขวา chart บัญชี #1 → **Template → Save Template**
2. เปิด chart บัญชี #2 → **Load Template**
3. หรือจด Inputs แล้วใส่มือให้ตรงกัน

## บันทึก Inputs ของคุณ (กรอกหลังตั้งจริง)

```text
EA ชื่อไฟล์: _______________________
เวอร์ชัน: v3.00 / อื่น

บัญชี #1:
  Lot: _____  Basket: _____  MaxSpread XAU: _____
  Recovery steps: _____  EquityStop: _____

บัญชี #2:
  (เหมือนหรือต่าง): _______________________
```
