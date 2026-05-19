# Checklist รวม — EA + Exness 2 บัญชี

ติ๊ก `[x]` เมื่อทำเสร็จ

## A. บัญชีและ MT5

- [ ] สมัคร Exness + ยืนยันตัวตน (ถ้าจะใช้ Real)
- [ ] เปิดบัญชี **Cent #1** — จดเลขบัญชี + server (เช่น `Exness-MT5Real20`)
- [ ] เปิดบัญชี **Cent #2** — server **คนละตัว** (เช่น `Exness-MT5Real37`)
- [ ] ติดตั้ง MT5 จาก Exness
- [ ] Login บัญชี #1 ใน MT5 หน้าต่างที่ 1
- [ ] Login บัญชี #2 ใน MT5 หน้าต่างที่ 2 (หรือเครื่องที่ 2)
- [ ] เปิด **Algo Trading** (ปุ่มเขียว) ทั้ง 2 หน้าต่าง
- [ ] ใส่ symbol ใน Market Watch: `XAUUSDc`, `EURUSDc`, `USDJPYc`, `XAGUSDc`, `BTCUSDc`

## B. EA

- [ ] ได้ไฟล์ EA `.ex5` (XAU Aggression Burst หรือใกล้เคียง)
- [ ] Copy ไป `File → Open Data Folder → MQL5 → Experts`
- [ ] รีเฟรช Navigator → เห็น EA
- [ ] เปิด chart `XAUUSDc` timeframe **M15** บัญชี #1
- [ ] ลาก EA → อนุญาต Algo → ตั้ง Lot **0.01**, Basket **3.00**
- [ ] ทำซ้ำบน **บัญชี #2**
- [ ] มี smiley หน้า EA = ทำงาน

## C. หลาย chart

- [ ] แปะ EA บน `EURUSDc` M15 (บัญชี #1)
- [ ] แปะ EA บน `XAGUSDc` M15 (บัญชี #1)
- [ ] (ถ้าต้องการ) mirror chart เดียวกันบนบัญชี #2
- [ ] (ระวัง) `BTCUSDc` — spread สูง ตั้ง filter ใน EA ถ้ามี

## D. Demo

- [ ] รัน Demo อย่างน้อย **7 วัน**
- [ ] จดใน [docs/05-demo-observation.md](docs/05-demo-observation.md) (template มีให้)
- [ ] เข้าใจ SINGLE vs RECOVERY
- [ ] รู้ว่า Basket ปิดที่ $3 จริงไหม

## E. Real ($100–200)

- [ ] ฝากทุนที่ยอมเสียได้ทั้งก้อน
- [ ] Lot ยัง **0.01**
- [ ] เปิด Real ทีละบัญชีหรือพร้อมกันตามที่ยอมรับ exposure ได้
- [ ] ตั้ง EquityStop / max loss ใน EA ถ้ามี
