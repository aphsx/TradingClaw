# Regime Detection Trading System v2
## Docker + Next.js Dashboard + MySQL + Binance API

ระบบเทรด Crypto อัจฉริยะที่ใช้ Machine Learning ตรวจจับ Market Regime
แล้วสลับ Strategy ให้เหมาะสมอัตโนมัติ พร้อม Dashboard แบบ Real-time

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Docker Compose                     │
├──────────────┬──────────────┬───────────────────────┤
│  MySQL 8.0   │  Trading     │  Next.js Dashboard    │
│  Port: 3306  │  Engine      │  Port: 3000           │
│              │  (Python)    │  (React + Recharts)   │
│  - candles   │              │                       │
│  - regimes   │  - Backtest  │  - Equity Curve       │
│  - signals   │  - Live Loop │  - Trade Log          │
│  - positions │  - ML Model  │  - Position Monitor   │
│  - equity    │  - Binance   │  - Regime Display     │
│  - logs      │    API       │  - Strategy Stats     │
└──────────────┴──────────────┴───────────────────────┘
```

## Quick Start

```bash
# 1. Clone / unzip the project
cd regime-trader-pro

# 2. Edit .env with your Binance API keys
nano .env

# 3. Start everything
docker compose up --build

# 4. Open Dashboard
# http://localhost:3000
```

## Services

### MySQL Database (Port 3306)
เก็บข้อมูลทั้งหมด:
- `candles` - ข้อมูลราคา OHLCV
- `regimes` - ผล regime detection (Trending/Ranging/Volatile)
- `signals` - สัญญาณเทรดที่ generate ได้
- `positions` - ตำแหน่งเปิด/ปิด + PnL
- `equity_curve` - equity over time
- `backtest_runs` - ประวัติ backtest
- `system_log` - log ระบบ

### Trading Engine (Python)
ใจกลางของระบบ:
- **Regime Detector** - Random Forest ML จำแนก market regime
- **3 Strategies** - Trend (EMA Cross), Range (BB+RSI), Volatile (Momentum)
- **Fee Filter** - กรอง trade ที่ expected profit < 3× fee
- **Risk Manager** - Position sizing, max drawdown, daily loss limit
- **Binance API** - ดึงข้อมูล + ยิง order

### Next.js Dashboard (Port 3000)
หน้าจอ monitoring:
- **Overview** - Key metrics, equity curve, PnL chart, regime pie
- **Trades** - รายละเอียดทุก trade
- **Positions** - Monitor open positions แบบ real-time

## Trading Modes

```bash
# Backtest (default) - ใช้ synthetic/historical data
TRADING_MODE=backtest docker compose up

# Live Trading - เทรดจริงบน Binance
TRADING_MODE=live docker compose up

# Paper Trading - signals only, ไม่ยิง order
TRADING_MODE=paper docker compose up
```

## Commands (Standalone, no Docker)

```bash
cd trading-engine

# Install
pip install -r requirements.txt

# Backtest
python main.py --mode backtest

# Test API
python main.py --mode test-api

# Live
python main.py --mode live
```

## File Structure

```
regime-trader-pro/
├── docker-compose.yml         # Orchestration
├── .env                       # API keys + config
├── db/
│   └── init.sql               # MySQL schema (auto-run)
├── trading-engine/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config.py              # All parameters
│   ├── main.py                # Entry point
│   ├── core/
│   │   ├── features.py        # Technical indicators
│   │   ├── regime_detector.py # ML regime classifier
│   │   └── risk_manager.py    # Position sizing + risk
│   ├── strategies/
│   │   └── strategies.py      # Trend/Range/Volatile
│   ├── data/
│   │   ├── database.py        # MySQL operations
│   │   └── fetcher.py         # Binance API + synthetic
│   └── backtest/
│       └── engine.py          # Full backtest pipeline
└── dashboard/
    ├── Dockerfile
    ├── package.json
    ├── next.config.js
    ├── tailwind.config.js
    └── src/
        ├── lib/db.ts           # MySQL connection
        ├── app/
        │   ├── layout.tsx
        │   ├── page.tsx        # Main page (SSR)
        │   ├── globals.css
        │   └── api/            # REST endpoints
        │       ├── stats/
        │       ├── trades/
        │       ├── equity/
        │       ├── positions/
        │       └── regimes/
        └── components/
            └── Dashboard.tsx   # Main dashboard UI
```

## Customization

### เปลี่ยน Parameters
แก้ไฟล์ `trading-engine/config.py` หรือ set ผ่าน `.env`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| SYMBOL | BTCUSDT | คู่เทรด |
| TIMEFRAME | 1h | Timeframe |
| INITIAL_CAPITAL | 10000 | ทุนเริ่มต้น (USDT) |
| RISK_PER_TRADE | 0.02 | Risk 2% per trade |
| MAX_DRAWDOWN | 0.15 | หยุดเทรดถ้า DD > 15% |
| FEE_MULTIPLIER | 3.0 | Min profit ≥ 3× fee |

### เพิ่ม Strategy ใหม่
1. สร้าง class ใน `strategies/strategies.py`
2. เพิ่มใน `STRATEGY_MAP`
3. เพิ่ม regime ใหม่ใน `regime_detector.py` ถ้าจำเป็น

## Access MySQL Direct

```bash
# Connect to MySQL
docker exec -it regime_db mysql -utrader -ptrader_pass_2026 regime_trader

# Check trades
SELECT * FROM positions ORDER BY entry_time DESC LIMIT 10;

# Check equity
SELECT * FROM equity_curve ORDER BY timestamp DESC LIMIT 5;

# Regime distribution
SELECT regime_name, COUNT(*) FROM regimes GROUP BY regime_name;
```

## ⚠️ Important

1. **เปลี่ยน API Key** หลังทดสอบเสร็จ!
2. ระบบนี้เหมาะสำหรับ **Demo/Paper trading** ก่อน
3. ทดสอบ backtest ให้ดีก่อนเทรดจริง
4. Cryptocurrency trading มีความเสี่ยงสูง - ใช้เงินที่พร้อมจะเสียได้เท่านั้น
