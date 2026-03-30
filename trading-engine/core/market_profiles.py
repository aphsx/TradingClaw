from __future__ import annotations

from dataclasses import dataclass, asdict
from copy import deepcopy


@dataclass
class ExitProfile:
    profile_family: str = "balanced"
    trend_rr: float = 2.8
    trend_trail_activation_r: float = 1.2
    trend_trail_atr_mult: float = 1.8
    breakout_rr: float = 2.2
    breakout_target_mult: float = 1.15
    breakout_sl_atr_mult: float = 1.6
    meanrev_rr: float = 1.45
    meanrev_stop_atr_mult: float = 1.05
    meanrev_target_buffer_atr: float = 0.15
    pullback_rr: float = 2.4
    session_open_rr: float = 1.9
    rsi_div_rr: float = 2.1
    rsi_div_stop_atr_mult: float = 1.75
    regime_tp_bias_trend: float = 1.10
    regime_tp_bias_range: float = 0.92
    regime_tp_bias_vol: float = 1.20


@dataclass
class ExecutionProfile:
    entry_latency_bars: int = 1
    leverage_cap: int = 20
    fee_sensitivity_bps: float = 7.5
    max_entry_drift_atr: float = 0.35
    missed_entry_probability: float = 0.02
    partial_fill_probability: float = 0.10
    partial_fill_min_ratio: float = 0.45
    partial_fill_max_ratio: float = 0.85
    maker_fill_probability: float = 0.97
    reduce_only_reject_probability: float = 0.01
    entry_fee_rate: float = 0.0
    entry_slippage_mult: float = 0.55
    stop_slippage_mult: float = 1.00
    liquidation_slippage_mult: float = 1.75


@dataclass
class MarketProfile:
    name: str
    exit: ExitProfile
    execution: ExecutionProfile

    def to_signal_payload(self) -> dict:
        return {
            "name": self.name,
            "exit": asdict(self.exit),
            "execution": asdict(self.execution),
        }


_DEFAULT_PROFILE = MarketProfile(
    name="default-5m",
    exit=ExitProfile(profile_family="balanced"),
    execution=ExecutionProfile(),
)

