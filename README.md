# Regime Detection Trading System v3
## Docker + MySQL + Redis + Next.js + Socket.IO + Binance API (Spot & Futures)

ระบบเทรด Crypto ที่ใช้ ML ตรวจจับ Market Regime แล้วสลับ Strategy อัตโนมัติ
พร้อม **real-time position monitoring** ผ่าน Socket.IO และ **ข้อมูลเทรดจริงจาก Binance**

**รองรับทั้ง Binance Spot และ Binance Futures**

---

## สิ่งที่เปลี่ยนจาก v2

| เรื่อง | v2 | v3 |
|--------|----|----|
| Position monitor | ไม่มี | Redis + Socket.IO real-time |
| ข้อมูล order | คำนวณเอง | จาก Binance API จริง (order ID, fill price, commission) |
| Backtest ↔ Live | ปนกัน | แยก `source` column ชัดเจน |
| Dashboard เปิดใหม่ | มี trade ปลอม | ว่างเปล่า จนกว่าจะเทรดจริง |
| SL/TP | คำนวณใน engine | ยิง order จริงบน Binance แล้ว monitor fill |
| Manual positions | ไม่มี | แสดง manual orders & holdings จาก Binance |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Docker Compose                                    │
├────────────┬────────────┬───────────────┬───────────────────────────┤
│  MySQL 8   │  Redis 7   │  Trading      │  Next.js Dashboard :3000   │
│  :3306     │  :6379     │  Engine       │                           │
│            │            │  (Python)     │  Live Trades              │
│ positions  │ pos:open:* │               │  Open Positions           │
│ signals    │ monitor:*  │  Main Loop:   │    - Bot (auto)           │
│ candles    │            │  ① Fetch      │    - Manual (Binance)     │
│ regimes    │ Pub/Sub:   │  ② Features   │  Backtest History         │
│ equity     │ positions  │  ③ Regime ML  │                           │
│ logs       │            │  ④ Signals    │  Binance Details:         │
│            │            │  ⑤ Order      │  · Order ID               │
│            │            │               │  · Fill Price             │
│            │            │  Socket.IO    │  · Commission             │
│            │            │  :8080        │  · Manual Orders          │
│            │            │               │  · Holdings               │
│            │            │  HTTP API     │                           │
│            │            │  :8081        │                           │
└────────────┴────────────┴───────────────┴───────────────────────────┘
```

---

## Quick Start

```bash
# 1. เริ่ม infra (MySQL + Redis)
docker compose -f docker-compose.infra.yml up -d

# 2. รัน trading engine  (Terminal 1)
cd trading-engine
python main.py

# 3. รัน dashboard  (Terminal 2)
cd dashboard
npm run dev

# 4. เปิด Dashboard
open http://localhost:3000
```

---

## Trading Modes

```bash
# Live: ดึงข้อมูลจริง + ยิง order จริง (Spot หรือ Futures)
TRADING_MODE=live docker compose up

# Paper: ดึงข้อมูลจริง + ไม่ยิง order (จำลอง)
TRADING_MODE=paper docker compose up

# Backtest: synthetic data + backtest only
TRADING_MODE=backtest docker compose up
```

### Binance Futures Configuration

```bash
# .env file
USE_FUTURES=true      # ใช้ Futures API แทน Spot
BINANCE_FUTURES_BASE_URL=https://demo-fapi.binance.com
TRADING_MODE=live     # ยิง order จริง (บน Demo URL = เงินปลอม)
```

**Futures API Endpoints:**
- Demo: `https://demo-fapi.binance.com`
- Mainnet: `https://fapi.binance.com`

**Spot API Endpoints:**
- Mainnet: `https://api.binance.com`

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
- **Real-time updates** ผ่าน Socket.IO

### 2. Open Positions
แบ่งเป็น 2 ส่วน:

#### Bot Positions (auto-managed)
- **Real-time** จาก Redis (auto-refresh ทุก 10 วินาที)
- แสดง: Entry fill price, current price, unrealized PnL, SL/TP levels
- ค่า fee จริงจาก Binance
- Bot จะจัดการ SL/TP ให้อัตโนมัติ

#### Manual Positions & Orders (Binance)
- แสดงคำสั่งที่เปิดไว้ด้วยตนเอง (ไม่ผ่านบอท)
- **Open Orders**: คำสั่งที่ยังรอ fill
- **Holdings**: สินทรัพย์ที่ถืออยู่
- **Recent Trades**: ประวัติเทรด 24 ชม. ล่าสุด
- ข้อมูลจาก Binance API โดยตรง (อ่านอย่างเดียว)

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

## Socket.IO Events

Dashboard รับข้อมูล real-time ผ่าน Socket.IO (port 8080):

| Event | Description |
|-------|-------------|
| `equity_update` | อัพเดท equity, capital, unrealized PnL |
| `position_update` | Position open/close/update |
| `regime_update` | เปลี่ยน market regime |
| `balance_update` | อัพเดท balance |

## HTTP API Endpoints

Trading Engine เปิด HTTP API (port 8081):

| Endpoint | Description |
|----------|-------------|
| `GET /manual-positions` | Manual positions, open orders, recent trades |
| `GET /health` | Health check |

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

## [WARN] สำคัญ

1. **เปลี่ยน API Key** ใน `.env` ก่อนใช้งาน!
2. **Futures Demo Trading:**
   - ตั้งค่า `USE_FUTURES=true`
   - ตั้งค่า `BINANCE_FUTURES_BASE_URL=https://demo-fapi.binance.com`
   - ใช้ API keys จาก Binance Demo Trading
3. **Spot Demo Trading:**
   - ตั้งค่า `USE_FUTURES=false`
   - ใช้ endpoint `https://api.binance.com`
4. ระบบเหมาะสำหรับ **Demo account** หรือ **Paper mode** ก่อน
5. ทดสอบ backtest ให้ดีก่อนเทรดจริง
6. Crypto trading มีความเสี่ยงสูง
