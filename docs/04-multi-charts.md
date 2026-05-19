# ขั้นที่ 4 — แปะ EA หลาย Chart (ภาพ 2)

หลังตั้งทองบนทั้ง 2 บัญชีแล้ว ขยายตามภาพหลายสินทรัพย์

## 4.1 ลำดับแนะนำ (spread ต่ำ → สูง)

| ลำดับ | Symbol | Timeframe | หมายเหตุ |
|-------|--------|-----------|----------|
| 1 | `XAUUSDc` | M15 | ทำแล้วในขั้น 3 |
| 2 | `EURUSDc` | M15 | spread ~8–10 |
| 3 | `XAGUSDc` | M15 | คู่ทอง |
| 4 | `USDJPYc` | M15 | |
| 5 | `BTCUSDc` | M15 | spread สูง — ตั้ง Max Spread ใน EA ถ้ามี |

## 4.2 วิธีแปะแต่ละ chart

1. Market Watch → เปิด chart symbol ใหม่
2. ตั้ง **M15**
3. ลาก **EA ตัวเดียวกัน** ลง chart
4. Inputs:
   - Lot **0.01** (หรือต่ำกว่าถ้า EA แยก per symbol)
   - Basket Target **3.00** ต่อ chart (แต่ละ chart มี basket ของตัวเอง)
5. ตรวจ smiley ทุก chart

## 4.3 บัญชี #1 vs #2

| แนวทาง | เมื่อไหร่ใช้ |
|--------|-------------|
| Mirror ทุก chart ทั้ง 2 บัญชี | ตรงภาพ — exposure สองเท่า |
| ทองทั้งคู่ + ยูโร/เงินแค่บัญชีเดียว | ลดความเสี่ยงทุน $100–200 |

## 4.4 สิ่งที่ EA ทำแยกต่อ chart

แต่ละ chart ไม่ sync กัน:

- **Signal** ของตัวเอง (BUY / SELL / NONE)
- **Velocity / Score** ของ symbol นั้น
- **Basket** ปิดเมื่อถึง $3 **ของ chart นั้น**

ภาพ 2 มีหลาย chart แต่ **ไม่ใช่เปิด 6 ไม้พร้อมกันทุกครั้ง** — เข้าเฉพาะเมื่อเงื่อนไข burst ผ่าน

## 4.5 BTC (v3.01 ในภาพ)

ถ้ามีเวอร์ชัน **CFD_Absorption** สำหรับ BTC:

- อาจมี FootprintMode, SigGate, DeltaP
- อ่านคู่มือ EA แยก — ซับซ้อนกว่าทอง
- ทุนเล็ก: แนะนำ **ข้าม BTC** จน demo ทอง/ยูโรดี

## 4.6 Symbol เพิ่ม (ถ้า Exness มี)

จากภาพ 2 อาจมี: USOIL, DXY — ค้นใน Symbols ถ้ามีชื่อเช่น `USOILc`, `DXYc` แล้วแปะ EA ได้เหมือนกัน

## 4.7 จำกัดจำนวน chart (ทุน $100–200)

แนะนำสูงสุด **3 chart ต่อบัญชี** ตอนเริ่ม:

- XAUUSDc + EURUSDc + XAGUSDc

เพิ่ม BTC / mirror บัญชี #2 เมื่อ demo ดีแล้ว

---

**เสร็จขั้นนี้เมื่อ:** มีอย่างน้อย 3 symbol ที่ EA smiley ทำงาน

**ถัดไป:** [05-demo-observation.md](05-demo-observation.md)
