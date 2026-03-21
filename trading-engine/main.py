#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════
  REGIME DETECTION TRADING SYSTEM v2 (Docker + MySQL)
═══════════════════════════════════════════════════════════

Modes:
  TRADING_MODE=backtest   → Run backtest, save to MySQL
  TRADING_MODE=live       → Live trading loop with Binance
  TRADING_MODE=paper      → Paper trading (signals only, no orders)
"""
import argparse
import json
import time
import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *
from data.fetcher import get_data, test_connection, place_test_order, place_real_order

# DB optional
try:
    from data.database import log as db_log, get_engine
    HAS_DB = True
except Exception:
    HAS_DB = False


def wait_for_db(max_retries=30, delay=2):
    """Wait for MySQL to be ready."""
    if not HAS_DB:
        print("⚠️  No DB connection configured, running standalone")
        return False

    for i in range(max_retries):
        try:
            eng = get_engine()
            with eng.connect() as conn:
                conn.execute(__import__('sqlalchemy').text("SELECT 1"))
            print("✅ Database connected!")
            return True
        except Exception as e:
            print(f"⏳ Waiting for DB... ({i+1}/{max_retries}) {e}")
            time.sleep(delay)

    print("❌ Could not connect to database")
    return False


def run_backtest():
    """Run full backtest and save to MySQL."""
    from backtest.engine import BacktestEngine

    print("=" * 60)
    print("  REGIME DETECTION TRADING SYSTEM - BACKTEST")
    print("=" * 60)

    db_ready = wait_for_db()

    # Get data
    df = get_data(use_api=True, days=LOOKBACK_DAYS)
    if len(df) < 100:
        print("❌ Insufficient data")
        return

    # Run
    engine = BacktestEngine(capital=INITIAL_CAPITAL, use_db=db_ready)
    results = engine.run(df)

    # Save JSON output
    os.makedirs("output", exist_ok=True)
    with open("output/backtest_results.json", 'w') as f:
        json.dump(results, f, indent=2, default=str)

    trade_log = engine.get_trade_log()
    if len(trade_log) > 0:
        trade_log.to_csv("output/trade_log.csv", index=False)

    print("\n✅ Backtest complete! Check dashboard at http://localhost:3000")
    return results


def run_live():
    """Live trading loop - continuously monitor and trade."""
    from core.features import calculate_features, get_regime_features
    from core.regime_detector import RegimeDetector, REGIME_NAMES
    from core.risk_manager import RiskManager, FeeFilter
    from strategies.strategies import generate_all_signals

    print("=" * 60)
    print("  LIVE TRADING MODE")
    print("=" * 60)

    db_ready = wait_for_db()
    detector = RegimeDetector()
    risk_mgr = RiskManager(initial_capital=INITIAL_CAPITAL)
    fee_filter = FeeFilter()
    is_trained = False

    if db_ready:
        db_log("INFO", "engine", "Live trading started", {"symbol": SYMBOL, "timeframe": TIMEFRAME})

    while True:
        try:
            print(f"\n{'─'*40}")
            print(f"⏰ {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            # 1. Fetch recent data
            df = get_data(use_api=True, days=30)
            if len(df) < 50:
                print("⚠️ Not enough data, waiting...")
                time.sleep(LOOP_INTERVAL_SECONDS)
                continue

            # 2. Calculate features
            df = calculate_features(df)
            regime_features = get_regime_features(df).dropna()
            common_idx = df.index.intersection(regime_features.index)
            df = df.loc[common_idx]
            regime_features = regime_features.loc[common_idx]

            # 3. Train/retrain if needed
            if not is_trained:
                print("🧠 Training regime detector...")
                stats = detector.fit(df, regime_features)
                print(f"   Accuracy: {stats['cv_accuracy']}")
                is_trained = True

            # 4. Detect current regime
            current = detector.get_current_regime(regime_features)
            print(f"🔮 Regime: {current['regime_name']} ({current['confidence']:.0%})")

            # 5. Generate signals
            regimes = detector.predict(regime_features)
            signals = generate_all_signals(df, regimes)
            passed, _ = fee_filter.filter_signals(signals)

            # 6. Check for new signals (last bar only)
            last_time = df.index[-1]
            new_signals = [s for s in passed if s.timestamp == last_time]

            if new_signals:
                for sig in new_signals:
                    print(f"\n📡 SIGNAL: {sig.direction} @ ${sig.entry_price:,.2f}")
                    print(f"   SL: ${sig.stop_loss:,.2f} | TP: ${sig.take_profit:,.2f}")
                    print(f"   Strategy: {sig.strategy} | RR: 1:{sig.risk_reward:.1f}")

                    # Place order on demo account
                    qty = risk_mgr.calculate_position_size(sig)
                    if qty > 0:
                        result = place_real_order(
                            symbol=SYMBOL,
                            side=sig.direction.replace("LONG", "BUY").replace("SHORT", "SELL"),
                            quantity=qty,
                            order_type="MARKET"
                        )
                        print(f"   Order result: {json.dumps(result, default=str)}")

                        if db_ready:
                            from data.database import save_signal, open_position
                            sid = save_signal(sig, SYMBOL, True)
                            open_position(sid, SYMBOL, sig.direction, sig.strategy,
                                          sig.regime, sig.entry_price, last_time,
                                          qty, 0, sig.stop_loss, sig.take_profit,
                                          sig.risk_reward)
            else:
                print("⏸️  No signal this bar")

            # 7. Monitor open positions
            last_bar = df.iloc[-1]
            risk_mgr.check_exits(last_bar, last_time)

            # Snapshot
            print(f"\n📊 BTC: ${last_bar['close']:,.2f} | ATR: {last_bar['atr_pct']:.2f}% | RSI: {last_bar['rsi_14']:.0f}")

        except Exception as e:
            print(f"❌ Error: {e}")
            traceback.print_exc()
            if db_ready:
                db_log("ERROR", "engine", str(e))

        print(f"\n💤 Sleeping {LOOP_INTERVAL_SECONDS}s...")
        time.sleep(LOOP_INTERVAL_SECONDS)


def run_test_api():
    """Test API connection."""
    print("=" * 60)
    print("  API CONNECTION TEST")
    print("=" * 60)
    results = test_connection()
    print(json.dumps(results, indent=2, default=str))

    print("\nTest order:")
    test = place_test_order()
    print(json.dumps(test, indent=2, default=str))


def main():
    mode = os.getenv("TRADING_MODE", "backtest")

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default=mode, choices=["backtest", "live", "paper", "test-api"])
    args = parser.parse_args()

    if args.mode == "test-api":
        run_test_api()
    elif args.mode == "live":
        run_live()
    elif args.mode == "paper":
        os.environ["TRADING_MODE"] = "paper"
        run_live()
    else:
        run_backtest()


if __name__ == "__main__":
    main()
