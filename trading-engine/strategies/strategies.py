"""
Trading Strategies - One per Regime
====================================
TRENDING  → EMA Crossover + ATR Trailing Stop
RANGING   → Bollinger Band Mean Reversion + RSI
VOLATILE  → Momentum Burst + Volume Spike
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *


@dataclass
class Signal:
    """Trade signal output."""
    timestamp: pd.Timestamp
    direction: str        # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    atr: float
    regime: int
    strategy: str
    confidence: float
    expected_profit_pct: float
    
    @property
    def risk_reward(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return reward / risk if risk > 0 else 0


class TrendStrategy:
    """
    EMA Crossover + ATR Trailing Stop + Multi-Timeframe
    ─────────────────────────────────────────────────────
    LONG:  EMA 9 crosses above EMA 21, price > EMA 50, 4h trend confirms
    SHORT: EMA 9 crosses below EMA 21, price < EMA 50, 4h trend confirms
    SL: ATR * 1.5 from entry
    TP: ATR * 3.0 from entry
    """
    name = "Trend_EMA_Cross"

    @staticmethod
    def generate_signals(df: pd.DataFrame, df_4h: pd.DataFrame = None) -> list:
        signals = []

        # EMA crossover detection
        ema_fast = df['ema_9']
        ema_slow = df['ema_21']
        ema_trend = df['ema_50']

        cross_up = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
        cross_down = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

        for idx in df.index:
            atr = df.loc[idx, 'atr_14']
            close = df.loc[idx, 'close']

            if pd.isna(atr) or atr <= 0:
                continue

            # Check 4h confirmation if available
            has_4h_long_confirm = True
            has_4h_short_confirm = True
            if df_4h is not None and not df_4h.empty:
                # Find nearest 4h candle before or at this time
                nearest_4h = df_4h[df_4h.index <= idx]
                if not nearest_4h.empty:
                    idx_4h = nearest_4h.index[-1]
                    ema_fast_4h = nearest_4h.loc[idx_4h, 'ema_9'] if 'ema_9' in nearest_4h.columns else None
                    ema_slow_4h = nearest_4h.loc[idx_4h, 'ema_21'] if 'ema_21' in nearest_4h.columns else None
                    if ema_fast_4h is not None and ema_slow_4h is not None:
                        has_4h_long_confirm = ema_fast_4h > ema_slow_4h
                        has_4h_short_confirm = ema_fast_4h < ema_slow_4h

            # Check pullback: price should be close to EMA (within 0.5%)
            pullback_threshold = ema_slow.get(idx, close) * 0.005
            price_above_ema = close - ema_slow.get(idx, close)
            is_pullback = abs(price_above_ema) < pullback_threshold

            # LONG signal
            if cross_up.get(idx, False) and close > ema_trend.get(idx, 0) and has_4h_long_confirm and is_pullback:
                sl = close - atr * TREND_ATR_SL_MULT
                tp = close + atr * TREND_ATR_TP_MULT
                expected_profit = (tp - close) / close * 100
                ema_spread = (ema_fast.get(idx, 0) - ema_slow.get(idx, 0)) / close * 100
                confidence = min((df.loc[idx, 'adx'] - 20) / 30, 1.0) * (1.0 if ema_spread > 0.002 else 0.5) if 'adx' in df.columns else 0.5

                signals.append(Signal(
                    timestamp=idx,
                    direction="LONG",
                    entry_price=close,
                    stop_loss=sl,
                    take_profit=tp,
                    atr=atr,
                    regime=0,
                    strategy="Trend_EMA_Cross",
                    confidence=confidence,
                    expected_profit_pct=expected_profit
                ))

            # SHORT signal
            elif cross_down.get(idx, False) and close < ema_trend.get(idx, float('inf')) and has_4h_short_confirm and is_pullback:
                sl = close + atr * TREND_ATR_SL_MULT
                tp = close - atr * TREND_ATR_TP_MULT
                expected_profit = (close - tp) / close * 100
                ema_spread = (ema_slow.get(idx, 0) - ema_fast.get(idx, 0)) / close * 100
                confidence = min((df.loc[idx, 'adx'] - 20) / 30, 1.0) * (1.0 if ema_spread > 0.002 else 0.5) if 'adx' in df.columns else 0.5

                signals.append(Signal(
                    timestamp=idx,
                    direction="SHORT",
                    entry_price=close,
                    stop_loss=sl,
                    take_profit=tp,
                    atr=atr,
                    regime=0,
                    strategy="Trend_EMA_Cross",
                    confidence=confidence,
                    expected_profit_pct=expected_profit
                ))

        return signals


class RangeStrategy:
    """
    Bollinger Band Mean Reversion + RSI + 4h Confirmation
    ──────────────────────────────────────────────────────
    LONG:  Price touches lower BB + RSI < 30, 4h not strong trending
    SHORT: Price touches upper BB + RSI > 70, 4h not strong trending
    SL: ATR * 1.0 from entry
    TP: BB middle band
    """
    name = "Range_BB_RSI"

    @staticmethod
    def generate_signals(df: pd.DataFrame, df_4h: pd.DataFrame = None) -> list:
        signals = []

        for idx in df.index:
            close = df.loc[idx, 'close']
            atr = df.loc[idx, 'atr_14']
            rsi = df.loc[idx, 'rsi_14']
            bb_lower = df.loc[idx, 'bb_lower']
            bb_upper = df.loc[idx, 'bb_upper']
            bb_mid = df.loc[idx, 'bb_mid']

            if any(pd.isna([atr, rsi, bb_lower, bb_upper, bb_mid])) or atr <= 0:
                continue

            # Check 4h - only trade range if 4h is NOT strongly trending
            allow_range = True
            if df_4h is not None and not df_4h.empty:
                nearest_4h = df_4h[df_4h.index <= idx]
                if not nearest_4h.empty:
                    idx_4h = nearest_4h.index[-1]
                    adx_4h = nearest_4h.loc[idx_4h, 'adx'] if 'adx' in nearest_4h.columns else 0
                    # Only trade range if 4h ADX < 30 (not strong trend)
                    allow_range = adx_4h < 30

            # LONG: Price at lower BB + RSI oversold
            if allow_range and close <= bb_lower and rsi < RANGE_RSI_OVERSOLD:
                sl = close - atr * RANGE_ATR_SL_MULT
                tp = bb_mid  # Target = middle band
                expected_profit = (tp - close) / close * 100
                bb_deviation = (close - bb_mid) / (bb_upper - bb_mid) if (bb_upper - bb_mid) != 0 else 0
                confidence = min(abs(bb_deviation) / 2, 1.0)

                signals.append(Signal(
                    timestamp=idx,
                    direction="LONG",
                    entry_price=close,
                    stop_loss=sl,
                    take_profit=tp,
                    atr=atr,
                    regime=1,
                    strategy="Range_BB_RSI",
                    confidence=confidence,
                    expected_profit_pct=expected_profit
                ))

            # SHORT: Price at upper BB + RSI overbought
            elif allow_range and close >= bb_upper and rsi > RANGE_RSI_OVERBOUGHT:
                sl = close + atr * RANGE_ATR_SL_MULT
                tp = bb_mid
                expected_profit = (close - tp) / close * 100
                bb_deviation = (close - bb_mid) / (bb_upper - bb_mid) if (bb_upper - bb_mid) != 0 else 0
                confidence = min(abs(bb_deviation) / 2, 1.0)

                signals.append(Signal(
                    timestamp=idx,
                    direction="SHORT",
                    entry_price=close,
                    stop_loss=sl,
                    take_profit=tp,
                    atr=atr,
                    regime=1,
                    strategy="Range_BB_RSI",
                    confidence=confidence,
                    expected_profit_pct=expected_profit
                ))

        return signals


class VolatileStrategy:
    """
    Momentum Burst + Volume Spike
    ──────────────────────────────
    LONG:  Big green candle + volume > 2x MA + momentum positive
    SHORT: Big red candle + volume > 2x MA + momentum negative
    SL: ATR * 2.0 (wider for volatile)
    TP: ATR * 4.0 (big targets)
    """
    name = "Volatile_Momentum"
    
    @staticmethod
    def generate_signals(df: pd.DataFrame) -> list:
        signals = []
        
        for idx in df.index:
            close = df.loc[idx, 'close']
            open_price = df.loc[idx, 'open']
            atr = df.loc[idx, 'atr_14']
            vol_ratio = df.loc[idx, 'volume_ratio']
            momentum = df.loc[idx, 'momentum_10']
            
            if any(pd.isna([atr, vol_ratio, momentum])) or atr <= 0:
                continue
            
            candle_size = abs(close - open_price) / close * 100
            is_volume_spike = vol_ratio > VOL_VOLUME_SPIKE
            is_big_candle = candle_size > (atr / close * 100) * 0.5
            
            # LONG: Bullish momentum burst (needs vol_ratio > 1.5 to be meaningful)
            if (close > open_price and is_volume_spike and is_big_candle
                and momentum > 0 and vol_ratio > 1.5):
                sl = close - atr * VOL_ATR_SL_MULT
                tp = close + atr * VOL_ATR_TP_MULT
                expected_profit = (tp - close) / close * 100
                confidence = min((vol_ratio - 1.5) / 2.5, 1.0)

                signals.append(Signal(
                    timestamp=idx,
                    direction="LONG",
                    entry_price=close,
                    stop_loss=sl,
                    take_profit=tp,
                    atr=atr,
                    regime=2,
                    strategy="Volatile_Momentum",
                    confidence=confidence,
                    expected_profit_pct=expected_profit
                ))

            # SHORT: Bearish momentum burst (needs vol_ratio > 1.5 to be meaningful)
            elif (close < open_price and is_volume_spike and is_big_candle
                  and momentum < 0 and vol_ratio > 1.5):
                sl = close + atr * VOL_ATR_SL_MULT
                tp = close - atr * VOL_ATR_TP_MULT
                expected_profit = (close - tp) / close * 100
                confidence = min((vol_ratio - 1.5) / 2.5, 1.0)

                signals.append(Signal(
                    timestamp=idx,
                    direction="SHORT",
                    entry_price=close,
                    stop_loss=sl,
                    take_profit=tp,
                    atr=atr,
                    regime=2,
                    strategy="Volatile_Momentum",
                    confidence=confidence,
                    expected_profit_pct=expected_profit
                ))
        
        return signals


# Strategy registry
STRATEGY_MAP = {
    0: TrendStrategy,    # TRENDING
    1: RangeStrategy,    # RANGING  
    2: VolatileStrategy, # VOLATILE
}


def check_exit_signals(position: dict, current_price: float, df: pd.DataFrame = None) -> dict:
    """Check if any exit signal is triggered for an open position."""
    result = {'exit': False, 'reason': None}

    # Extract position details
    entry = float(position.get('entry_fill_price') or position.get('entry_price', 0))
    sl = float(position.get('stop_loss', 0))
    tp = float(position.get('take_profit', 0))
    direction = position.get('direction', 'LONG')

    if direction == 'LONG':
        if sl > 0 and current_price <= sl:
            result = {'exit': True, 'reason': 'Stop Loss'}
        elif tp > 0 and current_price >= tp:
            result = {'exit': True, 'reason': 'Take Profit'}
    else:  # SHORT
        if sl > 0 and current_price >= sl:
            result = {'exit': True, 'reason': 'Stop Loss'}
        elif tp > 0 and current_price <= tp:
            result = {'exit': True, 'reason': 'Take Profit'}

    return result


def generate_all_signals(df: pd.DataFrame, regimes: pd.Series, df_4h: pd.DataFrame = None) -> list:
    """
    Generate signals using the appropriate strategy per regime.
    Only generates signals when the regime matches the strategy.
    Includes multi-timeframe confirmation if df_4h is provided.
    """
    all_signals = []

    for regime_id, strategy_class in STRATEGY_MAP.items():
        # Filter data to only this regime's periods
        regime_mask = regimes == regime_id
        regime_data = df[regime_mask]

        if len(regime_data) < 20:
            continue

        # Pass 4h data if available
        if df_4h is not None and not df_4h.empty:
            signals = strategy_class.generate_signals(regime_data, df_4h)
        else:
            signals = strategy_class.generate_signals(regime_data)
        all_signals.extend(signals)

    # Sort by timestamp
    all_signals.sort(key=lambda s: s.timestamp)

    return all_signals
