# TradingClaw — Automated Trading Bot

ระบบเทรดอัตโนมัติที่ใช้กลยุทธ์ **Smart Money Concepts (SMC) + Squeeze Breakout** บน Crypto Futures

---

## สารบัญ

1. [ภาพรวมระบบ](#1-ภาพรวมระบบ)
2. [โครงสร้างโปรเจกต์](#2-โครงสร้างโปรเจกต์)
3. [Market Analysis Engine](#3-market-analysis-engine)
4. [Decision Engine](#4-decision-engine)
5. [Entry Logic](#5-entry-logic)
6. [Exit Logic](#6-exit-logic)
7. [Risk Management](#7-risk-management)
8. [Order Execution](#8-order-execution)
9. [Monitoring System](#9-monitoring-system)
10. [Alert & Notification](#10-alert--notification)
11. [Backtesting & Forward Testing](#11-backtesting--forward-testing)
12. [Logging & Trade Journal](#12-logging--trade-journal)
13. [Technical Risk Protection](#13-technical-risk-protection)
14. [Deployment](#14-deployment)
15. [Performance Metrics & KPI](#15-performance-metrics--kpi)
16. [ตัวอย่าง Workflow จริง](#16-ตัวอย่าง-workflow-จริง)

---

## 1. ภาพรวมระบบ

ระบบประกอบด้วย 6 Module หลักที่ทำงานแบบ Modular Design:

| Module | หน้าที่ | Input | Output |
|---|---|---|---|
| Market Analysis Engine | อ่านตลาด วิเคราะห์ Structure/Volume | OHLCV, Order Book | Market State Object |
| Decision Engine | ตัดสินใจเข้า/ไม่เข้าตาม Confluence | Market State, Rules | Trade Signal |
| Risk Manager | คำนวณ Position Size, SL, TP, Leverage | Trade Signal, Portfolio | Order Parameters |
| Order Executor | ส่งคำสั่ง Exchange ด้วย Limit Order | Order Parameters | Order Status |
| Monitor & Tracker | ติดตาม Position, P&L, เลื่อน SL/TP | Open Positions | Position Updates |
| Logger & Journal | บันทึกทุก Action, สร้าง Trade Report | All Module Events | Trade Log |

**Data Flow:**
```
Exchange API → Market Analysis → Decision Engine → Risk Manager → Order Executor → Monitor → Logger
```

### Technology Stack

| Component | เทคโนโลยี | เหตุผล |
|---|---|---|
| ภาษาหลัก | Python 3.11+ | Library เยอะ, ccxt รองรับทุก Exchange |
| Exchange Library | ccxt (unified) | รองรับ 100+ Exchange |
| Data Processing | pandas + numpy | คำนวณ Indicator ได้เร็ว |
| Technical Analysis | ta-lib / pandas-ta | Indicator สำเร็จรูป |
| Database | SQLite → PostgreSQL | Trade Log, State, Config |
| Monitoring UI | Grafana + InfluxDB | Dashboard Real-time |
| Notification | Telegram Bot / LINE Notify | แจ้งเตือนทันที |
| Scheduler | APScheduler / asyncio | Loop ต่อเนื่อง |
| Deployment | VPS + Docker | รัน 24/7 |

---

## 2. โครงสร้างโปรเจกต์

```
trading-bot/
├── config/
│   ├── settings.yaml          # ค่าตั้งระบบทั้งหมด
│   ├── pairs.yaml             # คู่เทรดและพารามิเตอร์เฉพาะ
│   └── risk_rules.yaml        # กฎ Risk Management
├── core/
│   ├── market_analyzer.py     # Module วิเคราะห์ตลาด
│   ├── decision_engine.py     # Module ตัดสินใจ
│   ├── risk_manager.py        # Module จัดการความเสี่ยง
│   ├── order_executor.py      # Module ส่งคำสั่ง
│   ├── position_monitor.py    # Module ติดตาม Position
│   └── logger.py              # Module บันทึก Log
├── strategies/
│   ├── squeeze_breakout.py    # กลยุทธ์ Squeeze Breakout
│   └── smc_entry.py           # กลยุทธ์ Smart Money Concepts
├── utils/
│   ├── indicators.py          # ฟังก์ชัน Indicator ทั้งหมด
│   ├── structure.py           # ฟังก์ชัน Market Structure
│   └── notifications.py       # ฟังก์ชันแจ้งเตือน
├── data/
│   ├── trades.db              # ฐานข้อมูลเทรด
│   └── candles/               # Cache OHLCV Data
├── tests/
│   ├── test_strategy.py       # Unit Test
│   └── backtest_runner.py     # Backtesting Engine
├── main.py                    # Entry Point
└── requirements.txt
```

### Configuration (`settings.yaml`)

```yaml
exchange:
  name: binance
  api_key: "YOUR_API_KEY"
  secret: "YOUR_SECRET"
  testnet: true                    # เริ่มจาก Testnet ก่อนเสมอ!

trading:
  pairs: ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
  timeframe: "1h"
  higher_timeframe: "4h"
  lower_timeframe: "15m"
  max_concurrent_positions: 2

risk:
  risk_per_trade_pct: 1.0          # เสี่ยง 1% ต่อรอบ
  max_daily_loss_pct: 3.0          # ขาดทุนรวม/วัน ไม่เกิน 3%
  max_weekly_loss_pct: 5.0
  max_leverage: 5
  max_sl_distance_pct: 2.0
  consecutive_loss_limit: 2        # แพ้ติด 2 รอบ = หยุด

order:
  order_type: "limit"
  limit_offset_pct: 0.02
  max_slippage_pct: 0.1
  retry_count: 3

notifications:
  telegram_token: "YOUR_BOT_TOKEN"
  telegram_chat_id: "YOUR_CHAT_ID"
  alert_on: ["entry", "exit", "sl_hit", "tp_hit", "error", "daily_summary"]
```

---

## 3. Market Analysis Engine

คำนวณข้อมูลทั้งหมดที่จำเป็นสำหรับการตัดสินใจ

| ข้อมูล | วิธีคำนวณ | Timeframe | ใช้ทำอะไร |
|---|---|---|---|
| Market Structure | Swing High/Low → HH/HL/LH/LL | 4H + 1H | กำหนด Bias |
| BOS / CHoCH | ราคาทะลุ HH/LL (BOS) หรือ HL/LH (CHoCH) | 4H + 1H | ยืนยัน/เปลี่ยนเทรน |
| Order Block | แท่งสุดท้ายก่อน Impulsive Move ที่ทำ BOS | 1H | POI |
| Fair Value Gap | ช่องว่างระหว่างแท่ง 1 กับ แท่ง 3 | 1H | จุดเข้าเสริม |
| Liquidity Level | Equal Highs/Lows, Swing H/L | 4H + 1H | TP + หลีกเลี่ยง SL trap |
| EMA 9, 21, 50 | Exponential Moving Average | 1H + 4H | Dynamic S/R |
| Bollinger Bands | BB(20,2) | 1H | Squeeze + Breakout |
| ATR(14) | Average True Range | 1H | SL Buffer |
| Volume | Volume MA(20) | 1H | ยืนยัน Breakout |
| Funding Rate | Exchange API | Real-time | Sentiment Edge |
| Fibonacci | 61.8%, 70.5%, 78.6% ของ Swing ล่าสุด | 1H | OTE Zone |

### Market Structure Classification

| เงื่อนไข | Structure | Bias |
|---|---|---|
| Swing High ล่าสุด > ก่อนหน้า AND Swing Low ล่าสุด > ก่อนหน้า | Bullish (HH + HL) | Long Only |
| Swing High ล่าสุด < ก่อนหน้า AND Swing Low ล่าสุด < ก่อนหน้า | Bearish (LH + LL) | Short Only |
| ไม่เข้าเงื่อนไขทั้งสอง | Ranging / Unclear | No Trade |

### Swing Detection Algorithm

```python
def find_swing_highs(candles, lookback=3):
    swings = []
    for i in range(lookback, len(candles) - lookback):
        is_swing = True
        for j in range(1, lookback + 1):
            if candles[i].high <= candles[i-j].high or \
               candles[i].high <= candles[i+j].high:
                is_swing = False
                break
        if is_swing:
            swings.append(SwingPoint(index=i, price=candles[i].high, type='HIGH'))
    return swings
```

> **Lookback:** N=3 สำหรับ 1H, N=5 สำหรับ 4H

---

## 4. Decision Engine

### ขั้นตอนที่ 1 — Hard Filters (ไม่ผ่าน = ไม่เทรด ไม่มีข้อยกเว้น)

| Filter | เงื่อนไข | ถ้าไม่ผ่าน |
|---|---|---|
| Trend Alignment | 4H bias ต้องตรงกับ 1H bias | SKIP ทันที |
| Structure Clear | 4H ต้องไม่ใช่ Ranging | SKIP ทันที |
| No News | ไม่มีข่าว High Impact ใน 30 นาที | SKIP ทันที |
| Daily Loss Limit | ขาดทุนวันนี้ < 3% | หยุดเทรดทั้งวัน |
| Consecutive Loss | แพ้ติดกันไม่ถึง 2 รอบ | หยุดเทรดวันนี้ |
| Max Positions | Position เปิดอยู่ < 2 | รอปิดก่อน |
| SL Distance | SL ห่างไม่เกิน 2% | ข้าม Setup นี้ |

### ขั้นตอนที่ 2 — Confluence Scoring

| Factor | คะแนน | รายละเอียด |
|---|---|---|
| Price at Order Block | +3 | ราคาอยู่ใน OB zone ที่ยังไม่ถูก test |
| Price at FVG | +2 | ราคาอยู่ใน FVG zone |
| OB + FVG overlap | +2 | OB กับ FVG ซ้อนทับกัน (Bonus) |
| Fib OTE Zone | +2 | ราคาอยู่ในโซน 61.8-78.6% |
| BB Squeeze → Breakout | +2 | BB บีบแล้วทะลุ |
| Volume Confirmation | +2 | Volume > 1.5x ค่าเฉลี่ย |
| 15m CHoCH | +3 | มี CHoCH บน 15m ที่ POI |
| Funding Rate Edge | +1 | Funding Rate เข้าข้างทิศทางเรา |
| Liquidity Swept | +2 | Liquidity ถูกกวาดก่อนแล้ว |
| EMA Confluence | +1 | ราคาอยู่ใกล้ EMA 21/50 ที่เป็น S/R |

### ขั้นตอนที่ 3 — Scoring Threshold

| คะแนนรวม | การตัดสินใจ | Position Size |
|---|---|---|
| < 6 | ไม่เข้าเทรด | N/A |
| 6-8 | Conservative | 50% ของปกติ |
| 9-12 | Standard | 100% ของปกติ |
| 13+ | High Conviction | 100% + พิจารณา Scale In |

> **คำเตือน:** อย่าลดเกณฑ์คะแนนขั้นต่ำ (6) เพื่อเทรดบ่อยขึ้น — นี่คือกฎที่ปกป้องเงิน

---

## 5. Entry Logic

### Primary Entry: OB + FVG + CHoCH Model

```python
def check_entry(market_state):
    ms = market_state

    # HARD FILTERS
    if ms.structure_4h.bias == "RANGING": return None
    if ms.structure_4h.bias != ms.structure_1h.bias: return None
    if check_news_calendar(): return None
    if daily_loss >= config.max_daily_loss_pct: return None
    if consecutive_losses >= config.consecutive_loss_limit: return None
    if open_positions >= config.max_concurrent_positions: return None

    # FIND POI (OB + FVG overlap ใน Fib OTE zone)
    poi = find_best_poi(ms)
    if not poi: return None

    # CHECK 15M CHOCH
    choch = check_15m_choch(ms.pair, poi)
    if not choch: return None

    # CALCULATE CONFLUENCE SCORE
    score = calculate_confluence(ms, poi, choch)
    if score < 6: return None

    # DETERMINE ENTRY PARAMETERS
    direction = "LONG" if ms.structure_4h.bias == "BULLISH" else "SHORT"
    entry_price = choch.confirmation_price

    if direction == "LONG":
        sl_price = poi.low - (ms.indicators.atr_14 * 0.5)
        tp1 = find_nearest_liquidity(ms, "BSL")
    else:
        sl_price = poi.high + (ms.indicators.atr_14 * 0.5)
        tp1 = find_nearest_liquidity(ms, "SSL")

    rr = abs(tp1 - entry_price) / abs(entry_price - sl_price)
    if rr < 2.0: return None

    return TradeSignal(pair=ms.pair, direction=direction,
                       entry=entry_price, sl=sl_price, tp1=tp1,
                       score=score, rr=rr)
```

### Secondary Entry: Liquidity Sweep Model

1. **Detect Sweep** — ราคาทะลุ Swing High/Low ไปเล็กน้อย (< 0.3%)
2. **Confirm Rejection** — มี Rejection Wick (wick ยาว > 60% ของ body)
3. **Wait CHoCH** — รอ CHoCH บน 15m ก่อนเข้า
4. **SL Placement** — SL ไว้หลังจุดสุดขีดของ Sweep

### Limit Order Strategy

- **Long:** ตั้ง Limit Buy ที่ `Entry - 0.02%`
- **Short:** ตั้ง Limit Sell ที่ `Entry + 0.02%`
- ถ้า Order ไม่ Fill ใน 5 แท่ง 15m → Cancel → Setup หมดอายุ
- ไม่ Chase Price — ถ้าราคาไปแล้วก็ปล่อยไป

---

## 6. Exit Logic

### Partial Take Profit

| ส่วน | สัดส่วน | เป้าหมาย | Action หลัง TP |
|---|---|---|---|
| TP1 | 40% | Liquidity Pool ใกล้สุด (BSL/SSL บน 1H) | เลื่อน SL → Break Even |
| TP2 | 30% | Order Block ตรงข้ามบน 1H | เลื่อน SL → TP1 |
| TP3 | 30% | Liquidity Pool บน 4H | Trailing ตาม Structure |

### Trailing Stop ตาม Market Structure

```python
def update_trailing_stop(position, market_state):
    ms = market_state
    if position.direction == "LONG":
        latest_hl = find_latest_swing_low(ms.candles_1h)
        new_sl = latest_hl.price - (ms.indicators.atr_14 * 0.3)

        if new_sl > position.current_sl:   # เลื่อนขึ้นเท่านั้น ห้ามลง
            position.current_sl = new_sl

        if ms.structure_1h.choch_detected and ms.structure_1h.choch_direction == "BEARISH":
            close_position(position, reason="1H CHoCH detected")
```

### Early Exit Conditions

| # | เงื่อนไข |
|---|---|
| 1 | ราคาไม่เคลื่อนไหวตาม Plan ภายใน 5 แท่ง 1H (Time Stop) |
| 2 | ราคา 1H ปิดใต้/เหนือ Order Block ที่เราเข้า (OB Fail) |
| 3 | เกิด CHoCH สวนทาง Position บน 1H (Structure Break) |
| 4 | Volume หายไปอย่างรุนแรง (Volume < 30% ของ MA20) |
| 5 | มีข่าว High Impact กำลังจะออกใน 15 นาที |

---

## 7. Risk Management

### Position Sizing Formula

```python
def calculate_position_size(portfolio_value, risk_pct, entry_price, sl_price, leverage):
    risk_amount = portfolio_value * (risk_pct / 100)
    sl_distance_pct = abs(entry_price - sl_price) / entry_price

    position_size_usd = risk_amount / sl_distance_pct

    required_leverage = position_size_usd / portfolio_value
    if required_leverage > max_leverage:
        position_size_usd = portfolio_value * max_leverage  # ลด Size แทน

    margin_required = position_size_usd / leverage
    available_margin = portfolio_value - total_margin_in_use
    if margin_required > available_margin * 0.8:
        position_size_usd = available_margin * 0.8 * leverage

    return PositionSizeResult(size_usd=position_size_usd, ...)
```

### Correlation Guard

| สถานการณ์ | Action |
|---|---|
| เปิด 1 Position | เสี่ยง 1% ตามปกติ |
| เปิด 2 Position ทิศทางเดียวกัน | ลดเหลือ 0.5-0.75% ต่อตัว (รวมไม่เกิน 1.5%) |
| เปิด 2 Position ทิศทางตรงข้าม | เสี่ยงได้ 1% ต่อตัว (Hedge กันเอง) |
| มี 2 Position แล้ว | ห้ามเปิดเพิ่ม |

### Circuit Breaker

| เงื่อนไข | Action | ระยะเวลา |
|---|---|---|
| ขาดทุนติด 2 รอบ | หยุดเทรด | ที่เหลือของวัน |
| ขาดทุนรวมวัน ≥ 3% | หยุดเทรด | ที่เหลือของวัน |
| ขาดทุนรวมสัปดาห์ ≥ 5% | หยุดเทรด | ที่เหลือของสัปดาห์ |
| API Error ติดกัน 3 ครั้ง | หยุด + แจ้งเตือน | จนกว่า Manual Reset |
| Flash Crash (ลง > 5% ใน 5 นาที) | ปิดทุก Position ทันที | จนกว่า Manual Reset |

---

## 8. Order Execution

### Order Flow

```python
async def execute_trade(signal, position_params):
    if not await check_exchange_health(): return
    balance = await exchange.fetch_balance()
    if balance.free < position_params.margin * 1.1: return

    await exchange.set_leverage(position_params.leverage, signal.pair)

    entry_order = await exchange.create_limit_order(
        symbol=signal.pair,
        side='buy' if signal.direction == 'LONG' else 'sell',
        amount=position_params.size_coin,
        price=signal.entry
    )

    filled = await wait_for_fill(entry_order, timeout=1800)
    if not filled:
        await exchange.cancel_order(entry_order.id)
        return

    # ตั้ง SL ทันทีหลัง Fill
    sl_order = await exchange.create_order(type='stop_market', ...)
    # ตั้ง TP1 (40% ของ Position)
    tp1_order = await exchange.create_limit_order(amount=position_params.size_coin * 0.4, ...)

    save_trade(signal, entry_order, sl_order, tp1_order)
    monitor.add_position(position)
```

### Fee Optimization

| วิธี | ประหยัดได้ | รายละเอียด |
|---|---|---|
| ใช้ Limit Order เสมอ | 60%+ | Maker 0.02% vs Taker 0.05% |
| ใช้ BNB จ่าย Fee | 10% discount | เปิดใน Settings |
| สะสม Volume ถึง VIP | 10-50% | Volume 30 วัน > $5M |
| ไม่เปิด-ปิดบ่อย | ลด fee สะสม | เทรดเฉพาะ Setup ที่ดี |

> **หมายเหตุ:** Use Stop Market สำหรับ SL สำคัญ — Stop Limit อาจไม่ Fill ในตลาดที่เคลื่อนเร็ว

---

## 9. Monitoring System

### Dashboard Components

| Component | ข้อมูล | Update |
|---|---|---|
| Portfolio Overview | Equity, Balance, Margin, Unrealized P&L | ทุก 5 วิ |
| Open Positions | Pair, Direction, P&L%, SL/TP Status | ทุก 5 วิ |
| Pending Orders | Type, Price, Status, Time Remaining | ทุก 10 วิ |
| Market Analysis | Structure, Bias, OB/FVG, Liquidity | ทุกแท่ง 1H |
| Performance | Win Rate, R:R, P&L, Drawdown | ทุก 1 นาที |
| System Health | API Status, Latency, Uptime | ทุก 30 วิ |

### Position Monitor Loop

```python
async def monitor_loop():
    while True:
        for position in get_open_positions():
            market = await get_current_market(position.pair)
            position.update_pnl(market.current_price)

            if check_time_stop(position):
                await close_position(position, "Time Stop"); continue
            if check_ob_fail(position, market):
                await close_position(position, "OB Failed"); continue
            if check_structure_break(position, market):
                await close_position(position, "Structure Break"); continue

            if position.tp1_filled and not position.sl_moved_to_be:
                await move_sl_to_breakeven(position)
            if position.tp1_filled:
                await update_trailing_stop(position, market)

            save_position_state(position)
        await asyncio.sleep(5)
```

---

## 10. Alert & Notification

### Alert Categories

| ระดับ | สถานการณ์ | ช่องทาง |
|---|---|---|
| INFO | เปิด/ปิด Position ปกติ | Telegram |
| INFO | SL เลื่อนแล้ว | Telegram |
| WARNING | ขาดทุนติด 2 รอบ | Telegram |
| WARNING | Daily Loss ใกล้ Limit | Telegram |
| CRITICAL | API Error | Telegram + Email |
| CRITICAL | Flash Crash | Telegram + Email |
| DAILY | สรุปวัน | Telegram |

### Telegram Message Format

```
🟢 NEW TRADE OPENED
━━━━━━━━━━━━━━━
Pair: BTC/USDT
Direction: LONG
Entry: $94,650.00
Stop Loss: $94,100.00 (-0.58%)
Take Profit 1: $96,200.00
R:R: 1:2.8
━━━━━━━━━━━━━━━
Score: 14/20
Size: 0.1820 (17,241 USD)
Leverage: 1.7x
Risk: $100.00 (1.0%)
━━━━━━━━━━━━━━━
Reason: OB + FVG + CHoCH at Fib 70.5%
```

---

## 11. Backtesting & Forward Testing

ก่อนใช้เงินจริง ต้อง Backtest อย่างน้อย **6 เดือน – 1 ปี**

### Backtest Metrics

| Metric | ยอมรับได้ | ดี | อธิบาย |
|---|---|---|---|
| Win Rate | > 35% | > 45% | เทรดที่ชนะ |
| Avg R:R | > 1:2 | > 1:3 | กำไรเฉลี่ย / ขาดทุนเฉลี่ย |
| Profit Factor | > 1.3 | > 2.0 | Gross Profit / Gross Loss |
| Max Drawdown | < 20% | < 10% | เสียมากสุดจากยอดสูงสุด |
| Sharpe Ratio | > 1.0 | > 2.0 | Risk-adjusted Return |
| Expectancy/Trade | > $0 | ยิ่งสูงยิ่งดี | กำไรเฉลี่ยต่อเทรด |
| Max Consecutive Losses | < 8 | < 5 | แพ้ติดกันมากสุด |
| Recovery Time | < 30 วัน | < 14 วัน | เวลาฟื้นจาก Drawdown |

### Forward Testing

- ใช้ Testnet (Binance Testnet / Bybit Testnet) อย่างน้อย **1-3 เดือน**
- รันบอทจริงกับ Real-time แต่ไม่ใช้เงินจริง
- ผลต้องใกล้เคียง Backtest อย่างน้อย **70%** ถึงเริ่มใช้เงินจริง

> **คำเตือน:** Backtest ที่ดีเกินจริง (Win Rate > 80%, Drawdown < 2%) มักเป็น Overfitting

---

## 12. Logging & Trade Journal

### Database Schema

```sql
CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    pair TEXT NOT NULL,
    direction TEXT NOT NULL,       -- LONG / SHORT
    entry_price REAL NOT NULL,
    exit_price REAL,
    sl_price REAL NOT NULL,
    tp1_price REAL,
    position_size_usd REAL NOT NULL,
    leverage REAL NOT NULL,
    confluence_score INTEGER,

    entry_time TIMESTAMP NOT NULL,
    exit_time TIMESTAMP,
    holding_hours REAL,

    pnl_usd REAL,
    pnl_pct REAL,
    fees_paid REAL,
    net_pnl REAL,
    result TEXT,                   -- WIN / LOSS / BE

    entry_reason TEXT,             -- JSON
    exit_reason TEXT,              -- SL / TP1 / TP2 / TRAILING / EARLY_EXIT
    followed_system BOOLEAN,
    notes TEXT,
    screenshot_path TEXT,

    market_structure TEXT,
    volatility REAL,
    funding_rate REAL,
    volume_ratio REAL
);

CREATE TABLE daily_summary (
    date DATE PRIMARY KEY,
    total_trades INTEGER,
    wins INTEGER,
    losses INTEGER,
    win_rate REAL,
    gross_pnl REAL,
    fees REAL,
    net_pnl REAL,
    max_drawdown REAL,
    equity_end REAL,
    system_adherence_pct REAL
);
```

---

## 13. Technical Risk Protection

| ความเสี่ยง | ผลกระทบ | วิธีป้องกัน |
|---|---|---|
| Internet ตัด | Monitor ไม่ได้ | VPS + Server-side SL ที่ Exchange |
| Exchange ล่ม | เข้า/ออกไม่ได้ | ตั้ง SL ไว้ล่วงหน้าเสมอ |
| API Rate Limit | Request ถูก Block | WebSocket แทน REST |
| Bot Crash | หยุดทำงาน | Auto-restart ด้วย Docker |
| Data Error | Indicator ผิด | Validate Data ก่อนใช้ |
| Double Order | เปิด Position ซ้ำ | เช็ค Open Position + Idempotency Key |
| Balance Sync | คำนวณ Size ผิด | Sync Balance จาก Exchange ก่อนทุกเทรด |
| Flash Crash | SL Slippage สูง | Isolated Margin + Position Size เล็ก |

### Failsafe Layers

| ชั้น | ระบบ |
|---|---|
| 1 | SL Order ตั้งไว้ที่ Exchange (ทำงานแม้บอทตาย) |
| 2 | Bot Monitor ตรวจทุก 5 วินาที |
| 3 | Circuit Breaker หยุดอัตโนมัติเมื่อขาดทุนเกิน |
| 4 | Kill Switch ปุ่มฉุกเฉินปิดทุก Position (Manual) |
| 5 | Daily Report ตรวจสอบว่าระบบปกติ |

---

## 14. Deployment

### VPS Specs

| Item | แนะนำ | ค่าใช้จ่าย/เดือน |
|---|---|---|
| Provider | DigitalOcean / Vultr / AWS Lightsail | $5-20 |
| Location | Singapore / Tokyo (ใกล้ Exchange Server) | - |
| Spec | 2 vCPU, 2GB RAM, 50GB SSD | $10-15 |
| OS | Ubuntu 22.04 LTS | Free |
| Container | Docker + Docker Compose | Free |
| Monitoring | Grafana Cloud (Free Tier) | Free |

### Docker Compose

```yaml
version: '3.8'
services:
  trading-bot:
    build: .
    restart: always
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./config:/app/config
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana

  influxdb:
    image: influxdb:2.7
    volumes:
      - influx-data:/var/lib/influxdb2

volumes:
  grafana-data:
  influx-data:
```

---

## 15. Performance Metrics & KPI

| KPI | เป้าหมาย | วัดอย่างไร | ทำไมสำคัญ |
|---|---|---|---|
| Win Rate | 40-55% | Wins / Total Trades | ต่ำกว่า 35% = ระบบมีปัญหา |
| Average R:R | > 1:2.5 | Avg Win / Avg Loss | ถ้าต่ำ = TP ไม่ดี หรือ SL กว้างเกิน |
| Expectancy | > $0.5 / $1 risked | (WR × Avg Win) - (LR × Avg Loss) | ต้องเป็นบวก |
| Max Drawdown | < 15% | Peak - Trough Equity | > 20% = อันตราย |
| System Adherence | > 95% | Trades ทำตามระบบ / Total | บอทควรได้ 100% |
| Avg Trades/Week | 8-12 | นับรวมทุกเหรียญ | น้อยเกิน = เพิ่มเหรียญ / เยอะเกิน = Overtrade |
| Fee Ratio | < 5% of Gross Profit | Total Fees / Gross Profit | > 10% = fee กิน profit |
| Sharpe Ratio | > 1.5 | Annualized Return / Std Dev | Risk-adjusted performance |

### Monthly Review Checklist

- [ ] Backtest vs Live Results — ต่างกันเกิน 30% หรือไม่?
- [ ] Win Rate Trend — กำลังลดลงหรือคงที่?
- [ ] Average R:R Trend — TP ถูก Hit บ่อยพอไหม?
- [ ] Drawdown Analysis — Drawdown ครั้งใหญ่เกิดจากอะไร?
- [ ] Fee Analysis — fee เป็นสัดส่วนเท่าไหร่?
- [ ] Market Regime — ตลาดตอนนี้เหมาะกับระบบไหม?
- [ ] Bug/Error Log — มี Technical Error อะไรบ้าง?
- [ ] Optimization Opportunity — มีจุดไหนปรับปรุงได้?

---

## 16. ตัวอย่าง Workflow จริง

สมมติเวลา 15:00 น. วันจันทร์:

```
[15:00:00] Market Analysis: ดึง 1H candle ใหม่ของ BTC, ETH, SOL
[15:00:02] Market Analysis: BTC 4H = Bullish (HH-HL), 1H = Bullish
[15:00:03] Market Analysis: Bullish OB $94,300-94,700 + FVG $94,350-94,600 (overlap!)
[15:00:04] Market Analysis: Fib OTE = $94,200-94,550 → ตรงกับ OB+FVG → POI แข็งแรงมาก
[15:00:05] Decision Engine: ราคา $95,100 ยังไม่ถึง POI → ตั้ง Alert ที่ $94,700

[17:30:00] Alert: ราคาลงมาแตะ $94,700!
[17:45:00] Market Analysis: 15m เกิด CHoCH!
[17:45:01] Decision Engine: Score = OB(3)+FVG(2)+Overlap(2)+Fib(2)+CHoCH(3)+Volume(2) = 14/20
[17:45:02] Risk Manager: Portfolio $10,000 | Risk 1% = $100 | SL: $94,100 | Size: 0.182 BTC | Leverage: 1.7x
[17:45:03] Order Executor: Limit Buy 0.182 BTC @ $94,650
[17:45:03] Telegram: "🟢 NEW TRADE: Long BTC @ $94,650 | SL: $94,100 | Score: 14"

[17:47:00] Order Executor: Filled! ตั้ง SL @ $94,100 ทันที + TP1 @ $96,200 (40%)
[17:47:02] Monitor: เริ่ม Monitor ทุก 5 วินาที

[20:15:00] Monitor: TP1 Hit @ $96,200 | Profit: +$113
[20:15:01] Order Executor: SL → Break Even @ $94,650 | ตั้ง TP2 @ $97,400 (30%)
[20:15:03] Telegram: "✅ TP1 HIT! +$113 | SL to BE | Remaining: 60%"

[23:00:00] Monitor: HL ใหม่ $95,800 → Trailing SL → $95,650

[Day 2 09:30] Monitor: TP2 Hit @ $97,400 | Profit: +$151 | SL → TP1 ($96,200)
[Day 2 14:00] Monitor: 1H CHoCH ขาลง → ปิดส่วนที่เหลือ 30% @ $97,100

[Day 2 14:01] Logger: Entry $94,650 | Exits: $96,200(40%) / $97,400(30%) / $97,100(30%)
              Net P&L: +$357 | Fee: $13.80 | R:R achieved: 1:3.6
[Day 2 14:02] Telegram: "🏆 TRADE CLOSED | Net: +$357 (+3.57%) | R:R: 1:3.6 | Held: 20.5h"
```

---

*TradingClaw — Built for discipline, not for excitement.*
