"""
Backtesting Engine - with MySQL storage
"""
import pandas as pd
import numpy as np
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from core.features import calculate_features, get_regime_features
from core.regime_detector import RegimeDetector, REGIME_NAMES
from core.risk_manager import RiskManager
from core.ml_filter import MLSignalFilter   # Issue #8: same ML filter as live trading
from strategies.signal_engine import SignalEngine

# DB is optional (for standalone backtest without Docker)
try:
    from data.database import (save_candles, save_regimes, save_signal,
        open_position_bt as db_open_position,    # fix: was 'open_position' (doesn't exist)
        close_position_bt as db_close_position,  # fix: was 'close_position' (doesn't exist)
        save_equity_batch, save_backtest_run, log as db_log)
    HAS_DB = True
except Exception:
    HAS_DB = False


class BacktestEngine:
    def __init__(self, capital=INITIAL_CAPITAL, use_db=True):
        self.detector  = RegimeDetector()
        self.risk_mgr  = RiskManager(initial_capital=capital)
        self.sig_engine = SignalEngine()
        # Issue #8: include same MLSignalFilter used in live trading
        self.ml_filter = MLSignalFilter(
            min_samples=ML_MIN_SAMPLES, threshold=ML_THRESHOLD)
        from core.correlation import CorrelationManager
        self.corr_mgr = CorrelationManager(max_correlated=MAX_CORRELATED_POSITIONS,
                                            correlation_threshold=0.7)
        self.results = {}
        self.use_db = use_db and HAS_DB
        self._pos_id_counter = 0  # Counter for position IDs (instead of id())

    def run(self, df: pd.DataFrame, train_ratio: float = 0.6,
            pretrained: bool = False) -> dict:
        print("\n" + "=" * 60)
        print("🚀 REGIME DETECTION BACKTEST")
        print("=" * 60)

        # Step 1: Features
        print("\n📐 Calculating features...")
        df = calculate_features(df)
        regime_features = get_regime_features(df)
        regime_features = regime_features.dropna()
        common_idx = df.index.intersection(regime_features.index)
        df = df.loc[common_idx]
        regime_features = regime_features.loc[common_idx]
        print(f"   {len(regime_features.columns)} features, {len(df)} bars")

        # Save candles to DB
        if self.use_db:
            save_candles(df, SYMBOL, TIMEFRAME)

        # Step 2: Split
        if pretrained:
            # Detector already fitted externally (e.g. walk-forward) — use entire df as test
            train_df, test_df = df.iloc[:0], df   # Empty train, full test
            train_feat, test_feat = regime_features.iloc[:0], regime_features
            train_stats = {'cv_accuracy': 'N/A (pretrained)', 'holdout_accuracy': 'N/A',
                           'model': 'pretrained'}
            print(f"\n📊 Pretrained mode | Test: {len(test_df)} bars (no retrain)")
        else:
            split_idx = int(len(df) * train_ratio)
            train_df, test_df = df.iloc[:split_idx], df.iloc[split_idx:]
            train_feat, test_feat = regime_features.iloc[:split_idx], regime_features.iloc[split_idx:]
            print(f"\n📊 Train: {len(train_df)} | Test: {len(test_df)}")

        # Step 3: Train (skipped when pretrained=True)
        if not pretrained:
            print("\n🧠 Training regime detector...")
            train_stats = self.detector.fit(train_df, train_feat)
            print(f"   CV Accuracy:      {train_stats['cv_accuracy']}")
            print(f"   Holdout Accuracy: {train_stats.get('holdout_accuracy', 'N/A')}")

        # Step 4: Predict regimes for DB/reporting ONLY (uses full sequence — OK for display)
        # NOTE: signal generation below uses per-bar prediction (no look-ahead).
        print("\n🔮 Predicting regimes (for reporting)...")
        test_regimes_report = self.detector.predict(test_feat)
        regime_counts = test_regimes_report.value_counts()
        for r, c in regime_counts.items():
            print(f"   {REGIME_NAMES[r]}: {c} ({c/len(test_regimes_report)*100:.1f}%)")

        # Save regimes to DB (full-sequence prediction is fine for visualisation)
        if self.use_db:
            regime_detail = self.detector.predict_with_confidence(test_feat)
            save_regimes(regime_detail, SYMBOL, TIMEFRAME)

        # Step 5: Signals — per-bar regime prediction (NO look-ahead bias)
        # HMM Viterbi on the full sequence sees future data → use get_current_regime()
        # on only the bars available up to each point in time.
        # A rolling window of REGIME_LOOKBACK bars keeps this O(n) instead of O(n²).
        REGIME_LOOKBACK = 120  # 120 1h bars = 5 days of regime context
        print(f"\n📡 Generating signals (no-lookahead, window={REGIME_LOOKBACK})...")
        all_signals = []
        for i in range(60, len(test_df)):
            bar_df = test_df.iloc[:i+1]
            # Regime from a rolling window — never uses bars after index i
            window_start = max(0, i + 1 - REGIME_LOOKBACK)
            bar_feat_window = test_feat.iloc[window_start:i+1]
            try:
                current_regime = self.detector.get_current_regime(bar_feat_window)
                regime_id = current_regime['regime']
            except Exception:
                regime_id = 1  # Fallback: Ranging
            sigs = self.sig_engine.generate_signals(bar_df, regime=regime_id)
            all_signals.extend(sigs)
        print(f"   Raw signals: {len(all_signals)}")

        # Issue #8: train ML filter on train-set trades (if DB available) then apply
        # This ensures backtest uses the SAME MLSignalFilter logic as live trading.
        _REGIME_NAMES_BT = {0: 'Trending-Up', 1: 'Ranging', 2: 'Volatile', 3: 'Trending-Down'}
        ml_trained_bt = False
        if self.use_db:
            try:
                from data.database import get_recent_trades
                bt_trades = get_recent_trades(limit=200)
                if bt_trades is not None and len(bt_trades) >= ML_MIN_SAMPLES:
                    self.ml_filter.train(bt_trades, train_df)
                    ml_trained_bt = True
                    print(f"   🤖 ML filter trained on {len(bt_trades)} trades")
            except Exception as e:
                print(f"   ⚠️  ML filter train (backtest): {e}")

        # Apply ML filter to backtest signals when trained
        if ml_trained_bt:
            def _sig_to_dict_bt(s):
                return {
                    'timestamp': s.timestamp, 'time': s.timestamp,
                    'direction': s.direction, 'entry_price': s.entry_price,
                    'stop_loss': s.stop_loss, 'take_profit': s.take_profit,
                    'confidence': s.confidence, 'risk_reward': s.risk_reward,
                    'expected_profit_pct': s.expected_profit_pct,
                    'composite_score': getattr(s, 'composite_score', 0),
                    'regime': _REGIME_NAMES_BT.get(s.regime, 'Ranging'),
                    'strategy': s.strategy,
                }
            ml_passed = []
            ml_rejected = 0
            for s in all_signals:
                try:
                    res = self.ml_filter.predict(_sig_to_dict_bt(s), train_df)
                    if res['pass']:
                        ml_passed.append(s)
                    else:
                        ml_rejected += 1
                except Exception:
                    ml_passed.append(s)  # On error, keep signal
            print(f"   🤖 ML filter: {len(ml_passed)} passed, {ml_rejected} rejected")
            all_signals = ml_passed

        # Save signals to DB
        signal_id_map = {}
        passed = all_signals  # Fee filter now integrated into SignalEngine
        if self.use_db:
            for s in all_signals:
                sid = save_signal(s, SYMBOL, fee_filtered=True)
                signal_id_map[s.timestamp] = sid

        # Step 7: Execute
        print("\n⚡ Executing backtest...")
        self.risk_mgr.reset()
        signal_map = {}
        for s in passed:
            signal_map.setdefault(s.timestamp, []).append(s)

        # Track DB position IDs
        pos_db_ids = {}
        executed = 0

        for idx, bar in test_df.iterrows():
            # check_exits applies SLIPPAGE to make SL/TP prices realistic
            self.risk_mgr.check_exits(bar, idx)

            # ── Fix #2a: Breakeven stop — move SL to entry once 1R profit is touched ──
            for pos in list(self.risk_mgr.open_positions):
                sig = pos.signal
                risk = abs(pos.entry_price - sig.stop_loss)
                if risk > 0:
                    if sig.direction == "LONG":
                        unrealized_r = (bar['high'] - pos.entry_price) / risk
                        if unrealized_r >= 1.0 and sig.stop_loss < pos.entry_price:
                            sig.stop_loss = pos.entry_price * 1.001  # breakeven + tiny buffer
                    else:
                        unrealized_r = (pos.entry_price - bar['low']) / risk
                        if unrealized_r >= 1.0 and sig.stop_loss > pos.entry_price:
                            sig.stop_loss = pos.entry_price * 0.999

            # ── Fix #2b: Trailing stop — trail behind close once activation threshold met ──
            for pos in list(self.risk_mgr.open_positions):
                sig = pos.signal
                pos_dict = {
                    'entry_price': pos.entry_price,
                    'stop_loss': sig.stop_loss,
                    'direction': sig.direction,
                    'quantity': pos.quantity,
                }
                new_sl = self.risk_mgr.update_trailing_stop(pos_dict, bar['close'])
                if sig.direction == "LONG" and new_sl > sig.stop_loss:
                    sig.stop_loss = new_sl
                elif sig.direction == "SHORT" and new_sl < sig.stop_loss:
                    sig.stop_loss = new_sl

            # ── Fix #2c: Time-based exit — close stale unprofitable positions after 12h ──
            for pos in list(self.risk_mgr.open_positions):
                sig = pos.signal
                age_hours = (idx - pos.entry_time).total_seconds() / 3600
                if sig.direction == "LONG":
                    unrealized = (bar['close'] - pos.entry_price) * pos.quantity
                else:
                    unrealized = (pos.entry_price - bar['close']) * pos.quantity
                if age_hours > 12 and unrealized <= 0:
                    self.risk_mgr._close_position(pos, bar['close'], "Time Exit", idx)

            # Write closed positions to DB
            if self.use_db:
                for cp in list(self.risk_mgr.closed_positions):
                    pid = pos_db_ids.get(id(cp))
                    if pid and not getattr(cp, '_db_closed', False):
                        pnl_pct = cp.pnl / (cp.entry_price * cp.quantity) * 100 if cp.quantity > 0 else 0
                        db_close_position(pid, cp.exit_price, cp.exit_time,
                                          cp.exit_reason,
                                          cp.pnl, pnl_pct, cp.fees_paid)
                        cp._db_closed = True

            self.risk_mgr.record_equity(idx, bar['close'])

            if idx in signal_map:
                for signal in signal_map[idx]:
                    # ── Correlation check (mirrors live trading, issue #4) ──
                    open_pos_dicts = [
                        {'symbol': SYMBOL, 'direction': p.signal.direction}
                        for p in self.risk_mgr.open_positions
                    ]
                    corr_result = self.corr_mgr.can_open_position(
                        SYMBOL, signal.direction, open_pos_dicts)
                    if not corr_result['allowed']:
                        continue  # Skip correlated signal

                    pos = self.risk_mgr.open_position(signal, idx)
                    if pos:
                        # ── Fix #5: Scale position size by signal confidence + volatility ──
                        # CRITICAL: open_position() already locked capital for the FULL
                        # quantity. We MUST refund the unused portion before reducing
                        # pos.quantity, otherwise capital leaks and the circuit breaker
                        # falsely triggers on the very next trade.
                        conf = abs(signal.composite_score)
                        if conf < 0.50:
                            size_mult = 0.5    # Weak signal → half size
                        elif conf < 0.65:
                            size_mult = 0.75   # Moderate signal → 3/4 size
                        else:
                            size_mult = 1.0    # Strong signal → full size

                        total_mult = size_mult * signal.vol_size_mult
                        if total_mult < 1.0 and pos.quantity > 0:
                            original_qty = pos.quantity
                            new_qty = round(original_qty * total_mult, 6)
                            qty_delta = original_qty - new_qty
                            if qty_delta > 0:
                                # Refund the capital + entry fee for the unused portion
                                notional_refund = qty_delta * pos.entry_price
                                fee_refund      = notional_refund * TAKER_FEE
                                self.risk_mgr.capital += notional_refund + fee_refund
                                # Adjust fees_paid proportionally
                                pos.fees_paid = round(pos.fees_paid * (new_qty / original_qty), 8)
                                pos.quantity  = new_qty
                        # Note: total_mult > 1.0 (low-vol boost) is capped at original qty;
                        # scaling up would require additional capital checks.

                        executed += 1
                        if self.use_db:
                            sid = signal_id_map.get(signal.timestamp, None)
                            dbid = db_open_position(
                                None,  # run_id (filled in after save_backtest_run)
                                sid, SYMBOL, signal.direction, signal.strategy,
                                signal.regime, pos.entry_price, idx, pos.quantity,
                                pos.fees_paid, signal.stop_loss, signal.take_profit,
                                signal.risk_reward)
                            pos_db_ids[id(pos)] = dbid

        # Force close remaining
        if self.risk_mgr.open_positions:
            self.risk_mgr.force_close_all(test_df.iloc[-1]['close'], test_df.index[-1])

        # Close remaining in DB
        if self.use_db:
            for cp in self.risk_mgr.closed_positions:
                pid = pos_db_ids.get(id(cp))
                if pid and not getattr(cp, '_db_closed', False):
                    pnl_pct = cp.pnl / (cp.entry_price * cp.quantity) * 100 if cp.quantity > 0 else 0
                    db_close_position(pid, cp.exit_price, cp.exit_time,
                                      cp.exit_reason,
                                      cp.pnl, pnl_pct, cp.fees_paid)
                    cp._db_closed = True

        print(f"   Executed: {executed} trades")

        # Step 8: Results
        trade_stats = self.risk_mgr.get_stats()

        self.results = {
            "data": {"symbol": SYMBOL, "timeframe": TIMEFRAME,
                     "total_bars": len(df), "test_bars": len(test_df),
                     "test_period": f"{test_df.index[0]} → {test_df.index[-1]}"},
            "regime_detection": {
                "model": train_stats.get('model', 'HMM'),
                "state_map": train_stats.get('state_map', {}),
                "test_distribution": {REGIME_NAMES[r]: int(c) for r, c in regime_counts.items()},
            },
            "trading": trade_stats,
            "config": {"initial_capital": INITIAL_CAPITAL,
                       "risk_per_trade": f"{RISK_PER_TRADE*100}%",
                       "max_drawdown_limit": f"{MAX_DRAWDOWN*100}%",
                       "fee_per_trade": f"{TOTAL_FEE_PER_TRADE*100:.2f}%",
                       "fee_multiplier": FEE_MULTIPLIER}
        }

        self.test_df = test_df
        self.test_regimes = test_regimes_report  # Issue #8: fix NameError (was 'test_regimes')
        self.equity_curve = self.risk_mgr.equity_curve
        self.closed_positions = self.risk_mgr.closed_positions

        # Save equity + run to DB
        if self.use_db and self.equity_curve:
            # Add drawdown info
            equities = [e['equity'] for e in self.equity_curve]
            peak = equities[0]
            for e in self.equity_curve:
                peak = max(peak, e['equity'])
                e['peak_equity'] = peak
                e['drawdown_pct'] = (peak - e['equity']) / peak * 100 if peak > 0 else 0
            save_equity_batch(self.equity_curve)
            save_backtest_run(self.results, self.results['config'])
            db_log("INFO", "backtest", "Backtest completed", self.results['trading'])

        self._print_results()
        return self.results

    def _print_results(self):
        t = self.results.get('trading', {})
        if 'error' in t:
            print(f"❌ {t['error']}"); return

        print(f"\n{'='*60}\n📈 BACKTEST RESULTS\n{'='*60}")
        for k, v in [("Total Trades", t['total_trades']), ("Win Rate", t['win_rate']),
                      ("Profit Factor", t['profit_factor']),
                      ("Total PnL", f"${t['total_pnl']}"),
                      ("Fees Paid", f"${t['total_fees_paid']}"),
                      ("Max Drawdown", t['max_drawdown']),
                      ("Final Capital", f"${t['final_capital']}"),
                      ("Return", t['return_pct']),
                      ("Sharpe", t.get('sharpe_ratio', t.get('sharpe_approx', 'N/A')))]:
            print(f"  {k:<25} {str(v):>15}")

        for name, stats in t.get('strategy_breakdown', {}).items():
            print(f"  {name}: {stats['trades']}T WR={stats['win_rate']} PnL=${stats['pnl']:.2f}")

    def run_walk_forward(self, df: pd.DataFrame, train_pct: float = 0.6,
                          step_pct: float = 0.1) -> list:
        """
        Walk-forward backtest: train on first 60%, test on next 10%,
        then expand window and repeat.
        Returns list of result dicts per window.
        """
        results = []
        n = len(df)
        train_size = int(n * train_pct)
        step_size = int(n * step_pct)

        window_start = 0
        test_start = train_size

        while test_start + step_size <= n:
            train_df = df.iloc[window_start:test_start]
            test_df = df.iloc[test_start:test_start + step_size]

            # Train regime detector on this window
            try:
                from core.features import calculate_features, get_regime_features
                train_df_features = calculate_features(train_df)
                train_feat = get_regime_features(train_df_features).dropna()
                self.detector.fit(train_df_features, train_feat)

                # Run test
                result = self.run(test_df, pretrained=True)  # Use already-fitted detector
                results.append(result)
            except Exception as e:
                print(f"Walk-forward window failed: {e}")

            # Expand window (anchored walk-forward)
            test_start += step_size

        return results

    def get_trade_log(self) -> pd.DataFrame:
        if not self.closed_positions:
            return pd.DataFrame()
        records = []
        for p in self.closed_positions:
            records.append({
                'entry_time': p.entry_time, 'exit_time': p.exit_time,
                'direction': p.signal.direction, 'strategy': p.signal.strategy,
                'regime': REGIME_NAMES[p.signal.regime],
                'entry_price': round(p.entry_price, 2),
                'exit_price': round(p.exit_price, 2),
                'quantity': p.quantity, 'pnl': round(p.pnl, 2),
                'fees': round(p.fees_paid, 2), 'exit_reason': p.exit_reason})
        return pd.DataFrame(records)
