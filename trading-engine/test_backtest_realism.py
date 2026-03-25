import os
import sys
import unittest
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest.engine import BacktestEngine
from config import TAKE_PROFIT_MODE
from core.risk_manager import Position, RiskManager


def make_signal(**overrides):
    base = {
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "take_profit_2": 110.0,
        "direction": "LONG",
        "strategy": "TrendFollow",
        "regime": 0,
        "regime_name": "Trending-Up",
        "timeframe": "5m",
        "symbol": "BTCUSDT",
        "risk_reward": 2.0,
        "confidence": 0.8,
        "atr": 2.0,
        "vol_size_mult": 1.0,
        "execution_profile": {},
        "trail_enabled": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class BacktestRealismTests(unittest.TestCase):
    def test_take_profit_mode_defaults_to_single(self):
        self.assertEqual(TAKE_PROFIT_MODE, "single")

    def test_entry_fill_can_simulate_partial_fill(self):
        engine = BacktestEngine(capital=1000, use_db=False)
        signal = make_signal(
            execution_profile={
                "partial_fill_probability": 1.0,
                "partial_fill_min_ratio": 0.5,
                "partial_fill_max_ratio": 0.5,
                "missed_entry_probability": 0.0,
                "max_entry_drift_atr": 1.0,
                "entry_slippage_mult": 0.0,
            }
        )
        bar = pd.Series({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0})
        result = engine._entry_fill_from_bar(signal, bar)

        self.assertEqual(result["status"], "partial_fill")
        self.assertEqual(result["fill_ratio"], 0.5)
        self.assertEqual(result["fill_price"], 100.0)

    def test_profile_leverage_cap_is_applied(self):
        rm = RiskManager(initial_capital=1000, taker_fee=0.0005, maker_fee=0.0002)
        signal = make_signal(
            execution_profile={"entry_fee_rate": 0.0005, "leverage_cap": 8},
        )

        position = rm.open_position(signal, pd.Timestamp("2026-01-01T00:00:00"))

        self.assertIsNotNone(position)
        self.assertEqual(position.leverage_used, 8)

    def test_accounting_tracks_gross_entry_exit_and_funding_fees(self):
        rm = RiskManager(initial_capital=1000, taker_fee=0.0005, maker_fee=0.0002)
        signal = make_signal(
            execution_profile={"entry_fee_rate": 0.0005, "leverage_cap": 10},
        )
        entry_time = pd.Timestamp("2026-01-01T00:00:00")
        position = rm.open_position(signal, entry_time)
        self.assertIsNotNone(position)

        funding_bar = pd.Series({"close": 102.0, "funding_rate": 0.0001})
        rm.apply_funding_costs(funding_bar, bar_hours=8.0)
        rm._close_position(position, 105.0, "Take Profit", pd.Timestamp("2026-01-01T08:00:00"), exit_fee_rate=rm.maker_fee)

        self.assertGreater(position.gross_pnl, 0)
        self.assertGreater(position.entry_fee, 0)
        self.assertGreater(position.exit_fee, 0)
        self.assertNotEqual(position.funding_fee, 0)
        self.assertAlmostEqual(
            position.pnl,
            position.gross_pnl - (position.entry_fee + position.exit_fee + position.funding_fee),
            places=6,
        )

    def test_intrabar_path_respects_first_level_hit(self):
        rm = RiskManager(initial_capital=1000, taker_fee=0.0005, maker_fee=0.0002)
        signal = make_signal(stop_loss=99.0, take_profit=101.0)
        position = Position(
            signal=signal,
            entry_price=100.0,
            quantity=1.0,
            entry_time=pd.Timestamp("2026-01-01T00:00:00"),
            liquidation_price=98.0,
        )
        bar = pd.Series({"open": 100.0, "low": 97.0, "high": 102.0, "close": 102.0})

        event = rm._pick_intrabar_event(position, bar)

        self.assertIsNotNone(event)
        _, reason, _ = event
        self.assertEqual(reason, "Stop Loss")


if __name__ == "__main__":
    unittest.main()
