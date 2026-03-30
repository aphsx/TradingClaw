#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════
  TRADINGCLAW v5
  Universal Crypto Futures
  Multi-Factor Signal Engine | HMM Regime | ML Ensemble
  Scaled Entry/Exit | Portfolio Heat | Drawdown-Adaptive
═══════════════════════════════════════════════════════════
"""
import time, sys, os, traceback, threading
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *

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
            print("[OK] MySQL connected")
            return True
        except Exception:
            print(f"[WAIT] DB... ({i+1}/{max_retries})")
            time.sleep(2)
    return False


def wait_for_redis(max_retries=15):
    from data.monitor import get_redis
    for i in range(max_retries):
        try:
            get_redis().ping()
            print("[OK] Redis connected")
            return True
        except Exception:
            print(f"[WAIT] Redis... ({i+1}/{max_retries})")
            time.sleep(1)
    return False


# ═══════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════
def _verify_order_placed(order_resp: dict, order_type: str) -> bool:
    if order_resp.get('_http_status', 0) != 200:
        print(f"[WARN] {order_type} order failed: {order_resp}")
        return False
    if 'orderId' not in order_resp:
        print(f"[WARN] {order_type} order missing orderId: {order_resp}")
        return False
    return True


def _with_retry(fn, *args, retries=3, **kwargs):
    for attempt in range(retries):
        try:
            result = fn(*args, **kwargs)
            if result.get('_http_status', 200) == 200:
                return result
        except Exception:
            if attempt < retries - 1:
                time.sleep(1 * (attempt + 1))
            else:
                raise
    return result


# Regime int → name map (mirrors core/regime_detector.py REGIME_NAMES)
# Defined here to avoid circular import with regime_detector ↔ signal_engine.
_REGIME_NAMES = {0: 'Trending-Up', 1: 'Ranging', 2: 'Volatile', 3: 'Trending-Down'}


def _signal_to_dict(sig, oi_score: float = 0.0) -> dict:
    # Resolve regime int → name so ml_filter.predict() regime_map can match it.
    # Without this fix Signal.regime (int 0-3) becomes "0","1"… which the ML mapper
    # can't find in {'Trending-Up':0, 'Ranging':1, …} and defaults everything to 1.
    regime_name = _REGIME_NAMES.get(sig.regime, getattr(sig, 'regime_name', 'Ranging'))
    return {
        'timestamp': sig.timestamp,
        'time': sig.timestamp,
        'direction': sig.direction,
        'entry_price': sig.entry_price,
        'stop_loss': sig.stop_loss,
        'take_profit': sig.take_profit,
        'confidence': sig.confidence,
        'risk_reward': sig.risk_reward,
        'expected_profit_pct': sig.expected_profit_pct,
        'composite_score': getattr(sig, 'composite_score', 0),
        'regime': regime_name,
        'strategy': sig.strategy,
        'oi_score': oi_score,   # Issue #10: OI score for ML feature extraction
    }


# ═══════════════════════════════════════
# LIVE TRADING
# ═══════════════════════════════════════
def run_live():
    import data.database as db
    import data.ccxt_client as bnb          # ← CCXT: all trading + OI / L/S ratio (delegated internally)
    import data.monitor as mon
    from data.socket_server import run_socket_server
    from data.http_api import run_http_server
    from data.fetcher import fetch_klines, fetch_multi_symbol

    from core.features import calculate_features, get_regime_features
    from core.regime_detector import RegimeDetector, REGIME_NAMES
    from core.risk_manager import RiskManager
    from core.ml_filter import MLSignalFilter
    from core.correlation import CorrelationManager
    from core.position_manager import PositionManager
    from core.execution_analytics import ExecutionAnalytics  # Issue #10
    from core.regime_monitor import RegimeMonitor
    from core.performance_guard import StrategyPerformanceGuard
    from core.event_risk import EventRiskManager                        # v6: Event-Driven Risk
    from strategies.signal_engine import SignalEngine
    from strategies.factors.orderbook_flow import OrderbookFlowFactor   # v6: Real Orderbook

    print("=" * 60)
    print(f"  TRADINGCLAW v5 — LIVE  |  Symbols: {SYMBOLS}")
    print("=" * 60)

    wait_for_db()
    wait_for_redis()

    run_socket_server(port=8080)
    run_http_server(port=8081)

    # ── Binance connection test ──
    conn = bnb.test_connection()
    print(f"[SOCKET] Binance ping={conn.get('ping')}")
    if conn.get("account", {}).get("connected"):
        bals = conn["account"]["balances"]
        for asset, b in list(bals.items())[:5]:
            print(f"   {asset}: {b['free']}")

    # ── Fetch real balance from Binance ──
    print("\n[BALANCE] Fetching live balance from Binance...")
    live_balance = bnb.get_usdt_balance()
    if live_balance > 0:
        print(f"   USDT balance: ${live_balance:.2f}")
    else:
        print("   [ERROR] Could not fetch real Binance balance (no demo fallback)")
        if INITIAL_CAPITAL > 0:
            print(f"   [WARN] INITIAL_CAPITAL is set (${INITIAL_CAPITAL:.2f}) but ignored in live mode")
        raise RuntimeError("Live mode requires real Binance balance; aborting startup")

    # ── Core components ──
    print("\n[FEES] Fetching exact exchange trading fees...")
    real_fees = bnb.get_trading_fees(SYMBOLS[0] if isinstance(SYMBOLS, list) and SYMBOLS else SYMBOL)
    print(f"   Taker: {real_fees['taker']*100:.3f}% | Maker: {real_fees['maker']*100:.3f}%")

    detector    = RegimeDetector()
    risk_mgr    = RiskManager(
        initial_capital=live_balance,
        taker_fee=real_fees['taker'],
        maker_fee=real_fees['maker'],
    )
    ml_filter   = MLSignalFilter(min_samples=ML_MIN_SAMPLES, threshold=ML_THRESHOLD)
    corr_mgr    = CorrelationManager(max_correlated=MAX_CORRELATED_POSITIONS,
                                     correlation_threshold=0.7)
    pos_mgr     = PositionManager()
    sig_engine  = SignalEngine(taker_fee=real_fees['taker'], maker_fee=real_fees['maker'])
    exec_analytics = ExecutionAnalytics(window=50)  # Issue #10
    regime_mon  = RegimeMonitor()                   # Per-regime circuit breakers
    perf_guard  = StrategyPerformanceGuard()        # Per strategy+regime after-fee guard
    event_risk  = EventRiskManager()               # v6: Event-driven risk gate
    ob_flow     = OrderbookFlowFactor()            # v6: Live orderbook microstructure

    # Shared dict for monitor thread to read current regime per symbol (no DB round-trip)
    _current_regimes: dict = {}  # symbol → {'regime': int, 'confidence': float}

    # Print tier info so operator knows what risk level is active
    print(f"   {risk_mgr.sync_capital(live_balance)}")

    is_trained   = False
    ml_trained   = False
    last_signal_time = {sym: None for sym in SYMBOLS}
    loop_count   = 0
    bars_since_retrain = {sym: 0 for sym in SYMBOLS}
    CAPITAL_SYNC_EVERY = 50  # Re-sync balance every N loops (~50 min on 1h tf)

    # ── Issue #1: ML Cold Start — pretrain on backtest trades before first live trade ──
    # pretrain_from_backtest() exists in MLSignalFilter but was never called at startup.
    # Without this, ML passes every signal through for the first ML_MIN_SAMPLES=50 trades.
    # We pretrain now so the filter is active from minute 1.
    if db_ready if 'db_ready' in dir() else False:
        pass  # handled below after first data fetch
    _ml_pretrained_attempted = False

    # ── Pending signal outcome tracker (ML bias fix) ──
    # All generated signals (including rejected) are tracked here.
    # Each loop checks bar high/low to see if SL/TP was TOUCHED on any bar since creation.
    # This prevents survivorship bias: a SL that was hit then recovered is still a loss.
    # Structure: {sig_id: {'signal': dict, 'entry': float, 'sl': float, 'tp': float,
    #                      'direction': str, 'symbol': str, 'created_at': datetime,
    #                      'adverse_extreme': float  ← worst price seen since signal (low for LONG, high for SHORT)
    #                      'favorable_extreme': float ← best price seen since signal}}
    _pending_outcomes: dict = {}
    _OUTCOME_MAX_AGE_HOURS = 48   # Discard unresolved signals after 48h
    _sig_id_counter = 0           # Simple counter for pending signal IDs

    # ── Set leverage and margin type ──
    if USE_FUTURES:
        print("\n[CONFIG]  Configuring futures...")
        for sym in SYMBOLS:
            try:
                bnb.set_leverage(sym, LEVERAGE)
                print(f"[OK] {sym}: {LEVERAGE}x")
            except Exception as e:
                print(f"[WARN] {sym}: leverage {e}")
            try:
                bnb.set_margin_type(sym, MARGIN_TYPE)
                print(f"[OK] {sym}: {MARGIN_TYPE}")
            except Exception:
                print(f"[WARN] {sym}: margin_type (may already be set)")

    # ── Reconcile positions ──
    try:
        print("\n[SYNC] Reconciling positions...")
        bp = bnb.get_position_risk(SYMBOL)
        rp = mon.get_open_positions_from_redis()
        print(f"   Binance: {len([p for p in bp if float(p.get('positionAmt',0)) != 0])} | Redis: {len(rp)}")
    except Exception as e:
        print(f"[WARN] Reconcile: {e}")

    mon.set_status("running", f"TradingClaw v5 | {SYMBOLS}")
    db.log("INFO", "engine", "TradingClaw v5 started", {"symbols": SYMBOLS})

    # ──────────────────────────
    # MONITOR THREAD
    # ──────────────────────────
    def monitor_loop():
        _ghost_check_counter = 0
        while True:
            try:
                with _position_lock:
                    price = bnb.get_price(SYMBOL)
                    mon.update_price(price)

                    # Margin check
                    if USE_FUTURES:
                        try:
                            account = bnb.get_futures_account()
                            margin_check = risk_mgr.check_margin_ratio(account)
                            mon.update_margin_ratio(account)
                            if margin_check["status"] == "emergency":
                                print(f"[EMERGENCY] EMERGENCY MARGIN {margin_check['ratio']:.1%} — CLOSING ALL!")
                                for pos in mon.get_open_positions_from_redis():
                                    close_side = 'SELL' if pos['direction'] == 'LONG' else 'BUY'
                                    try:
                                        bnb.place_market_order(pos['symbol'], close_side,
                                                               float(pos['quantity']))
                                        db.log("CRITICAL", "margin", f"Emergency #{pos.get('id')}", pos)
                                    except Exception as e:
                                        print(f"[WARN] Emergency close: {e}")
                            elif margin_check["status"] == "warning":
                                print(f"[WARN] Margin warning: {margin_check['ratio']:.1%}")
                        except Exception as e:
                            print(f"[WARN] Margin check: {e}")

                    open_positions = mon.get_open_positions_from_redis()
                    for pos in open_positions:
                        # ── Partial TP check ──
                        try:
                            partial = None if TAKE_PROFIT_MODE == "single" else pos_mgr.check_partial_tp(pos, price)
                            if partial and TRADING_MODE != "paper":
                                tp_qty = float(pos.get('quantity', 0)) * partial['fraction']
                                close_side = 'SELL' if pos['direction'] == 'LONG' else 'BUY'
                                close_resp = bnb.place_market_order(
                                    pos['symbol'], close_side, round(tp_qty, 6),
                                    reduce_only=True)
                                if close_resp.get('orderId'):
                                    tp_level = partial['tp_level']
                                    pos[f'tp{tp_level}_hit'] = True
                                    if tp_level == 1:
                                        # Move SL to breakeven after TP1
                                        new_sl = pos_mgr.move_to_breakeven(pos)
                                        pos['stop_loss'] = new_sl
                                    print(f"[OK] {partial['reason']} partial close #{pos.get('id')} "
                                          f"({partial['fraction']*100:.0f}%)")
                                    mon.publish_position_open(pos['id'], pos)
                        except Exception as e:
                            print(f"[WARN] Partial TP: {e}")

                        # ── Chandelier trailing stop ──
                        try:
                            new_sl = pos_mgr.update_trailing_stop(pos, price)
                            if new_sl and abs(new_sl - float(pos.get('stop_loss', 0))) > price * 0.0001:
                                print(f"[SYNC] Trail SL #{pos.get('id')}: {pos.get('stop_loss')} → {new_sl:.2f}")
                                pos['stop_loss'] = new_sl
                                if pos.get('sl_order_id') and TRADING_MODE != "paper":
                                    try:
                                        bnb.cancel_order(pos['symbol'], int(pos['sl_order_id']))
                                    except Exception:
                                        pass
                                    sl_side = 'SELL' if pos['direction'] == 'LONG' else 'BUY'
                                    new_sl_order = bnb.place_stop_loss_order(
                                        pos['symbol'], sl_side, float(pos['quantity']), new_sl)
                                    if new_sl_order.get('orderId'):
                                        pos['sl_order_id'] = new_sl_order['orderId']
                                        mon.publish_position_open(pos['id'], pos)
                        except Exception as e:
                            print(f"[WARN] Trail SL: {e}")

                        # ── Trailing TP (final leg) ──
                        try:
                            if pos.get('tp2_hit'):  # Final leg active
                                new_tp = pos_mgr.update_trailing_tp(pos, price)
                                if abs(new_tp - float(pos.get('take_profit', 0))) > price * 0.0001:
                                    print(f"[SYNC] Trail TP #{pos.get('id')}: {pos.get('take_profit')} → {new_tp:.2f}")
                                    pos['take_profit'] = new_tp
                                    if pos.get('tp_order_id') and TRADING_MODE != "paper":
                                        try:
                                            bnb.cancel_order(pos['symbol'], int(pos['tp_order_id']))
                                        except Exception:
                                            pass
                                        tp_side = 'SELL' if pos['direction'] == 'LONG' else 'BUY'
                                        new_tp_order = bnb.place_take_profit_order(
                                            pos['symbol'], tp_side, float(pos['quantity']), new_tp)
                                        if new_tp_order.get('orderId'):
                                            pos['tp_order_id'] = new_tp_order['orderId']
                                            mon.publish_position_open(pos['id'], pos)
                        except Exception as e:
                            print(f"[WARN] Trail TP: {e}")

                        # ── Trade health monitoring ──
                        try:
                            health = pos_mgr.check_trade_health(pos, price)
                            if health:
                                print(f"[HEALTH] {health['reason']}")
                                new_sl = health['new_sl']
                                pos['stop_loss'] = new_sl
                                pos['health_sl_tightened'] = True
                                # Replace SL order on exchange
                                if pos.get('sl_order_id') and TRADING_MODE != "paper":
                                    try:
                                        bnb.cancel_order(pos['symbol'], int(pos['sl_order_id']))
                                    except Exception:
                                        pass
                                    sl_side = 'SELL' if pos['direction'] == 'LONG' else 'BUY'
                                    new_sl_order = bnb.place_stop_loss_order(
                                        pos['symbol'], sl_side, float(pos['quantity']), new_sl)
                                    if new_sl_order.get('orderId'):
                                        pos['sl_order_id'] = new_sl_order['orderId']
                                mon.publish_position_open(pos['id'], pos)
                                db.log("WARN", "health", f"SL tightened #{pos['id']}", health)
                        except Exception as e:
                            print(f"[WARN] Health check: {e}")

                        # ── Regime flip exit ──
                        try:
                            sym = pos.get('symbol', SYMBOL)
                            reg_info = _current_regimes.get(sym, {})
                            current_reg_id  = reg_info.get('regime', -1)
                            entry_reg_id    = int(pos.get('entry_regime', current_reg_id))
                            if current_reg_id >= 0 and regime_mon.should_exit_on_regime_flip(
                                pos.get('direction', 'LONG'), entry_reg_id, current_reg_id
                            ):
                                print(f"[REGIME-FLIP] Adverse regime flip #{pos['id']} "
                                      f"({REGIME_NAMES.get(entry_reg_id,'?')} → "
                                      f"{REGIME_NAMES.get(current_reg_id,'?')}) — exiting")
                                close_side = 'SELL' if pos['direction'] == 'LONG' else 'BUY'
                                if TRADING_MODE != "paper":
                                    flip_order = bnb.place_market_order(
                                        pos['symbol'], close_side, float(pos['quantity']),
                                        reduce_only=True)
                                    if flip_order.get('orderId'):
                                        pnl = float(pos.get('unrealized_pnl', 0))
                                        r_mult = regime_mon.estimate_r_multiple(pos, price)
                                        regime_mon.record_outcome(entry_reg_id, r_mult, pos_id=pos.get('id'))
                                        mon.publish_position_close(pos['id'], {
                                            'exit_price': price, 'reason': 'Regime Flip',
                                            'pnl': pnl, 'r_multiple': r_mult,
                                        })
                                        db.log("WARN", "regime_flip", f"Exit #{pos['id']}", {
                                            'entry_regime': REGIME_NAMES.get(entry_reg_id),
                                            'exit_regime': REGIME_NAMES.get(current_reg_id),
                                            'r_multiple': r_mult,
                                        })
                        except Exception as e:
                            print(f"[WARN] Regime flip exit: {e}")

                        # ── Time/funding exit ──
                        try:
                            if pos_mgr.should_time_exit(pos):
                                print(f"[TIME] Time exit #{pos['id']}")
                                close_side = 'SELL' if pos['direction'] == 'LONG' else 'BUY'
                                if TRADING_MODE != "paper":
                                    close_order = bnb.place_market_order(
                                        pos['symbol'], close_side, float(pos['quantity']))
                                    if close_order.get('orderId'):
                                        mon.publish_position_close(pos['id'], {
                                            'exit_price': price, 'reason': 'Time Exit',
                                            'pnl': float(pos.get('unrealized_pnl', 0))
                                        })
                                        db.log("INFO", "monitor", f"Time exit #{pos['id']}", {})
                        except Exception as e:
                            print(f"[WARN] Time exit: {e}")

                    # Sync fills with Binance + record outcomes to regime_monitor
                    try:
                        # Snapshot positions before sync so we can compute R on closed ones
                        _pre_sync_positions = {p['id']: p for p in open_positions}
                        closed = mon.sync_open_positions_with_binance(db)
                        if closed:
                            db.log("INFO", "monitor", f"Synced {len(closed)} closes", {"ids": closed})
                            for closed_id in closed:
                                try:
                                    closed_pos = _pre_sync_positions.get(int(closed_id))
                                    if closed_pos:
                                        entry_regime = int(closed_pos.get('entry_regime', -1))
                                        if entry_regime >= 0:
                                            # Estimate exit price from unrealized PnL or last price
                                            r = regime_mon.estimate_r_multiple(closed_pos, price)
                                            regime_mon.record_outcome(entry_regime, r, pos_id=closed_id)
                                except Exception:
                                    pass
                    except Exception as e:
                        print(f"[WARN] Sync: {e}")

                    # Ghost cleanup every ~5 min (300s / MONITOR_INTERVAL_SECONDS)
                    _ghost_check_counter += 1
                    if _ghost_check_counter >= max(1, int(300 / max(MONITOR_INTERVAL_SECONDS, 1))):
                        _ghost_check_counter = 0
                        try:
                            removed = mon.cleanup_ghost_positions()
                            if removed:
                                db.log("INFO", "monitor", f"Ghost cleanup removed {len(removed)}", {"ids": removed})
                        except Exception as e:
                            print(f"[WARN] Ghost cleanup: {e}")

            except Exception as e:
                print(f"[WARN] Monitor loop: {e}")
            time.sleep(MONITOR_INTERVAL_SECONDS)

    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()
    print("[INFO] Monitor thread started")

    # ── Pending signal outcome checker ──
    def resolve_pending_outcomes(bar_ohlcv: dict):
        """
        Issue #1 fix — Survivorship Bias in ML Training.

        For every pending signal we track the WORST (adverse) price seen across
        ALL bars since the signal was created, using bar high/low — not just the
        spot price at check time.

        This catches the case where price dipped to SL then recovered: the old
        spot-price-only check would label it a winner, creating optimistic ML data.

        bar_ohlcv: {symbol: {'high': float, 'low': float, 'close': float}}
        Called once per main loop AFTER fetching fresh OHLCV data.
        """
        now = datetime.utcnow()
        resolved = []

        for sig_key, pending in list(_pending_outcomes.items()):
            sym = pending['symbol']
            direction = pending['direction']
            sl = pending['sl']
            tp = pending['tp']

            # ── Update high/low extremes from this bar ──
            bar = bar_ohlcv.get(sym)
            if bar:
                bar_high = bar.get('high', 0)
                bar_low  = bar.get('low', 0)
                if direction == 'LONG':
                    # Track lowest price seen (adverse = low, favorable = high)
                    if bar_low > 0:
                        pending['adverse_extreme'] = min(pending['adverse_extreme'], bar_low)
                    if bar_high > 0:
                        pending['favorable_extreme'] = max(pending['favorable_extreme'], bar_high)
                else:  # SHORT
                    # Track highest price seen (adverse = high, favorable = low)
                    if bar_high > 0:
                        pending['adverse_extreme'] = max(pending['adverse_extreme'], bar_high)
                    if bar_low > 0:
                        pending['favorable_extreme'] = min(pending['favorable_extreme'], bar_low)

            age_h = (now - pending['created_at']).total_seconds() / 3600
            adverse  = pending['adverse_extreme']
            favorable = pending['favorable_extreme']

            # ── Check if SL or TP was TOUCHED at any point ──
            # Order matters: SL check first (worst case realized)
            outcome = None
            if direction == 'LONG':
                if adverse > 0 and adverse <= sl:
                    outcome = 0   # SL was touched → loss
                elif favorable > 0 and favorable >= tp:
                    outcome = 1   # TP was touched (and SL wasn't hit first)
                elif age_h >= _OUTCOME_MAX_AGE_HOURS:
                    outcome = 0   # Expired without resolution → treat as loss
            else:  # SHORT
                if adverse > 0 and adverse >= sl:
                    outcome = 0
                elif favorable > 0 and favorable <= tp:
                    outcome = 1
                elif age_h >= _OUTCOME_MAX_AGE_HOURS:
                    outcome = 0

            if outcome is None:
                continue  # Still pending — price hasn't touched SL or TP yet

            # Issue #3: Persist simulated outcome to DB so ML can train on it
            try:
                sim_pnl = (tp - pending['entry'] if outcome == 1 else sl - pending['entry'])
                if direction == 'SHORT':
                    sim_pnl = -sim_pnl
                sig_dict = pending.get('signal', {})
                db.save_simulated_outcome(
                    symbol      = sym,
                    direction   = direction,
                    strategy    = sig_dict.get('strategy', 'SIM'),
                    regime      = sig_dict.get('regime', 'Ranging'),
                    entry_price = pending['entry'],
                    entry_time  = pending['created_at'],
                    stop_loss   = sl,
                    take_profit = tp,
                    risk_reward = sig_dict.get('risk_reward', 0),
                    confidence  = sig_dict.get('confidence', 0.5),
                    sim_pnl     = round(sim_pnl, 4),
                    outcome     = outcome,
                    composite_score = sig_dict.get('composite_score', 0),
                )
                db.log("DEBUG", "ml_signal", f"Simulated outcome sig={sig_key}",
                       {"outcome": outcome, "sim_pnl": round(sim_pnl, 4),
                        "direction": direction, "age_h": round(age_h, 1)})
            except Exception:
                pass
            resolved.append(sig_key)

        for k in resolved:
            _pending_outcomes.pop(k, None)
        if resolved:
            print(f"   [ML] ML: resolved {len(resolved)} pending signal outcomes")

    # ──────────────────────────
    # MAIN SIGNAL LOOP
    # ──────────────────────────
    while True:
        try:
            now = datetime.utcnow()
            loop_count += 1
            perf_guard.tick()  # advance bar counter for cooldown tracking
            print(f"\n{'─'*55}")
            print(f"[TIME] {now.strftime('%Y-%m-%d %H:%M:%S')} UTC  [#{loop_count}]")

            # ── Periodic capital re-sync from Binance ──
            if loop_count % CAPITAL_SYNC_EVERY == 0:
                try:
                    refreshed = bnb.get_usdt_balance()
                    if refreshed > 0:
                        msg = risk_mgr.sync_capital(refreshed)
                        print(msg)
                except Exception as e:
                    print(f"[WARN] Capital re-sync: {e}")

            # ── Fetch multi-symbol prices for correlation ──
            multi_data = {}
            try:
                multi_data = fetch_multi_symbol(SYMBOLS, interval=TIMEFRAME, lookback_days=30)
                for sym, sym_df in multi_data.items():
                    if not sym_df.empty and 'close' in sym_df.columns:
                        corr_mgr.update_prices(sym, sym_df['close'])
                        # v6: Update EventRisk price for anomaly detection
                        closes = sym_df['close'].tail(20).tolist()
                        if closes:
                            event_risk.update_price(sym, closes[-1], closes[:-1])
            except Exception as e:
                print(f"[WARN] Multi-symbol fetch: {e}")

            # ── Resolve pending signal outcomes for ML training (Issue #1 fix) ──
            # Pass bar OHLCV so resolver tracks worst price seen, not just spot price.
            try:
                bar_ohlcv_snap = {}
                for sym in SYMBOLS:
                    sym_df = multi_data.get(sym)
                    if sym_df is not None and not sym_df.empty:
                        last_bar = sym_df.iloc[-1]
                        bar_ohlcv_snap[sym] = {
                            'high':  float(last_bar.get('high',  last_bar['close'])),
                            'low':   float(last_bar.get('low',   last_bar['close'])),
                            'close': float(last_bar['close']),
                        }
                resolve_pending_outcomes(bar_ohlcv_snap)
            except Exception as e:
                print(f"[WARN] Pending outcome check: {e}")

            # ── Fetch funding rates for VolumeFlowFactor + EventRisk ──
            if USE_FUTURES:
                for sym in SYMBOLS:
                    try:
                        mark = bnb.get_mark_price(sym)
                        rate = float(mark.get("lastFundingRate", 0))
                        next_funding_ts = mark.get("nextFundingTime")
                        sig_engine.volume_flow.update_funding(sym, rate)
                        event_risk.update_funding(sym, rate, next_funding_ts)  # v6
                    except Exception:
                        pass

            # ── Issue #5: Fetch Open Interest + Long/Short Ratio ──
            if USE_FUTURES:
                for sym in SYMBOLS:
                    try:
                        oi_data = bnb.get_open_interest(sym)
                        curr_oi = oi_data.get('openInterest', 0)
                        if curr_oi > 0:
                            oi_hist = sig_engine.open_interest._oi_cache.get(sym, [])
                            prev_oi = oi_hist[-1] if oi_hist else 0
                            sig_engine.open_interest.update_oi(sym, curr_oi)
                            event_risk.update_oi(sym, curr_oi, prev_oi)  # v6
                    except Exception:
                        pass
                    try:
                        ls_data = bnb.get_long_short_ratio(sym, period='5m')
                        if ls_data.get('longRatio') is not None:
                            sig_engine.open_interest.update_long_short_ratio(
                                sym, ls_data['longRatio'])
                    except Exception:
                        pass

            # ── v6: Fetch orderbook snapshots for microstructure ──
            if ORDERFLOW_ENABLED:
                for sym in SYMBOLS:
                    try:
                        ob = bnb.exchange.fetch_order_book(sym, limit=20)
                        # Get latest close price from multi_data (already fetched above)
                        _sym_df = multi_data.get(sym)
                        sym_df_latest = (float(_sym_df['close'].iloc[-1])
                                         if _sym_df is not None and len(_sym_df) > 0 else 0.0)
                        ob_flow.update(sym, ob, current_price=sym_df_latest)
                    except Exception:
                        pass

            # ── Issue #6: Pre-compute BTC composite score as cross-symbol macro bias ──
            # BTC leads the crypto market — blend a small portion into all other signals.
            # Computed once per loop before the per-symbol signal loop.
            _btc_composite_last = 0.0
            _BTC_SYMBOL = 'BTCUSDT'
            if _BTC_SYMBOL in multi_data and not multi_data[_BTC_SYMBOL].empty:
                try:
                    btc_df_raw = multi_data[_BTC_SYMBOL]
                    btc_df_feat = calculate_features(btc_df_raw)
                    if len(btc_df_feat) >= 60:
                        btc_scores = sig_engine.compute_composite(
                            btc_df_feat,
                            regime=detector.get_current_regime(
                                get_regime_features(btc_df_feat).dropna()
                            ).get('regime', -1) if len(btc_df_feat) >= 50 else -1,
                            symbol=_BTC_SYMBOL,
                            btc_composite=0.0,   # BTC doesn't get blended with itself
                        )
                        _btc_composite_last = float(btc_scores['composite'].iloc[-1])
                        print(f"[LINK] BTC composite: {_btc_composite_last:+.3f} (macro bias for other pairs)")
                except Exception as e:
                    print(f"[WARN] BTC cross-symbol bias: {e}")

            for current_symbol in SYMBOLS:
                print(f"\n== {current_symbol} ==")

                # ── 1h data ──
                df = multi_data.get(current_symbol)
                if df is None or len(df) < 60:
                    df = fetch_klines(symbol=current_symbol, interval=TIMEFRAME, days=30)
                if len(df) < 60:
                    print(f"[WARN] Not enough data for {current_symbol}")
                    continue

                # ── 4h data ──
                df_4h = None
                try:
                    df_4h = fetch_klines(symbol=current_symbol, interval="4h", days=60)
                    if len(df_4h) >= 20:
                        df_4h = calculate_features(df_4h)
                    else:
                        df_4h = None
                except Exception as e:
                    print(f"[WARN] 4h fetch {current_symbol}: {e}")

                # ── Features ──
                df = calculate_features(df)
                feat = get_regime_features(df).dropna()
                ci = df.index.intersection(feat.index)
                df, feat = df.loc[ci], feat.loc[ci]

                if len(feat) < 50:
                    print(f"[WARN] Not enough features for {current_symbol}")
                    continue

                # ── Regime detection (fit first time or retrain) ──
                bars_since_retrain[current_symbol] = bars_since_retrain.get(current_symbol, 0) + 1
                needs_retrain = (
                    not is_trained or
                    bars_since_retrain.get(current_symbol, 0) >= HMM_RETRAIN_BARS
                )
                if needs_retrain and current_symbol == SYMBOLS[0]:
                    print("[ML] Training HMM regime detector...")
                    stats = detector.fit(df, feat)
                    print(f"   Model: {stats.get('model')} | States: {stats.get('state_map')}")
                    print(f"   Distribution: {stats.get('regime_distribution')}")
                    is_trained = True
                    bars_since_retrain[current_symbol] = 0

                current_regime = detector.get_current_regime(feat)
                rname = current_regime['regime_name']
                rconf = current_regime['confidence']
                regime_id = current_regime['regime']
                transitioning = current_regime.get('transitioning', False)
                print(f"[REGIME] Regime: {rname} ({rconf:.0%})"
                      + (" [FAST]transitioning" if transitioning else ""))
                mon.update_regime(rname, rconf, current_regime['probabilities'])

                # Publish current regime for monitor thread (regime flip exit)
                _current_regimes[current_symbol] = {'regime': regime_id, 'confidence': rconf}

                # Tick regime monitor bar counter (once per symbol per loop is fine)
                if current_symbol == SYMBOLS[0]:
                    regime_mon.tick()

                # ── ML filter training ──
                # Issue #1: Cold-start pretrain from backtest on first loop, before live filter
                if not _ml_pretrained_attempted and current_symbol == SYMBOLS[0]:
                    _ml_pretrained_attempted = True
                    try:
                        bt_trades = db.get_recent_trades(limit=500, source='BACKTEST')
                        if bt_trades is not None and len(bt_trades) >= ML_MIN_SAMPLES:
                            ml_filter.pretrain_from_backtest(bt_trades, df)
                            ml_trained = True
                            print(f"[ML] ML cold-start: pretrained on {len(bt_trades)} backtest trades")
                        else:
                            n = len(bt_trades) if bt_trades is not None else 0
                            print(f"[WARN] ML cold-start: only {n} backtest trades (need {ML_MIN_SAMPLES})")
                            # Also try SIMULATED outcomes from pending outcome tracker
                            sim_trades = db.get_recent_trades(limit=500, source='SIMULATED')
                            if sim_trades is not None and len(sim_trades) >= ML_MIN_SAMPLES:
                                ml_filter.pretrain_from_backtest(sim_trades, df)
                                ml_trained = True
                                print(f"[ML] ML cold-start: pretrained on {len(sim_trades)} simulated trades")
                    except Exception as e:
                        print(f"[WARN] ML cold-start: {e}")

                if not ml_trained or loop_count % 20 == 0:
                    if current_symbol == SYMBOLS[0]:
                        try:
                            recent_trades = db.get_recent_trades(limit=200)
                            if recent_trades is not None and len(recent_trades) >= ML_MIN_SAMPLES:
                                ml_filter.train(recent_trades, df)
                                ml_trained = True
                            else:
                                n = len(recent_trades) if recent_trades is not None else 0
                                print(f"[WARN] ML: {n}/{ML_MIN_SAMPLES} live trades")
                        except Exception as e:
                            print(f"[WARN] ML train: {e}")

                # ── Generate signals via multi-factor engine ──
                # Issue #6: pass BTC composite bias for non-BTC symbols
                _btc_bias = 0.0 if current_symbol == _BTC_SYMBOL else _btc_composite_last
                signals = sig_engine.generate_signals(
                    df, df_4h=df_4h, regime=regime_id, symbol=current_symbol,
                    btc_composite=_btc_bias,
                )

                last_bar = df.index[-1]
                new_sigs = [s for s in signals if s.timestamp == last_bar]

                # ── Track ALL new signals for ML outcome logging (bias fix) ──
                # Signals that get rejected by any filter still need their outcomes
                # tracked so ML can learn from complete data, not just executed trades.
                # Compute OI score for this symbol (Issue #10: pass to ML features)
                _oi_score_last = float(
                    sig_engine.oi_factor.score(df, symbol=current_symbol).iloc[-1]
                ) if len(df) > 0 else 0.0

                if last_bar != last_signal_time.get(current_symbol):
                    for raw_sig in new_sigs:
                        _sig_id_counter += 1
                        # Issue #1: initialize adverse/favorable extremes to entry price
                        # so the first bar's high/low extend them correctly
                        _pending_outcomes[f"{current_symbol}_{_sig_id_counter}"] = {
                            'signal':   _signal_to_dict(raw_sig, oi_score=_oi_score_last),
                            'entry':    raw_sig.entry_price,
                            'sl':       raw_sig.stop_loss,
                            'tp':       raw_sig.take_profit,
                            'direction': raw_sig.direction,
                            'symbol':   current_symbol,
                            'created_at': now,
                            # Track worst (adverse) and best (favorable) prices seen via bar high/low
                            'adverse_extreme':  raw_sig.entry_price,  # will move to min(low) for LONG
                            'favorable_extreme': raw_sig.entry_price, # will move to max(high) for LONG
                        }

                if last_bar == last_signal_time.get(current_symbol):
                    print("[SKIP]  Already processed this bar")
                elif new_sigs:
                    for sig in new_sigs:
                        score = getattr(sig, 'composite_score', 0)
                        print(f"\n[SIGNAL] {sig.direction} @ ${sig.entry_price:,.2f} "
                              f"| score={score:+.3f} | conf={sig.confidence:.0%}")
                        print(f"   SL: ${sig.stop_loss:,.2f} | TP1: ${sig.take_profit:,.2f} "
                              f"| TP2: ${sig.take_profit_2:,.2f}")
                        print(f"   Strategy: {sig.strategy}")

                        # ── Regime Monitor: circuit breaker + confidence gate ──
                        regime_ok, regime_reason = regime_mon.can_trade(regime_id, rconf)
                        if not regime_ok:
                            print(f"   [REGIME-MON] Blocked: {regime_reason}")
                            continue
                        regime_size_mult = regime_mon.get_size_multiplier(regime_id)

                        # ── Issue #7: Regime Transition Buffer ──
                        # Instead of hard-skipping all transition signals (which misses
                        # genuine breakouts), we reduce position size proportionally
                        # based on how uncertain the HMM regime is.
                        # transition_size_mult ∈ [0.3, 1.0] — never zero, never full.
                        transition_size_mult = 1.0
                        if transitioning:
                            # Use HMM confidence as the size scale.
                            # Low confidence (0.5) → 0.4x; high confidence (0.9) → 0.7x.
                            hmm_conf = current_regime.get('confidence', 0.5)
                            transition_size_mult = float(np.clip(hmm_conf * 0.80, 0.30, 0.70))
                            print(f"   [FAST] Regime transitioning (HMM conf={hmm_conf:.0%}) "
                                  f"— reducing size to {transition_size_mult:.0%}")

                        # ── Strategy Performance Guard ──
                        perf_ok, perf_reason = perf_guard.can_trade(
                            symbol=current_symbol,
                            timeframe=TIMEFRAME,
                            strategy=sig.strategy,
                            regime=regime_id,
                        )
                        if not perf_ok:
                            print(f"   [BLOCK] PerfGuard: {perf_reason}")
                            continue
                        perf_mult = perf_guard.get_size_multiplier(
                            symbol=current_symbol,
                            timeframe=TIMEFRAME,
                            strategy=sig.strategy,
                            regime=regime_id,
                        )
                        if perf_mult < 1.0:
                            print(f"   [PERF] Weak strategy perf: size×{perf_mult:.2f}")

                        # ── ML Filter ──
                        sig_dict = _signal_to_dict(sig, oi_score=_oi_score_last)
                        ml_result = ml_filter.predict(sig_dict, df)
                        print(f"   [ML] ML: {ml_result['reason']}")
                        if not ml_result['pass']:
                            continue

                        # ── Max open trades ──
                        open_pos = mon.get_open_positions_from_redis()
                        if len(open_pos) >= MAX_OPEN_TRADES:
                            print(f"   [BLOCK] Max open trades ({MAX_OPEN_TRADES})")
                            continue

                        # ── Portfolio heat check ──
                        heat_ok, heat_reason = risk_mgr.heat_allows_new_trade(open_pos, sig)
                        if not heat_ok:
                            print(f"   [BLOCK] {heat_reason}")
                            continue

                        # ── v6: Event-Driven Risk Gate ──
                        event_decision = event_risk.should_skip_entry(
                            current_symbol, sig.direction
                        )
                        if event_decision.skip:
                            print(f"   [BLOCK] EventRisk: {event_decision.reason}")
                            continue
                        event_size_mult = event_decision.size_mult
                        if event_decision.active_events:
                            print(f"   [EVENT] {', '.join(event_decision.active_events)} "
                                  f"→ size×{event_size_mult:.2f}")

                        # ── v6: Execution Quality Gate ──
                        exec_pause, exec_pause_reason = exec_analytics.should_pause_trading(
                            current_symbol
                        )
                        if exec_pause:
                            print(f"   [BLOCK] ExecQuality: {exec_pause_reason}")
                            continue
                        exec_slip_mult  = exec_analytics.get_sizing_penalty(current_symbol)
                        exec_fee_mult   = exec_analytics.get_adjusted_fee_multiplier(
                            base_multiplier=FEE_MULTIPLIER, symbol=current_symbol
                        )
                        if exec_slip_mult < 1.0:
                            print(f"   [EXEC] Slippage penalty: size×{exec_slip_mult:.2f} "
                                  f"fee_mult={exec_fee_mult:.2f}")

                        # ── Correlation check (v2: regime-aware) ──
                        corr_mgr.update_regime(
                            _current_regimes.get(current_symbol, {}).get("regime", -1)
                        )
                        corr_result = corr_mgr.can_open_position_v2(
                            current_symbol, sig.direction, open_pos
                        )
                        if not corr_result['allowed']:
                            print(f"   [BLOCK] Correlation: {corr_result['reason']}")
                            continue
                        if corr_result['correlated_with']:
                            print(f"   [INFO] Correlated with: {[c['symbol'] for c in corr_result['correlated_with']]}")

                        # ── v6: Orderbook flow confirmation ──
                        ob_score = 0.0
                        if ORDERFLOW_ENABLED and ob_flow.has_data(current_symbol):
                            ob_score = ob_flow.score(current_symbol, sig.direction)
                            spread_q = ob_flow.get_spread_quality(current_symbol)
                            if spread_q == "extreme":
                                print("   [WARN] OB spread extreme → reducing size")
                                exec_slip_mult *= 0.7
                            if ob_score != 0:
                                print(f"   [OB] Flow score: {ob_score:+.3f} | Spread: {spread_q}")

                        # ── Position size ──
                        # Kelly (tier-aware risk%) × drawdown × volatility × transition × regime × event × exec
                        qty = risk_mgr.calculate_position_size(sig)
                        dd_mult  = risk_mgr.get_drawdown_size_multiplier()
                        vol_mult = getattr(sig, 'vol_size_mult', 1.0)  # From VolatilityFactor
                        qty *= (dd_mult * vol_mult * transition_size_mult *
                                regime_size_mult * event_size_mult * exec_slip_mult * perf_mult)
                        qty = round(qty, 6)
                        tier = risk_mgr.get_tier_info()
                        print(f"   [BALANCE] Tier: {tier['tier']} | Risk: {tier['risk_pct']} "
                              f"(${tier['risk_amount_usd']}) | DD: {dd_mult:.2f}x | "
                              f"Vol: {vol_mult:.2f}x | Trans: {transition_size_mult:.2f}x | "
                              f"Regime: {regime_size_mult:.2f}x | Event: {event_size_mult:.2f}x | "
                              f"Exec: {exec_slip_mult:.2f}x | Qty: {qty}")
                        if qty <= 0:
                            print("   [BLOCK] Quantity zero after adjustments")
                            continue

                        # ── Funding rate check (kept for backward compat; EventRisk also checks) ──
                        if USE_FUTURES:
                            try:
                                mark = bnb.get_mark_price(current_symbol)
                                funding_rate = float(mark.get("lastFundingRate", 0))
                                if abs(funding_rate) > MAX_FUNDING_RATE:
                                    print(f"   [BLOCK] Funding too high: {funding_rate:.4%}")
                                    continue
                            except Exception as e:
                                print(f"   [WARN] Funding check: {e}")

                        # ── Place ENTRY order ──
                        side = "BUY" if sig.direction == "LONG" else "SELL"
                        print(f"   🔫 {side} {qty:.6f} {current_symbol}...")

                        if TRADING_MODE == "paper":
                            order_resp = {
                                "orderId": 0, "status": "PAPER",
                                "fills": [{"price": str(sig.entry_price), "qty": str(qty),
                                           "commission": "0", "commissionAsset": "USDT"}],
                                "_client_oid": "paper", "_http_status": 200
                            }
                        else:
                            order_resp = bnb.place_market_order(current_symbol, side, qty)

                        parsed = bnb.parse_order_response(order_resp)
                        print(f"   [OK] {parsed.get('status')}: fill=${parsed.get('fill_price'):,.2f}")

                        # Issue #10: record execution quality (expected vs actual fill)
                        if parsed.get('fill_price') and parsed.get('fill_qty', 0) > 0:
                            try:
                                exec_analytics.record(
                                    symbol=current_symbol,
                                    expected_price=sig.entry_price,
                                    actual_fill=float(parsed['fill_price']),
                                    side=side,
                                    quantity=float(parsed['fill_qty']),
                                )
                                eff_slip = exec_analytics.get_effective_slippage(current_symbol)
                                print(f"   [DATA] Exec: effective slippage={eff_slip*100:.3f}%")
                            except Exception:
                                pass

                        if parsed.get("status") not in ("FILLED", "PAPER"):
                            print(f"   [ERROR] Not filled: {parsed.get('status')}")
                            db.log("ERROR", "order", "Entry not filled", parsed)
                            continue

                        # Adjust SL/TP for entry slippage
                        fill_price = parsed.get("fill_price")
                        if fill_price and fill_price != sig.entry_price:
                            offset = float(fill_price) - sig.entry_price
                            sig.stop_loss += offset
                            sig.take_profit += offset
                            sig.take_profit_2 += offset
                            print(f"   [WARN] SL/TP offset by {offset:,.2f} (slippage)")

                        sig_id = db.save_signal(sig, current_symbol, source="LIVE")

                        # ── Place SL + TP (initial = TP1) ──
                        sl_oid, tp_oid = None, None
                        exit_side = "SELL" if sig.direction == "LONG" else "BUY"
                        if TRADING_MODE != "paper":
                            try:
                                sl_resp = _with_retry(bnb.place_stop_loss_order,
                                                      current_symbol, exit_side, qty, sig.stop_loss)
                                if _verify_order_placed(sl_resp, "SL"):
                                    sl_oid = sl_resp.get("orderId")
                                    print(f"   [SL] SL #{sl_oid} @ ${sig.stop_loss:,.2f}")
                            except Exception as e:
                                print(f"   [WARN] SL failed: {e}")

                            try:
                                tp_qty = qty if TAKE_PROFIT_MODE == "single" else qty * PARTIAL_TP_FRACTIONS[0]
                                tp_resp = _with_retry(bnb.place_take_profit_order,
                                                      current_symbol, exit_side,
                                                      round(tp_qty, 6), sig.take_profit)
                                if _verify_order_placed(tp_resp, "TP"):
                                    tp_oid = tp_resp.get("orderId")
                                    tp_label = "TP" if TAKE_PROFIT_MODE == "single" else "TP1"
                                    tp_pct = 100.0 if TAKE_PROFIT_MODE == "single" else PARTIAL_TP_FRACTIONS[0] * 100
                                    print(f"   [TARGET] {tp_label} #{tp_oid} @ ${sig.take_profit:,.2f} "
                                          f"({tp_pct:.0f}%)")
                            except Exception as e:
                                print(f"   [WARN] TP failed: {e}")

                        with _position_lock:
                            pos_id = db.open_position_live(
                                signal_id=sig_id, symbol=current_symbol,
                                direction=sig.direction, strategy=sig.strategy,
                                regime=sig.regime, entry_price=sig.entry_price,
                                entry_time=now, quantity=qty,
                                order_data=parsed,
                                stop_loss=sig.stop_loss, take_profit=sig.take_profit,
                                risk_reward=sig.risk_reward,
                                sl_order_id=sl_oid, tp_order_id=tp_oid,
                                confidence=sig.confidence,
                            )

                            mon.publish_position_open(pos_id, {
                                "source": "LIVE", "symbol": current_symbol,
                                "direction": sig.direction, "strategy": sig.strategy,
                                "entry_price": sig.entry_price,
                                "entry_fill_price": parsed.get("fill_price"),
                                "quantity": qty,
                                "stop_loss": sig.stop_loss,
                                "take_profit": sig.take_profit,
                                "take_profit_2": getattr(sig, 'take_profit_2', sig.take_profit),
                                "sl_order_id": sl_oid, "tp_order_id": tp_oid,
                                "entry_time": now.isoformat(),
                                "tp1_hit": False, "tp2_hit": False,
                                "composite_score": getattr(sig, 'composite_score', 0),
                                "ml_probability": ml_result.get("probability"),
                                # Regime monitoring: store entry regime for flip detection
                                "entry_regime": regime_id,
                            })

                            db.log("INFO", "trade", f"Opened #{pos_id}", {
                                "direction": sig.direction, "qty": qty,
                                "fill": parsed.get("fill_price"),
                                "composite": getattr(sig, 'composite_score', 0),
                                "ml_prob": ml_result.get("probability"),
                                "regime": rname,
                            })

                    last_signal_time[current_symbol] = last_bar
                else:
                    print("[SKIP]  No signal this bar")
                    last_signal_time[current_symbol] = last_bar

                # ── Market snapshot ──
                last = df.iloc[-1]
                price = last['close']
                print(f"[DATA] {current_symbol} ${price:,.2f} | ATR: {last.get('atr_pct',0):.2f}% "
                      f"| RSI: {last.get('rsi_14',0):.0f} | ADX: {last.get('adx',0):.0f}")

            # ── Portfolio risk score ──
            open_pos = mon.get_open_positions_from_redis()
            if len(open_pos) > 1:
                risk_score = corr_mgr.get_portfolio_risk_score(open_pos)
                heat = risk_mgr.get_portfolio_heat(open_pos)
                dd_mult = risk_mgr.get_drawdown_size_multiplier()
                print(f"\n[RESULT] Correlation: {risk_score:.2f} | Heat: {heat:.1%} | DD mult: {dd_mult:.2f}x")

            # ── Funding rates ──
            if USE_FUTURES:
                for sym in SYMBOLS:
                    try:
                        mark = bnb.get_mark_price(sym)
                        rate = float(mark.get("lastFundingRate", 0))
                        mon.update_funding_rates({
                            "symbol": sym, "rate": rate,
                            "mark_price": float(mark.get("markPrice", 0)),
                            "next_funding": mark.get("nextFundingTime")
                        })
                    except Exception:
                        pass

            # ── Regime monitor health report (every 10 loops) ──
            if loop_count % 10 == 0:
                health = regime_mon.get_health_report()
                print(f"[REGIME-MON] Health @ bar {health['bar_counter']}:")
                for reg_id, stats in health['regimes'].items():
                    if stats['total_trades'] > 0:
                        print(f"   {stats['name']}: {stats['total_trades']} trades | "
                              f"WR={stats['win_rate']} | avgR={stats['avg_r_recent']:+.2f} | "
                              f"consec_loss={stats['consecutive_losses']} | "
                              f"size_mult={stats['size_multiplier']:.0%}")

            # ── Equity update ──
            price = bnb.get_price(SYMBOL)
            unrealized = mon.update_price(price)
            mon.update_equity(risk_mgr.capital + unrealized, risk_mgr.initial_capital, unrealized, len(open_pos))

            # ── Publish v6 module status to Redis (for dashboard) ──────────────
            try:
                import redis as _redis, json as _json
                _r = _redis.Redis(host=os.getenv('REDIS_HOST', 'localhost'),
                                  port=int(os.getenv('REDIS_PORT', 6379)), decode_responses=True)
                # EventRisk snapshot
                _r.set('v6:event_risk', _json.dumps(
                    event_risk.get_risk_dashboard(SYMBOLS)), ex=120)
                # ExecutionAnalytics snapshot
                _r.set('v6:exec_analytics', _json.dumps(
                    exec_analytics.get_dashboard_metrics()), ex=120)
                # Correlation heatmap
                _r.set('v6:correlation', _json.dumps(
                    corr_mgr.get_correlation_heatmap()), ex=120)
                # OrderbookFlow spread quality per symbol
                ob_quality = {sym: ob_flow.get_spread_quality(sym) for sym in SYMBOLS}
                _r.set('v6:orderbook', _json.dumps(ob_quality), ex=120)
                # StrategyPerformanceGuard summary
                _r.set('v6:perf_guard', _json.dumps(perf_guard.get_report()), ex=120)
            except Exception:
                pass  # non-critical — dashboard degrades gracefully

        except Exception as e:
            print(f"[ERROR] Loop error: {e}")
            traceback.print_exc()
            mon.set_status("error", str(e))
            db.log("ERROR", "engine", str(e))

        print(f"\n[SLEEP] Next in {LOOP_INTERVAL_SECONDS}s...")
        time.sleep(LOOP_INTERVAL_SECONDS)


# ═══════════════════════════════════════
# BACKTEST
# ═══════════════════════════════════════
def run_backtest():
    from backtest.engine import BacktestEngine
    from data.fetcher import get_data

    print("=" * 60)
    print("  BACKTEST MODE")
    print("=" * 60)

    db_ready = wait_for_db()
    df = get_data(use_api=True, days=LOOKBACK_DAYS)
    if len(df) < 100:
        print("[ERROR] Not enough data")
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
