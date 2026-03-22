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
from core.risk_manager import RiskManager, FeeFilter
from strategies.strategies import generate_all_signals

# DB is optional (for standalone backtest without Docker)
try:
    from data.database import (save_candles, save_regimes, save_signal,
        open_position as db_open_position, close_position as db_close_position,
        save_equity_batch, save_backtest_run, log as db_log)
    HAS_DB = True
except Exception:
    HAS_DB = False


class BacktestEngine:
    def __init__(self, capital=INITIAL_CAPITAL, use_db=True):
        self.detector = RegimeDetector()
        self.risk_mgr = RiskManager(initial_capital=capital)
        self.fee_filter = FeeFilter()
        self.results = {}
        self.use_db = use_db and HAS_DB
        self._pos_id_counter = 0  # Counter for position IDs (instead of id())

    def run(self, df: pd.DataFrame, train_ratio: float = 0.6) -> dict:
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
        split_idx = int(len(df) * train_ratio)
        train_df, test_df = df.iloc[:split_idx], df.iloc[split_idx:]
        train_feat, test_feat = regime_features.iloc[:split_idx], regime_features.iloc[split_idx:]
        print(f"\n📊 Train: {len(train_df)} | Test: {len(test_df)}")

        # Step 3: Train
        print("\n🧠 Training regime detector...")
        train_stats = self.detector.fit(train_df, train_feat)
        print(f"   CV Accuracy:      {train_stats['cv_accuracy']}")
        print(f"   Holdout Accuracy: {train_stats.get('holdout_accuracy', 'N/A')}")

        # Step 4: Predict
        print("\n🔮 Predicting regimes...")
        test_regimes = self.detector.predict(test_feat)
        regime_counts = test_regimes.value_counts()
        for r, c in regime_counts.items():
            print(f"   {REGIME_NAMES[r]}: {c} ({c/len(test_regimes)*100:.1f}%)")

        # Save regimes to DB
        if self.use_db:
            regime_detail = self.detector.predict_with_confidence(test_feat)
            save_regimes(regime_detail, SYMBOL, TIMEFRAME)

        # Step 5: Signals
        print("\n📡 Generating signals...")
        all_signals = generate_all_signals(test_df, test_regimes)
        print(f"   Raw: {len(all_signals)}")

        # Step 6: Fee filter
        passed, rejected = self.fee_filter.filter_signals(all_signals)
        fee_stats = self.fee_filter.get_stats(all_signals, passed, rejected)
        print(f"\n💰 Fee filter: {fee_stats['passed']}/{fee_stats['total_signals']} passed")

        # Save signals to DB
        signal_id_map = {}
        if self.use_db:
            for s in all_signals:
                ff = s in passed
                sid = save_signal(s, SYMBOL, fee_filtered=ff)
                signal_id_map[s.timestamp] = sid  # Use timestamp instead of id()

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

            # Write closed positions to DB
            if self.use_db:
                for cp in list(self.risk_mgr.closed_positions):
                    pid = pos_db_ids.get(id(cp))
                    if pid and not getattr(cp, '_db_closed', False):
                        pnl_pct = cp.pnl / (cp.entry_price * cp.quantity) * 100 if cp.quantity > 0 else 0
                        # Remove the mysterious 0.5 multiplier on exit fees
                        db_close_position(pid, cp.exit_price, cp.exit_time,
                                          cp.exit_reason, cp.fees_paid,
                                          cp.pnl, pnl_pct, cp.fees_paid)
                        cp._db_closed = True

            self.risk_mgr.record_equity(idx, bar['close'])

            if idx in signal_map:
                for signal in signal_map[idx]:
                    pos = self.risk_mgr.open_position(signal, idx)
                    if pos:
                        executed += 1
                        if self.use_db:
                            sid = signal_id_map.get(signal.timestamp, None)
                            dbid = db_open_position(
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
                    # Remove the mysterious 0.5 multiplier on exit fees
                    db_close_position(pid, cp.exit_price, cp.exit_time,
                                      cp.exit_reason, cp.fees_paid,
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
                "cv_accuracy": train_stats['cv_accuracy'],
                "test_distribution": {REGIME_NAMES[r]: int(c) for r, c in regime_counts.items()},
                "feature_importance": {k: round(v, 4) for k, v in train_stats['top_features'].items()}},
            "fee_filter": fee_stats,
            "trading": trade_stats,
            "config": {"initial_capital": INITIAL_CAPITAL,
                       "risk_per_trade": f"{RISK_PER_TRADE*100}%",
                       "max_drawdown_limit": f"{MAX_DRAWDOWN*100}%",
                       "fee_per_trade": f"{TOTAL_FEE_PER_TRADE*100:.2f}%",
                       "fee_multiplier": FEE_MULTIPLIER}
        }

        self.test_df = test_df
        self.test_regimes = test_regimes
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
                result = self.run(test_df, train_ratio=1.0)  # Use full test set
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
