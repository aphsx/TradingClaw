# หา EA บน MQL5 — ใกล้ “XAU Aggression Burst”

ภาพใช้ชื่อ **XAU Aggression Burst EA v3.00** — อาจไม่ขายสาธารณะบน Market ใต้ชื่อนี้ตรงๆ

## ลำดับการหา

### 1. แหล่งเดียวกับคนโพสต์ภาพ (ได้ชัวร์สุด)

- กลุ่ม Line/Telegram/Facebook ที่แชร์ภาพ
- ถามชื่อไฟล์ `.ex5` และเวอร์ชัน v3.00
- ระวังของปลอม — ทดบน Demo ก่อน

### 2. MQL5 Market

1. ไป [mql5.com/en/market](https://www.mql5.com/en/market)
2. ค้นหาคำเหล่านี้ทีละคำ:

| คำค้น | เหตุผล |
|-------|--------|
| `XAU scalper` | ทอง scalping |
| `aggression` | ใกล้ชื่อ burst |
| `velocity gold` | มี metric velocity |
| `basket profit` | ปิดรวม basket |
| `burst EA` | aggression burst |

3. กรอง: **MetaTrader 5**, รีวิว, มีภาพ dashboard
4. ดู **Inputs** ในคำอธิบายว่ามี:
   - Velocity / Tick rate
   - Basket target
   - Recovery / grid

### 3. MQL5 Code Base (ฟรี — ต้อง compile)

- [mql5.com/en/code](https://www.mql5.com/en/code)
- ค้นหา `scalper XAUUSD`
- ดาวน์โหลด `.mq5` → เปิด MetaEditor → **Compile** → ได้ `.ex5`

### 4. เช่า vs ซื้อ

| แบบ | ข้อดี | ข้อเสีย |
|-----|-------|---------|
| ซื้อขาด | ใช้ยาว | แพง |
| เช่า | ถูกลอง | หมดอายุ |
| ฟรี | ไม่เสียเงิน | คุณภาพไม่แน่นอน |

## เช็คก่อนซื้อ/ใช้

- [ ] รันบน **Demo Cent** ได้
- [ ] รองรับ symbol `XAUUSDc` หรือ `XAUUSD`
- [ ] มี **M15** ใน timeframe ที่แนะนำ
- [ ] อธิบาย Recovery ชัด
- [ ] ไม่บังคับ DLL แปลกๆ ถ้าไม่ไว้ใจ

## ถ้าไม่มีชื่อตรง — EA ทดแทนได้ถ้ามี

- Fixed lot 0.01
- Basket / group close ที่กำไร $
- Scalping สั้น + velocity หรือ momentum filter
- แสดง panel บน chart

## ติดตั้งหลังได้ไฟล์

ดู [03-install-ea.md](03-install-ea.md)
