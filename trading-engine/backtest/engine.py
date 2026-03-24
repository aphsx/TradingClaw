"""
Backtesting Engine v3
=====================
Changes from v2:
- Removed MLSignalFilter (not needed — 3 clear strategies handle signal quality)
- Added RegimeMonitor trade health checks (regime-flip exit + tighten SL)
- Passes regime_confidence to SignalEngine
- Cleaner loop structure
"""
import pandas as pd
import numpy as np
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from core.features import calculate_features, get_regime_features
from core.regime_detector import RegimeDetector, REGIME_NAMES
from core.risk_manager import RiskManager
from core.regime_monitor import RegimeMonitor
from core.ml_filter import WalkForwardMLFilter
from strategies.signal_engine import SignalEngine

try:
    from data.database import (save_candles, save_regimes, save_signal,
        open_position_bt as db_open_position,
        close_position_bt as db_close_position,
        save_equity_batch, save_backtest_run, log as db_log)
    HAS_DB = True
except Exception:
    HAS_DB = False


class BacktestEngine:

    def __init__(self, capital=INITIAL_CAPITAL, use_db=True):
        # Fetch real broker fees if available, else use config defaults
        try:
            from data.ccxt_client import get_trading_fees
            fees = get_trading_fees(SYMBOL)
            self.taker_fee = fees['taker']
            self.maker_fee = fees['maker']
            print(f"[FEES] Real fees: Taker={self.taker_fee*100:.3f}% Maker={self.maker_fee*100:.3f}%")
        except Exception:
            self.taker_fee = TAKER_FEE
            self.maker_fee = MAKER_FEE

        self.detector   = RegimeDetector()
        self.risk_mgr   = RiskManager(initial_capital=capital, taker_fee=self.taker_fee)
        self.sig_engine = SignalEngine(taker_fee=self.taker_fee, maker_fee=self.maker_fee)
        self.monitor    = RegimeMonitor()
        self.ml_filter  = WalkForwardMLFilter()  # walk-forward, zero-leakage ML gate

        try:
            from core.correlation import CorrelationManager
            self.corr_mgr = CorrelationManager(
                max_correlated=MAX_CORRELATED_POSITIONS, correlation_threshold=0.7)
        except Exception:
            self.corr_mgr = None

        self.results  = {}
        self.use_db   = use_db and HAS_DB

    def run(self, df: pd.DataFrame, train_ratio: float = 0.6,
            pretrained: bool = False) -> dict:
        print("\n" + "=" * 60)
        print("[START] REGIME DETECTION BACKTEST")
        print("=" * 60)

        # ── Step 1: Features ──
        print("\n📐 Calculating features...")
        df = calculate_features(df)
        regime_features = get_regime_features(df).dropna()
        common_idx      = df.index.intersection(regime_features.index)
        df              = df.loc[common_idx]
        regime_features = regime_features.loc[common_idx]
        print(f"   {len(regime_features.columns)} features, {len(df)} bars")

        if self.use_db:
            save_candles(df, SYMBOL, TIMEFRAME)

        # ── Step 2: Train/test split ──
        if pretrained:
            train_df  = df.iloc[:0]
            test_df   = df
            train_feat = regime_features.iloc[:0]
            test_feat  = regime_features
            train_stats = {'cv_accuracy': 'Rule-based (pretrained)', 'model': 'RuleBased'}
            print(f"\n[DATA] Pretrained | Test: {len(test_df)} bars")
        else:
            split_idx  = int(len(df) * train_ratio)
            train_df   = df.iloc[:split_idx]
            test_df    = df.iloc[split_idx:]
            train_feat = regime_features.iloc[:split_idx]
            test_feat  = regime_features.iloc[split_idx:]
            print(f"\n[DATA] Train: {len(train_df)} | Test: {len(test_df)}")

        # ── Step 3: Fit regime detector ──
        if not pretrained:
            print("\n[ML] Training regime detector...")
            train_stats = self.detector.fit(train_df, train_feat)
            print(f"   CV Accuracy:      {train_stats['cv_accuracy']}")
            print(f"   Holdout Accuracy: {train_stats.get('holdout_accuracy', 'N/A')}")

        # ── Step 4: Predict regimes for reporting ──
        print("\n[REGIME] Predicting regimes (for reporting)...")
        test_regimes_report = self.detector.predict(test_feat)
        regime_counts       = test_regimes_report.value_counts()
        for r, c in regime_counts.items():
            print(f"   {REGIME_NAMES[r]}: {c} ({c/len(test_regimes_report)*100:.1f}%)")

        if self.use_db:
            regime_detail = self.detector.predict_with_confidence(test_feat)
            save_regimes(regime_detail, SYMBOL, TIMEFRAME)

        # ── Step 5: Generate signals (no look-ahead) ──
        REGIME_LOOKBACK = 120
        print(f"\n[SIGNAL] Generating signals (no-lookahead, window={REGIME_LOOKBACK})...")
        all_signals = []
        ml_feat_map = {}   # signal.timestamp → ML feature vector (extracted at signal time)
        for i in range(60, len(test_df)):
            bar_df       = test_df.iloc[:i + 1]
            window_start = max(0, i + 1 - REGIME_LOOKBACK)
            feat_window  = test_feat.iloc[window_start:i + 1]
            try:
                cur_regime   = self.detector.get_current_regime(feat_window)
                regime_id    = cur_regime['regime']
                regime_conf  = cur_regime.get('confidence', 0.5)
            except Exception:
                regime_id   = 1
                regime_conf = 0.5

            sigs = self.sig_engine.generate_signals(
                bar_df, regime=regime_id, regime_confidence=regime_conf)

            for s in sigs:
                # Extract ML features NOW (at signal bar) — strictly backward-looking
                ml_feats = self.ml_filter.extract_features(bar_df, s, regime_id, regime_conf)
                ml_feat_map[id(s)] = ml_feats

            all_signals.extend(sigs)

        print(f"   Raw signals: {len(all_signals)}")

        # Save signals to DB
        signal_id_map = {}
        if self.use_db:
            for s in all_signals:
                sid = save_signal(s, SYMBOL, fee_filtered=True)
                signal_id_map[s.timestamp] = sid

        # ── Step 6: Execute backtest loop ──
        print("\n[FAST] Executing backtest...")
        self.risk_mgr.reset()
        signal_map = {}
        for s in all_signals:
            signal_map.setdefault(s.timestamp, []).append(s)

        pos_db_ids    = {}
        executed      = 0
        # Maps position id → ML feature vector used to generate its signal
        # Needed to record outcome when the position closes
        pos_ml_feats: dict = {}

        # Pre-compute per-bar regime for trade health monitor
        bar_regime_map = {}
        for i in range(len(test_df)):
            window_start = max(0, i + 1 - REGIME_LOOKBACK)
            feat_window  = test_feat.iloc[window_start:i + 1]
            try:
                cur = self.detector.get_current_regime(feat_window)
                bar_regime_map[test_df.index[i]] = cur['regime']
            except Exception:
                bar_regime_map[test_df.index[i]] = 1

        for idx, bar in test_df.iterrows():
            self.monitor.tick()
            current_regime_for_bar = bar_regime_map.get(idx, 1)

            # ── Check exits (SL/TP hits) ──
            self.risk_mgr.check_exits(bar, idx)

            # ── Breakeven stop: move SL to entry once 1R touched ──
            for pos in list(self.risk_mgr.open_positions):
                sig  = pos.signal
                risk = abs(pos.entry_price - sig.stop_loss)
                if risk > 0:
                    if sig.direction == "LONG":
                        unrealized_r = (bar['high'] - pos.entry_price) / risk
                        if unrealized_r >= 1.0 and sig.stop_loss < pos.entry_price:
                            sig.stop_loss = pos.entry_price * 1.001
                    else:
                        unrealized_r = (pos.entry_price - bar['low']) / risk
                        if unrealized_r >= 1.0 and sig.stop_loss > pos.entry_price:
                            sig.stop_loss = pos.entry_price * 0.999

            # ── Trailing stop ──
            for pos in list(self.risk_mgr.open_positions):
                sig      = pos.signal
                pos_dict = {
                    'entry_price': pos.entry_price,
                    'stop_loss':   sig.stop_loss,
                    'direction':   sig.direction,
                    'quantity':    pos.quantity,
                }
                new_sl = self.risk_mgr.update_trailing_stop(pos_dict, bar['close'])
                if sig.direction == "LONG" and new_sl > sig.stop_loss:
                    sig.stop_loss = new_sl
                elif sig.direction == "SHORT" and new_sl < sig.stop_loss:
                    sig.stop_loss = new_sl

            # ── Trade health monitor (regime flip + tighten SL + time stop) ──
            for pos in list(self.risk_mgr.open_positions):
                sig        = pos.signal
                age_hours  = (idx - pos.entry_time).total_seconds() / 3600
                pos_dict   = {
                    'entry_fill_price': pos.entry_price,
                    'entry_price':      pos.entry_price,
                    'stop_loss':        sig.stop_loss,
                    'direction':        sig.direction,
                    'regime':           sig.regime,
                }
                action = self.monitor.check_trade_health(
                    pos_dict, bar['close'], current_regime_for_bar, age_hours)

                if action.action == "exit":
                    self.risk_mgr._close_position(
                        pos, bar['close'], f"Monitor: {action.reason}", idx)
                elif action.action == "tighten_sl" and action.new_sl is not None:
                    if sig.direction == "LONG" and action.new_sl > sig.stop_loss:
                        sig.stop_loss = action.new_sl
                    elif sig.direction == "SHORT" and action.new_sl < sig.stop_loss:
                        sig.stop_loss = action.new_sl

            # ── Record R-multiples for regime monitor + ML filter outcomes ──
            for cp in list(self.risk_mgr.closed_positions):
                if not getattr(cp, '_monitor_recorded', False):
                    r = self.monitor.estimate_r_multiple(
                        {'entry_fill_price': cp.entry_price,
                         'stop_loss': cp.signal.stop_loss,
                         'direction': cp.signal.direction},
                        cp.exit_price)
                    self.monitor.record_outcome(cp.signal.regime, r)
                    cp._monitor_recorded = True

                    # Walk-forward ML: record outcome AFTER trade closes (no leakage)
                    ml_feats = pos_ml_feats.get(id(cp))
                    if ml_feats is not None:
                        self.ml_filter.record_outcome(ml_feats, won=(cp.pnl > 0))

            # Write closed positions to DB
            if self.use_db:
                for cp in list(self.risk_mgr.closed_positions):
                    pid = pos_db_ids.get(id(cp))
                    if pid and not getattr(cp, '_db_closed', False):
                        pnl_pct = cp.pnl / (cp.entry_price * cp.quantity) * 100 \
                                  if cp.quantity > 0 else 0
                        db_close_position(pid, cp.exit_price, cp.exit_time,
                                          cp.exit_reason, cp.pnl, pnl_pct, cp.fees_paid)
                        cp._db_closed = True

            self.risk_mgr.record_equity(idx, bar['close'])

            # ── Open new positions ──
            if idx in signal_map:
                for signal in signal_map[idx]:
                    # Regime monitor gate
                    mon_ok, mon_reason = self.monitor.can_trade(
                        signal.regime, getattr(signal, 'confidence', 0.5))
                    if not mon_ok:
                        continue

                    # Walk-forward ML gate (zero-leakage — trained only on past closed trades)
                    ml_feats  = ml_feat_map.get(id(signal))
                    if ml_feats is not None:
                        ml_dec = self.ml_filter.should_trade(ml_feats)
                        if not ml_dec.allowed:
                            continue
                    else:
                        ml_feats = None  # no features available → allow (warming up)

                    # Correlation gate
                    if self.corr_mgr is not None:
                        open_pos_dicts = [
                            {'symbol': SYMBOL, 'direction': p.signal.direction}
                            for p in self.risk_mgr.open_positions
                        ]
                        corr_result = self.corr_mgr.can_open_position(
                            SYMBOL, signal.direction, open_pos_dicts)
                        if not corr_result['allowed']:
                            continue

                    pos = self.risk_mgr.open_position(signal, idx)
                    if pos:
                        # Store ML features on position for outcome recording at close
                        if ml_feats is not None:
                            pos_ml_feats[id(pos)] = ml_feats
                        # Scale by volatility multiplier
                        total_mult = signal.vol_size_mult
                        mon_mult   = self.monitor.get_size_multiplier(signal.regime)
                        total_mult = total_mult * mon_mult

                        if total_mult < 1.0 and pos.quantity > 0:
                            original_qty   = pos.quantity
                            new_qty        = round(original_qty * total_mult, 6)
                            qty_delta      = original_qty - new_qty
                            if qty_delta > 0:
                                notional_refund = qty_delta * pos.entry_price
                                fee_refund      = notional_refund * self.taker_fee
                                self.risk_mgr.capital += notional_refund + fee_refund
                                pos.fees_paid  = round(pos.fees_paid * (new_qty / original_qty), 8)
                                pos.quantity   = new_qty

                        executed += 1
                        if self.use_db:
                            sid  = signal_id_map.get(signal.timestamp, None)
                            dbid = db_open_position(
                                None, sid, SYMBOL, signal.direction, signal.strategy,
                                signal.regime, pos.entry_price, idx, pos.quantity,
                                pos.fees_paid, signal.stop_loss, signal.take_profit,
                                signal.risk_reward)
                            pos_db_ids[id(pos)] = dbid

        # Force close remaining open positions at end
        if self.risk_mgr.open_positions:
            self.risk_mgr.force_close_all(
                test_df.iloc[-1]['close'], test_df.index[-1])

        if self.use_db:
            for cp in self.risk_mgr.closed_positions:
                pid = pos_db_ids.get(id(cp))
                if pid and not getattr(cp, '_db_closed', False):
                    pnl_pct = cp.pnl / (cp.entry_price * cp.quantity) * 100 \
                              if cp.quantity > 0 else 0
                    db_close_position(pid, cp.exit_price, cp.exit_time,
                                      cp.exit_reason, cp.pnl, pnl_pct, cp.fees_paid)
                    cp._db_closed = True

        print(f"   Executed: {executed} trades")

        # ── Step 7: Results ──
        trade_stats  = self.risk_mgr.get_stats()
        health_report = self.monitor.get_health_report()

        ml_stats = self.ml_filter.get_stats()
        if ml_stats.get('active'):
            print(f"\n[ML FILTER] Active | Trades seen: {ml_stats['trades_in_memory']} | "
                  f"Pass rate: {ml_stats['pass_rate']} | "
                  f"Observed win rate: {ml_stats['observed_win_rate']}")
            fi = self.ml_filter.feature_importance()
            top5 = list(fi.items())[:5]
            print(f"   Top features: {', '.join(f'{k}={v:.3f}' for k,v in top5)}")
        else:
            print(f"\n[ML FILTER] Warming up ({ml_stats['trades_in_memory']}/{50} trades needed)")

        self.results = {
            "data": {
                "symbol": SYMBOL, "timeframe": TIMEFRAME,
                "total_bars": len(df), "test_bars": len(test_df),
                "test_period": f"{test_df.index[0]} → {test_df.index[-1]}",
            },
            "regime_detection": {
                "model": train_stats.get('model', 'RuleBased'),
                "state_map": train_stats.get('state_map', {}),
                "test_distribution": {
                    REGIME_NAMES[r]: int(c) for r, c in regime_counts.items()},
            },
            "trading":    trade_stats,
            "monitor":    health_report,
            "ml_filter":  ml_stats,
            "config": {
                "initial_capital":     INITIAL_CAPITAL,
                "risk_per_trade":      f"{RISK_PER_TRADE*100}%",
                "leverage":            LEVERAGE,
                "max_drawdown_limit":  f"{MAX_DRAWDOWN*100}%",
                "fee_per_trade":       f"{TOTAL_FEE_PER_TRADE*100:.2f}%",
                "fee_multiplier":      FEE_MULTIPLIER,
            }
        }

        self.test_df         = test_df
        self.test_regimes    = test_regimes_report
        self.equity_curve    = self.risk_mgr.equity_curve
        self.closed_positions = self.risk_mgr.closed_positions

        if self.use_db and self.equity_curve:
            equities = [e['equity'] for e in self.equity_curve]
            peak = equities[0]
            for e in self.equity_curve:
                peak = max(peak, e['equity'])
                e['peak_equity']  = peak
                e['drawdown_pct'] = (peak - e['equity']) / peak * 100 if peak > 0 else 0
            save_equity_batch(self.equity_curve)
            save_backtest_run(self.results, self.results['config'])
            db_log("INFO", "backtest", "Backtest completed", self.results['trading'])

        self._print_results()
        return self.results

    def _print_results(self):
        t = self.results.get('trading', {})
        if 'error' in t:
            print(f"[ERROR] {t['error']}"); return

        print(f"\n{'='*60}\n[RESULT] BACKTEST RESULTS\n{'='*60}")
        for k, v in [
            ("Total Trades",  t['total_trades']),
            ("Win Rate",      t['win_rate']),
            ("Profit Factor", t['profit_factor']),
            ("Total PnL",     f"${t['total_pnl']}"),
            ("Fees Paid",     f"${t['total_fees_paid']}"),
            ("Max Drawdown",  t['max_drawdown']),
            ("Final Capital", f"${t['final_capital']}"),
            ("Return",        t['return_pct']),
            ("Sharpe",        t.get('sharpe_ratio', t.get('sharpe_approx', 'N/A'))),
        ]:
            print(f"  {k:<25} {str(v):>15}")

        for name, stats in t.get('strategy_breakdown', {}).items():
            print(f"  {name}: {stats['trades']}T WR={stats['win_rate']} PnL=${stats['pnl']:.2f}")

    def run_walk_forward(self, df: pd.DataFrame, train_pct: float = 0.6,
                          step_pct: float = 0.1) -> list:
        results    = []
        n          = len(df)
        train_size = int(n * train_pct)
        step_size  = int(n * step_pct)
        test_start = train_size

        while test_start + step_size <= n:
            train_df = df.iloc[:test_start]
            test_df  = df.iloc[test_start:test_start + step_size]
            try:
                train_df_features = calculate_features(train_df)
                train_feat        = get_regime_features(train_df_features).dropna()
                self.detector.fit(train_df_features, train_feat)
                result = self.run(test_df, pretrained=True)
                results.append(result)
            except Exception as e:
                print(f"Walk-forward window failed: {e}")
            test_start += step_size

        return results

    def get_trade_log(self) -> pd.DataFrame:
        if not self.closed_positions:
            return pd.DataFrame()
        records = []
        for p in self.closed_positions:
            records.append({
                'entry_time':  p.entry_time,
                'exit_time':   p.exit_time,
                'direction':   p.signal.direction,
                'strategy':    p.signal.strategy,
                'regime':      REGIME_NAMES[p.signal.regime],
                'entry_price': round(p.entry_price, 2),
                'exit_price':  round(p.exit_price, 2),
                'quantity':    p.quantity,
                'pnl':         round(p.pnl, 2),
                'fees':        round(p.fees_paid, 2),
                'exit_reason': p.exit_reason,
            })
        return pd.DataFrame(records)
