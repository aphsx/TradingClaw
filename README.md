# Regime Detection Trading System v3
## Docker + MySQL + Redis + Next.js + Binance API

ระบบเทรด Crypto ที่ใช้ ML ตรวจจับ Market Regime แล้วสลับ Strategy อัตโนมัติ
พร้อม **real-time position monitoring** และ **ข้อมูลเทรดจริงจาก Binance**

---

## สิ่งที่เปลี่ยนจาก v2

| เรื่อง | v2 | v3 |
|--------|----|----|
| Position monitor | ไม่มี | Redis real-time (ทุก 15 วินาที) |
| ข้อมูล order | คำนวณเอง | จาก Binance API จริง (order ID, fill price, commission) |
| Backtest ↔ Live | ปนกัน | แยก `source` column ชัดเจน |
| Dashboard เปิดใหม่ | มี trade ปลอม | ว่างเปล่า จนกว่าจะเทรดจริง |
| SL/TP | คำนวณใน engine | ยิง order จริงบน Binance แล้ว monitor fill |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose                            │
├────────────┬────────────┬───────────────┬───────────────────┤
│  MySQL 8   │  Redis 7   │  Trading      │  Next.js          │
│  :3306     │  :6379     │  Engine       │  Dashboard :3000   │
│            │            │  (Python)     │                    │
│ positions  │ pos:open:* │              │  Live Trades        │
│ signals    │ monitor:*  │  Main Loop:  │  Open Positions     │
│ candles    │            │  ① Fetch     │  (auto-refresh 10s) │
│ regimes    │ Pub/Sub:   │  ② Features  │                    │
│ equity     │ positions  │  ③ Regime ML │  Backtest History   │
│ logs       │            │  ④ Signals   │  (separate tab)     │
│            │            │  ⑤ Order     │                    │
│            │            │              │  Binance Details:   │
│            │            │  Monitor:    │  · Order ID         │
│            │            │  · Price     │  · Fill Price       │
│            │            │  · SL/TP     │  · Commission       │
│            │            │  · Sync      │  · Commission Asset │
└────────────┴────────────┴───────────────┴───────────────────┘
```

---

## Quick Start

```bash
# 1. แก้ .env ใส่ API key
nano .env

# 2. Start ทุกอย่าง
docker compose up --build

# 3. เปิด Dashboard
open http://localhost:3000
```

---

## Trading Modes

```bash
# Live: ดึงข้อมูลจริง + ยิง order จริง
TRADING_MODE=live docker compose up

# Paper: ดึงข้อมูลจริง + ไม่ยิง order (จำลอง)
TRADING_MODE=paper docker compose up

# Backtest: synthetic data + backtest only
TRADING_MODE=backtest docker compose up
```

---

## Live Trading Flow

```
1. Engine เปิด → เชื่อม MySQL + Redis + Binance
2. ทุกๆ 60 วินาที:
   a. Fetch OHLCV จาก Binance
   b. คำนวณ features → ตรวจ regime
   c. Generate signals → ผ่าน fee filter
   d. ถ้ามี signal ใหม่:
      - ยิง MARKET order (entry)
      - ยิง STOP_LOSS_LIMIT order (SL)
      - ยิง TAKE_PROFIT_LIMIT order (TP)
      - บันทึก fill details จริงจาก Binance ลง MySQL
      - Publish position ลง Redis

3. Monitor thread (ทุก 15 วินาที):
   a. อัพเดทราคาล่าสุด
   b. คำนวณ Unrealized PnL ทุก position
   c. เช็คว่า SL/TP orders ถูก fill หรือยัง
   d. ถ้า filled → บันทึก exit details จริง → cancel ฝั่งตรงข้าม → ลบจาก Redis
```

---

## ข้อมูลที่เก็บจาก Binance (ไม่ใช่คำนวณเอง)

ทุก trade ที่เกิดขึ้นจะเก็บ:

| Field | Description |
|-------|-------------|
| `entry_order_id` | Binance orderId ของ entry order |
| `entry_client_oid` | Client order ID ที่เราตั้ง |
| `entry_fill_price` | ราคา fill เฉลี่ยจริง (avg of fills) |
| `entry_fill_qty` | จำนวนที่ fill จริง |
| `entry_commission` | ค่า fee จริงจาก Binance |
| `entry_commission_asset` | สกุลที่จ่าย fee (BNB, USDT, etc.) |
| `entry_raw` | Full JSON response จาก Binance |
| `exit_order_id` | Binance orderId ของ exit order |
| `exit_fill_price` | ราคา fill exit จริง |
| `exit_commission` | ค่า fee exit จริง |
| `exit_raw` | Full JSON response |

---

## Dashboard Tabs

### 1. Live Trades
- แสดง **เฉพาะ trade จริง** ที่เกิดบน Binance
- เปิดใหม่ = ว่างเปล่า (ไม่มี trade ปลอม)
- แสดง: Order ID, fill price, commission จาก Binance

### 2. Open Positions
- **Real-time** จาก Redis (auto-refresh ทุก 10 วินาที)
- แสดง: Entry fill price, current price, unrealized PnL, SL/TP levels
- ค่า fee จริงจาก Binance

### 3. Backtest History
- แยกจาก live ชัดเจน
- ข้อมูลจาก backtest runs เท่านั้น

---

## Redis Keys

| Key | Description |
|-----|-------------|
| `pos:open:{id}` | JSON ของ open position (รวม unrealized PnL) |
| `pos:open_ids` | SET ของ ID ที่ยังเปิดอยู่ |
| `monitor:last_price` | ราคาล่าสุด |
| `monitor:equity` | Equity snapshot |
| `monitor:regime` | Current regime + confidence |
| `monitor:status` | Engine status (running/error) |

---

## Access MySQL

```bash
docker exec -it regime_db mysql -utrader -ptrader_pass_2026 regime_trader

-- ดู live trades (ของจริง)
SELECT id, direction, strategy, entry_fill_price, exit_fill_price,
       entry_commission, exit_commission, pnl, exit_reason
FROM positions WHERE source='LIVE' ORDER BY entry_time DESC;

-- ดู backtest (จำลอง)
SELECT * FROM positions WHERE source='BACKTEST' LIMIT 10;

-- Regime distribution
SELECT regime_name, COUNT(*) FROM regimes GROUP BY regime_name;
```

---

## ⚠️ สำคัญ

1. **เปลี่ยน API Key** ใน `.env` ก่อนใช้งาน!
2. ระบบเหมาะสำหรับ **Demo account** หรือ **Paper mode** ก่อน
3. ทดสอบ backtest ให้ดีก่อนเทรดจริง
4. Crypto trading มีความเสี่ยงสูง
