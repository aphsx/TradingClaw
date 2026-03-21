#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════
  REGIME DETECTION TRADING SYSTEM v3
  Docker + MySQL + Redis + Binance API
  Enhanced: Multi-Symbol, Trailing Stops, Kelly Sizing
═══════════════════════════════════════════════════════════
"""
import json, time, sys, os, traceback, threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *

# Threading lock for position state changes
_position_lock = threading.Lock()

# ═══════════════════════════════════════
# INFRA WAIT
# ═══════════════════════════════════════
def wait_for_db(max_retries=30):
    from data.database import get_engine
    from sqlalchemy import text
    for i in range(max_retries):
        try:
            with get_engine().connect() as c:
                c.execute(text("SELECT 1"))
            print("✅ MySQL connected")
            return True
        except Exception as e:
            print(f"⏳ DB... ({i+1}/{max_retries})")
            time.sleep(2)
    return False


def wait_for_redis(max_retries=15):
    from data.monitor import get_redis
    for i in range(max_retries):
        try:
            get_redis().ping()
            print("✅ Redis connected")
            return True
        except Exception:
            print(f"⏳ Redis... ({i+1}/{max_retries})")
            time.sleep(1)
    return False


# ═══════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════
def _verify_order_placed(order_resp: dict, order_type: str) -> bool:
    """Verify an order was successfully placed on Binance."""
    if order_resp.get('_http_status', 0) != 200:
        print(f"⚠️ {order_type} order failed: {order_resp}")
        return False
    if 'orderId' not in order_resp:
        print(f"⚠️ {order_type} order missing orderId: {order_resp}")
        return False
    return True


def _with_retry(fn, *args, retries=3, **kwargs):
    """Retry a function up to N times on failure."""
    for attempt in range(retries):
        try:
            result = fn(*args, **kwargs)
            if result.get('_http_status', 200) == 200:
                return result
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1 * (attempt + 1))
            else:
                raise
    return result


# ═══════════════════════════════════════
# LIVE TRADING
# ═══════════════════════════════════════
def run_live():
    import data.database as db
    import data.binance_client as bnb
    import data.monitor as mon
    from data.socket_server import run_socket_server
    from data.http_api import run_http_server
    from data.fetcher import fetch_klines, fetch_multi_symbol
    from core.features import calculate_features, get_regime_features
    from core.regime_detector import RegimeDetector, REGIME_NAMES
    from core.risk_manager import RiskManager, FeeFilter
    from strategies.strategies import generate_all_signals, check_exit_signals

    print("=" * 60)
    print(f"  LIVE TRADING - {SYMBOL} {TIMEFRAME}")
    print("=" * 60)

    wait_for_db()
    wait_for_redis()
    
    # Start Socket.IO server for real-time dashboard updates
    run_socket_server(port=8080)
    
    # Start HTTP API server for manual positions
    run_http_server(port=8081)

    # Test Binance
    conn = bnb.test_connection()
    print(f"🔌 Binance: ping={conn.get('ping')}")
    if conn.get("account", {}).get("connected"):
        bals = conn["account"]["balances"]
        for asset, b in list(bals.items())[:5]:
            print(f"   {asset}: {b['free']}")
    else:
        print(f"⚠️  Account: {conn.get('account')}")

    detector = RegimeDetector()
    risk_mgr = RiskManager(initial_capital=INITIAL_CAPITAL)
    fee_filter = FeeFilter()
    is_trained = False
    last_signal_time = None

    # ─── Set leverage and margin type for all symbols ───
    if USE_FUTURES:
        print(f"\n⚙️  Configuring futures leverage and margin...")
        for sym in SYMBOLS:
            try:
                bnb.set_leverage(sym, LEVERAGE)
                print(f"✅ {sym}: Leverage set to {LEVERAGE}x")
            except Exception as e:
                print(f"⚠️ {sym}: Failed to set leverage: {e}")
            try:
                bnb.set_margin_type(sym, MARGIN_TYPE)
                print(f"✅ {sym}: Margin type set to {MARGIN_TYPE}")
            except Exception as e:
                print(f"⚠️ {sym}: Margin type error (may already be set): {e}")

    mon.set_status("running", f"Live trading {SYMBOL}")
    db.log("INFO", "engine", "Live started", {"symbol": SYMBOL})

    # ─── MONITOR THREAD: check SL/TP fills every N seconds ───
    def monitor_loop():
        while True:
            try:
                with _position_lock:
                    # Update price
                    price = bnb.get_price(SYMBOL)
                    mon.update_price(price)

                    # Check margin ratio for futures
                    if USE_FUTURES:
                        try:
                            account = bnb.get_futures_account()
                            margin_check = risk_mgr.check_margin_ratio(account)
                            mon.update_margin_ratio(account)
                            if margin_check["status"] == "emergency":
                                print(f"🚨 EMERGENCY: Margin ratio {margin_check['ratio']:.1%} — CLOSING ALL!")
                                # Close all positions
                                for pos in mon.get_open_positions_from_redis():
                                    close_side = 'SELL' if pos['direction'] == 'LONG' else 'BUY'
                                    try:
                                        bnb.place_market_order(pos['symbol'], close_side, float(pos['quantity']))
                                    except Exception as e:
                                        print(f"⚠️ Emergency close error: {e}")
                            elif margin_check["status"] == "warning":
                                print(f"⚠️ WARNING: Margin ratio {margin_check['ratio']:.1%}")
                        except Exception as e:
                            print(f"⚠️ Margin check error: {e}")

                    # Get open positions from Redis
                    open_positions = mon.get_open_positions_from_redis()

                    for pos in open_positions:
                        # Update trailing stop
                        new_sl = risk_mgr.update_trailing_stop(pos, price)
                        if new_sl != float(pos.get('stop_loss', 0)):
                            print(f"🔄 Updating trailing stop for position #{pos.get('id')}: {pos.get('stop_loss')} → {new_sl}")
                            pos['stop_loss'] = new_sl
                            try:
                                if pos.get('sl_order_id'):
                                    bnb.cancel_order(pos['symbol'], int(pos['sl_order_id']))
                            except:
                                pass
                            # Place new SL order
                            sl_side = 'SELL' if pos['direction'] == 'LONG' else 'BUY'
                            new_sl_order = bnb.place_stop_loss_order(pos['symbol'], sl_side,
                                                                      float(pos['quantity']), new_sl)
                            if new_sl_order.get('orderId'):
                                pos['sl_order_id'] = new_sl_order['orderId']
                                mon.publish_position_open(pos['id'], pos)

                        # Check time-based exit
                        if risk_mgr.should_time_exit(pos):
                            print(f"⏰ Time exit for position #{pos['id']} - open too long with no profit")
                            close_side = 'SELL' if pos['direction'] == 'LONG' else 'BUY'
                            close_order = bnb.place_market_order(pos['symbol'], close_side,
                                                                  float(pos['quantity']))
                            if close_order.get('orderId'):
                                mon.publish_position_close(pos['id'],
                                    {'exit_price': price, 'reason': 'Time Exit',
                                     'pnl': float(pos.get('unrealized_pnl', 0))})
                                db.log("INFO", "monitor", f"Time exit #{pos['id']}", {})

                    # Sync positions with Binance (check SL/TP)
                    closed = mon.sync_open_positions_with_binance(db)
                    if closed:
                        db.log("INFO", "monitor", f"Closed {len(closed)} positions", {"ids": closed})

            except Exception as e:
                print(f"⚠️  Monitor: {e}")
            time.sleep(MONITOR_INTERVAL_SECONDS)

    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()
    print("🔍 Position monitor started")

    # ─── MAIN SIGNAL LOOP ───
    while True:
        try:
            now = datetime.utcnow()
            print(f"\n{'─'*50}")
            print(f"⏰ {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")

            # 1. Fetch data
            df = fetch_klines(symbol=SYMBOL, interval=TIMEFRAME, days=30)
            if len(df) < 50:
                print("⚠️  Not enough data")
                time.sleep(LOOP_INTERVAL_SECONDS)
                continue

            # 2. Features
            df = calculate_features(df)
            feat = get_regime_features(df).dropna()
            ci = df.index.intersection(feat.index)
            df, feat = df.loc[ci], feat.loc[ci]

            # 3. Train if needed
            if not is_trained:
                print("🧠 Training...")
                stats = detector.fit(df, feat)
                print(f"   CV: {stats['cv_accuracy']}")
                is_trained = True

            # 4. Current regime
            current = detector.get_current_regime(feat)
            rname = current['regime_name']
            rconf = current['confidence']
            print(f"🔮 Regime: {rname} ({rconf:.0%})")
            mon.update_regime(rname, rconf, current['probabilities'])

            # 5. Signals
            regimes = detector.predict(feat)
            signals = generate_all_signals(df, regimes)
            passed, _ = fee_filter.filter_signals(signals)

            # Only look at the latest bar signal
            last_bar = df.index[-1]
            new_sigs = [s for s in passed if s.timestamp == last_bar]

            # Skip if we already processed this bar
            if last_bar == last_signal_time:
                print("⏸️  Already processed this bar")
            elif new_sigs:
                for sig in new_sigs:
                    print(f"\n📡 SIGNAL: {sig.direction} @ ${sig.entry_price:,.2f}")
                    print(f"   SL: ${sig.stop_loss:,.2f} | TP: ${sig.take_profit:,.2f}")
                    print(f"   Strategy: {sig.strategy} | RR: 1:{sig.risk_reward:.1f}")

                    # Check risk limits
                    open_pos = mon.get_open_positions_from_redis()
                    if len(open_pos) >= MAX_OPEN_TRADES:
                        print(f"   ⛔ Max {MAX_OPEN_TRADES} open trades")
                        continue

                    # Calculate quantity
                    qty = risk_mgr.calculate_position_size(sig)
                    if qty <= 0:
                        print("   ⛔ Qty too small")
                        continue

                    # Place ENTRY order
                    side = "BUY" if sig.direction == "LONG" else "SELL"
                    print(f"   🔫 Placing {side} {qty:.6f} {SYMBOL}...")

                    if TRADING_MODE == "paper":
                        order_resp = {"orderId": 0, "status": "PAPER",
                                      "fills": [{"price": str(sig.entry_price),
                                                  "qty": str(qty), "commission": "0",
                                                  "commissionAsset": "USDT"}],
                                      "_client_oid": "paper"}
                    else:
                        order_resp = bnb.place_market_order(SYMBOL, side, qty)

                    parsed = bnb.parse_order_response(order_resp)
                    print(f"   ✅ Order {parsed.get('status')}: fill=${parsed.get('fill_price'):,.2f} "
                          f"fee={parsed.get('commission'):.6f} {parsed.get('commission_asset')}")

                    if parsed.get("status") not in ("FILLED", "PAPER"):
                        print(f"   ❌ Order not filled: {parsed.get('status')}")
                        db.log("ERROR", "order", "Entry not filled", parsed)
                        continue

                    # Save signal + position to DB
                    sig_id = db.save_signal(sig, SYMBOL, source="LIVE")

                    # Place SL + TP orders
                    sl_oid = None
                    tp_oid = None
                    exit_side = "SELL" if sig.direction == "LONG" else "BUY"

                    if TRADING_MODE != "paper":
                        try:
                            sl_resp = _with_retry(bnb.place_stop_loss_order, SYMBOL, exit_side, qty, sig.stop_loss)
                            if _verify_order_placed(sl_resp, "SL"):
                                sl_oid = sl_resp.get("orderId")
                                print(f"   🛑 SL order placed: #{sl_oid}")
                        except Exception as e:
                            print(f"   ⚠️  SL order failed: {e}")

                        try:
                            tp_resp = _with_retry(bnb.place_take_profit_order, SYMBOL, exit_side, qty, sig.take_profit)
                            if _verify_order_placed(tp_resp, "TP"):
                                tp_oid = tp_resp.get("orderId")
                                print(f"   🎯 TP order placed: #{tp_oid}")
                        except Exception as e:
                            print(f"   ⚠️  TP order failed: {e}")

                    with _position_lock:
                        pos_id = db.open_position_live(
                            signal_id=sig_id, symbol=SYMBOL,
                            direction=sig.direction, strategy=sig.strategy,
                            regime=sig.regime, entry_price=sig.entry_price,
                            entry_time=now, quantity=qty,
                            order_data=parsed,
                            stop_loss=sig.stop_loss, take_profit=sig.take_profit,
                            risk_reward=sig.risk_reward,
                            sl_order_id=sl_oid, tp_order_id=tp_oid,
                        )

                        # Publish to Redis for monitoring
                        mon.publish_position_open(pos_id, {
                            "source": "LIVE", "symbol": SYMBOL,
                            "direction": sig.direction, "strategy": sig.strategy,
                            "entry_price": sig.entry_price,
                            "entry_fill_price": parsed.get("fill_price"),
                            "entry_commission": parsed.get("commission"),
                            "quantity": qty,
                            "stop_loss": sig.stop_loss, "take_profit": sig.take_profit,
                            "sl_order_id": sl_oid, "tp_order_id": tp_oid,
                            "entry_time": now.isoformat(),
                        })

                        db.log("INFO", "trade", f"Opened #{pos_id}", {
                            "direction": sig.direction, "qty": qty,
                            "fill": parsed.get("fill_price"),
                            "fee": parsed.get("commission"),
                            "sl_order": sl_oid, "tp_order": tp_oid,
                        })

                last_signal_time = last_bar
            else:
                print("⏸️  No signal")
                last_signal_time = last_bar

            # 6. Market snapshot
            last = df.iloc[-1]
            price = last['close']
            print(f"\n📊 {SYMBOL}: ${price:,.2f} | ATR: {last['atr_pct']:.2f}% "
                  f"| RSI: {last['rsi_14']:.0f} | ADX: {last['adx']:.0f}")

            # Check funding rates for each symbol (futures)
            if USE_FUTURES:
                for sym in SYMBOLS:
                    try:
                        mark = bnb.get_mark_price(sym)
                        rate = float(mark.get("lastFundingRate", 0))
                        mon.update_funding_rates({"symbol": sym, "rate": rate,
                                                   "mark_price": float(mark.get("markPrice", 0)),
                                                   "next_funding": mark.get("nextFundingTime")})
                    except:
                        pass

            # Update equity in Redis
            open_count = len(mon.get_open_positions_from_redis())
            unrealized = mon.update_price(price)
            mon.update_equity(INITIAL_CAPITAL + unrealized, INITIAL_CAPITAL, unrealized, open_count)

        except Exception as e:
            print(f"❌ Error: {e}")
            traceback.print_exc()
            mon.set_status("error", str(e))
            db.log("ERROR", "engine", str(e))

        print(f"\n💤 Next check in {LOOP_INTERVAL_SECONDS}s...")
        time.sleep(LOOP_INTERVAL_SECONDS)


# ═══════════════════════════════════════
# BACKTEST (unchanged from previous, no fake live data)
# ═══════════════════════════════════════
def run_backtest():
    from backtest.engine import BacktestEngine
    from data.fetcher import get_data
    import data.database as db

    print("=" * 60)
    print("  BACKTEST MODE")
    print("=" * 60)

    db_ready = wait_for_db()
    df = get_data(use_api=True, days=LOOKBACK_DAYS)
    if len(df) < 100:
        print("❌ Not enough data")
        return

    engine = BacktestEngine(capital=INITIAL_CAPITAL, use_db=db_ready)
    engine.run(df)


# ═══════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════
def main():
    mode = TRADING_MODE
    print(f"MODE = {mode}")

    if mode == "backtest":
        run_backtest()
    elif mode in ("live", "paper"):
        run_live()
    else:
        print(f"Unknown mode: {mode}")


if __name__ == "__main__":
    main()
