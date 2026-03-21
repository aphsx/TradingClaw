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
    EMA Crossover + ATR Trailing Stop
    ──────────────────────────────────
    LONG:  EMA 9 crosses above EMA 21, price > EMA 50
    SHORT: EMA 9 crosses below EMA 21, price < EMA 50
    SL: ATR * 1.5 from entry
    TP: ATR * 3.0 from entry
    """
    name = "Trend_EMA_Cross"
    
    @staticmethod
    def generate_signals(df: pd.DataFrame) -> list:
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
            
            # LONG signal
            if cross_up.get(idx, False) and close > ema_trend.get(idx, 0):
                sl = close - atr * TREND_ATR_SL_MULT
                tp = close + atr * TREND_ATR_TP_MULT
                expected_profit = (tp - close) / close * 100
                
                signals.append(Signal(
                    timestamp=idx,
                    direction="LONG",
                    entry_price=close,
                    stop_loss=sl,
                    take_profit=tp,
                    atr=atr,
                    regime=0,
                    strategy="Trend_EMA_Cross",
                    confidence=min(df.loc[idx, 'adx'] / 50, 1.0) if 'adx' in df.columns else 0.5,
                    expected_profit_pct=expected_profit
                ))
            
            # SHORT signal
            elif cross_down.get(idx, False) and close < ema_trend.get(idx, float('inf')):
                sl = close + atr * TREND_ATR_SL_MULT
                tp = close - atr * TREND_ATR_TP_MULT
                expected_profit = (close - tp) / close * 100
                
                signals.append(Signal(
                    timestamp=idx,
                    direction="SHORT",
                    entry_price=close,
                    stop_loss=sl,
                    take_profit=tp,
                    atr=atr,
                    regime=0,
                    strategy="Trend_EMA_Cross",
                    confidence=min(df.loc[idx, 'adx'] / 50, 1.0) if 'adx' in df.columns else 0.5,
                    expected_profit_pct=expected_profit
                ))
        
        return signals


class RangeStrategy:
    """
    Bollinger Band Mean Reversion + RSI
    ────────────────────────────────────
    LONG:  Price touches lower BB + RSI < 30
    SHORT: Price touches upper BB + RSI > 70
    SL: ATR * 1.0 from entry
    TP: BB middle band
    """
    name = "Range_BB_RSI"
    
    @staticmethod
    def generate_signals(df: pd.DataFrame) -> list:
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
            
            # LONG: Price at lower BB + RSI oversold
            if close <= bb_lower and rsi < RANGE_RSI_OVERSOLD:
                sl = close - atr * RANGE_ATR_SL_MULT
                tp = bb_mid  # Target = middle band
                expected_profit = (tp - close) / close * 100
                
                signals.append(Signal(
                    timestamp=idx,
                    direction="LONG",
                    entry_price=close,
                    stop_loss=sl,
                    take_profit=tp,
                    atr=atr,
                    regime=1,
                    strategy="Range_BB_RSI",
                    confidence=min((RANGE_RSI_OVERSOLD - rsi) / 30, 1.0),
                    expected_profit_pct=expected_profit
                ))
            
            # SHORT: Price at upper BB + RSI overbought
            elif close >= bb_upper and rsi > RANGE_RSI_OVERBOUGHT:
                sl = close + atr * RANGE_ATR_SL_MULT
                tp = bb_mid
                expected_profit = (close - tp) / close * 100
                
                signals.append(Signal(
                    timestamp=idx,
                    direction="SHORT",
                    entry_price=close,
                    stop_loss=sl,
                    take_profit=tp,
                    atr=atr,
                    regime=1,
                    strategy="Range_BB_RSI",
                    confidence=min((rsi - RANGE_RSI_OVERBOUGHT) / 30, 1.0),
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
            
            # LONG: Bullish momentum burst
            if (close > open_price and is_volume_spike and is_big_candle 
                and momentum > 0):
                sl = close - atr * VOL_ATR_SL_MULT
                tp = close + atr * VOL_ATR_TP_MULT
                expected_profit = (tp - close) / close * 100
                
                signals.append(Signal(
                    timestamp=idx,
                    direction="LONG",
                    entry_price=close,
                    stop_loss=sl,
                    take_profit=tp,
                    atr=atr,
                    regime=2,
                    strategy="Volatile_Momentum",
                    confidence=min(vol_ratio / 4, 1.0),
                    expected_profit_pct=expected_profit
                ))
            
            # SHORT: Bearish momentum burst
            elif (close < open_price and is_volume_spike and is_big_candle 
                  and momentum < 0):
                sl = close + atr * VOL_ATR_SL_MULT
                tp = close - atr * VOL_ATR_TP_MULT
                expected_profit = (close - tp) / close * 100
                
                signals.append(Signal(
                    timestamp=idx,
                    direction="SHORT",
                    entry_price=close,
                    stop_loss=sl,
                    take_profit=tp,
                    atr=atr,
                    regime=2,
                    strategy="Volatile_Momentum",
                    confidence=min(vol_ratio / 4, 1.0),
                    expected_profit_pct=expected_profit
                ))
        
        return signals


# Strategy registry
STRATEGY_MAP = {
    0: TrendStrategy,    # TRENDING
    1: RangeStrategy,    # RANGING  
    2: VolatileStrategy, # VOLATILE
}


def generate_all_signals(df: pd.DataFrame, regimes: pd.Series) -> list:
    """
    Generate signals using the appropriate strategy per regime.
    Only generates signals when the regime matches the strategy.
    """
    all_signals = []
    
    for regime_id, strategy_class in STRATEGY_MAP.items():
        # Filter data to only this regime's periods
        regime_mask = regimes == regime_id
        regime_data = df[regime_mask]
        
        if len(regime_data) < 20:
            continue
        
        signals = strategy_class.generate_signals(regime_data)
        all_signals.extend(signals)
    
    # Sort by timestamp
    all_signals.sort(key=lambda s: s.timestamp)
    
    return all_signals