_PROFILE_OVERRIDES = {
    "BTC": {
        "5m": MarketProfile(
            name="btc-5m",
            exit=ExitProfile(
                profile_family="btc-trend-balanced",
                trend_rr=3.0,
                trend_trail_activation_r=1.4,
                trend_trail_atr_mult=2.0,
                breakout_rr=2.35,
                breakout_target_mult=1.20,
                breakout_sl_atr_mult=1.7,
                meanrev_rr=1.35,
                meanrev_stop_atr_mult=0.95,
                meanrev_target_buffer_atr=0.10,
                pullback_rr=2.6,
                session_open_rr=2.0,
                rsi_div_rr=2.2,
                rsi_div_stop_atr_mult=1.65,
            ),
            execution=ExecutionProfile(
                entry_latency_bars=1,
                leverage_cap=20,
                fee_sensitivity_bps=5.0,
                max_entry_drift_atr=0.30,
                missed_entry_probability=0.015,
                partial_fill_probability=0.05,
                partial_fill_min_ratio=0.55,
                partial_fill_max_ratio=0.90,
                maker_fill_probability=0.985,
                reduce_only_reject_probability=0.006,
                entry_fee_rate=0.0005,
                entry_slippage_mult=0.45,
                stop_slippage_mult=0.90,
                liquidation_slippage_mult=1.4,
            ),
        ),
        "15m": MarketProfile(
            name="btc-15m",
            exit=ExitProfile(
                profile_family="btc-swing",
                trend_rr=3.2,
                trend_trail_activation_r=1.6,
                trend_trail_atr_mult=2.2,
                breakout_rr=2.45,
                breakout_target_mult=1.25,
                meanrev_rr=1.55,
                meanrev_stop_atr_mult=1.00,
                pullback_rr=2.8,
                session_open_rr=2.1,
                rsi_div_rr=2.4,
                rsi_div_stop_atr_mult=1.70,
            ),
            execution=ExecutionProfile(
                entry_latency_bars=1,
                leverage_cap=16,
                fee_sensitivity_bps=4.5,
                max_entry_drift_atr=0.40,
                missed_entry_probability=0.012,
                partial_fill_probability=0.04,
                partial_fill_min_ratio=0.60,
                partial_fill_max_ratio=0.92,
                maker_fill_probability=0.988,
                reduce_only_reject_probability=0.005,
                entry_fee_rate=0.0005,
                entry_slippage_mult=0.40,
                stop_slippage_mult=0.85,
                liquidation_slippage_mult=1.35,
            ),
        ),
    },
    "ETH": {
        "5m": MarketProfile(
            name="eth-5m",
            exit=ExitProfile(
                profile_family="eth-balanced",
                trend_rr=2.75,
                trend_trail_activation_r=1.25,
                trend_trail_atr_mult=1.9,
                breakout_rr=2.25,
                breakout_target_mult=1.12,
                breakout_sl_atr_mult=1.7,
                meanrev_rr=1.40,
                meanrev_stop_atr_mult=1.00,
                meanrev_target_buffer_atr=0.12,
                pullback_rr=2.45,
                session_open_rr=1.95,
                rsi_div_rr=2.15,
                rsi_div_stop_atr_mult=1.85,
            ),
            execution=ExecutionProfile(
                entry_latency_bars=1,
                leverage_cap=14,
                fee_sensitivity_bps=6.5,
                max_entry_drift_atr=0.34,
                missed_entry_probability=0.022,
                partial_fill_probability=0.09,
                partial_fill_min_ratio=0.50,
                partial_fill_max_ratio=0.88,
                maker_fill_probability=0.975,
                reduce_only_reject_probability=0.008,
                entry_fee_rate=0.0005,
                entry_slippage_mult=0.55,
                stop_slippage_mult=1.05,
                liquidation_slippage_mult=1.6,
            ),
        ),
    },
    "SOL": {
        "5m": MarketProfile(
            name="sol-5m",
            exit=ExitProfile(
                profile_family="sol-volatility",
                trend_rr=2.55,
                trend_trail_activation_r=1.10,
                trend_trail_atr_mult=1.7,
                breakout_rr=2.05,
                breakout_target_mult=1.08,
                breakout_sl_atr_mult=1.9,
                meanrev_rr=1.30,
                meanrev_stop_atr_mult=1.15,
                meanrev_target_buffer_atr=0.18,
                pullback_rr=2.20,
                session_open_rr=1.80,
                rsi_div_rr=2.00,
                rsi_div_stop_atr_mult=2.05,
                regime_tp_bias_vol=1.30,
            ),
            execution=ExecutionProfile(
                entry_latency_bars=1,
                leverage_cap=12,
                fee_sensitivity_bps=9.0,
                max_entry_drift_atr=0.42,
                missed_entry_probability=0.035,
                partial_fill_probability=0.18,
                partial_fill_min_ratio=0.35,
                partial_fill_max_ratio=0.75,
                maker_fill_probability=0.95,
                reduce_only_reject_probability=0.015,
                entry_fee_rate=0.0005,
                entry_slippage_mult=0.75,
                stop_slippage_mult=1.25,
                liquidation_slippage_mult=1.95,
            ),
        ),
    },
}


def _symbol_key(symbol: str | None) -> str:
    if not symbol:
        return "DEFAULT"
    sym = symbol.upper()
    if "BTC" in sym:
        return "BTC"
    if "ETH" in sym:
        return "ETH"
    if "SOL" in sym:
        return "SOL"
    return "DEFAULT"


def resolve_market_profile(symbol: str | None, timeframe: str | None) -> MarketProfile:
    tf = (timeframe or "5m").lower()
    sym_key = _symbol_key(symbol)

    if sym_key in _PROFILE_OVERRIDES:
        if tf in _PROFILE_OVERRIDES[sym_key]:
            return deepcopy(_PROFILE_OVERRIDES[sym_key][tf])
        if "5m" in _PROFILE_OVERRIDES[sym_key]:
            return deepcopy(_PROFILE_OVERRIDES[sym_key]["5m"])

    profile = deepcopy(_DEFAULT_PROFILE)
    profile.name = f"default-{tf}"
    return profile
