# ขั้นที่ 1 — บัญชี Exness Cent #1 + MT5

## 1.1 สมัคร Exness

1. ไปที่ [exness.com](https://www.exness.com) → สมัครบัญชี
2. ยืนยันอีเมล / โทรศัพท์
3. ใน Personal Area → **เปิดบัญชีใหม่**
4. เลือกประเภท: **Cent** (มิโคร/เซนต์ — symbol ลงท้าย `c`)
5. เลือกแพลตฟอร์ม: **MetaTrader 5**
6. Leverage: ตามที่ยอมรับได้ (ภาพตัวอย่างใช้ Hedge mode)
7. **จดข้อมูลนี้ไว้:**
   - เลขบัญชี (Login)
   - รหัสผ่าน trading
   - ชื่อ **Server** เต็ม (เช่น `Exness-MT5Real20` หรือ `Exness-MT5Trial7` สำหรับ demo)

> บัญชีแรกนี้จะเป็น **บัญชี #1** ในภาพ (เช่น Real20)

## 1.2 ติดตั้ง MetaTrader 5

**Windows (แนะนำ)**

1. จาก Exness PA → **Download MT5** → ติดตั้ง
2. เปิด MT5 → **File → Login to Trade Account**
3. ใส่ Login, Password, Server จากขั้น 1.1
4. กด **Login**

**Mac**

1. ดาวน์โหลด MT5 จาก Exness หรือใช้ Wine/Crossover
2. ขั้นตอน login เหมือนกัน

## 1.3 เปิด Algo Trading (บังคับ)

1. แถบเครื่องมือ MT5 → ปุ่ม **Algo Trading** ต้องเป็น **สีเขียว**
2. ถ้าเป็นสีแดง → คลิกให้เขียว
3. **Tools → Options → Expert Advisors:**
   - [x] Allow algorithmic trading
   - [x] Allow DLL imports (ถ้า EA ต้องการ — อ่านคู่มือ EA)
   - [ ] Disable trading when changing profile — ปิดถ้าไม่ต้องการ

## 1.4 Market Watch — ใส่ symbol ตามภาพ

1. กด **Ctrl+M** เปิด Market Watch
2. คลิกขวา → **Symbols** (หรือ Show All)
3. ค้นหาและเพิ่ม (ชื่ออาจต่างเล็กน้อยตาม broker):

| Symbol | หมายเหตุ |
|--------|----------|
| `XAUUSDc` | ทอง cent |
| `EURUSDc` | ยูโร |
| `USDJPYc` | เยน |
| `XAGUSDc` | เงิน |
| `BTCUSDc` | บิทคอยน์ |

4. คลิกขวา symbol → **Chart Window** เพื่อเปิดกราฟ

## 1.5 ตั้ง chart หลัก (เตรียมก่อนใส่ EA)

1. เปิด chart `XAUUSDc`
2. เปลี่ยน timeframe เป็น **M15** (15 นาที)
3. ตรวจ **Spread** มุม Market Watch (ทองมัก 200–300+ points)

## 1.6 Demo ก่อน Real (แนะนำ)

- ใน Exness PA สร้าง **Demo Cent** แยก หรือใช้บัญชี trial
- Login demo ใน MT5 ก่อนฝากเงิน Real

---

**เสร็จขั้นนี้เมื่อ:** Login MT5 ได้, Algo Trading เขียว, เห็น symbol `c` ใน Market Watch, มี chart XAUUSDc M15

**ถัดไป:** [02-setup-account-2.md](02-setup-account-2.md)
