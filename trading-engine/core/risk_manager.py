"""
Fee-Aware Filter + Risk Management
====================================
Ensures every trade has positive expected value after fees.
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional
from collections import deque
from datetime import datetime, timezone

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from config import (LEVERAGE, MAX_MARGIN_RATIO, EMERGENCY_MARGIN_RATIO, LIQUIDATION_SAFETY_PCT,
                    MAX_PORTFOLIO_HEAT, DRAWDOWN_SCALE_LEVELS, DRAWDOWN_SIZE_FACTORS,
                    CAPITAL_TIERS)


def get_risk_tier(capital: float) -> dict:
    """
    Return risk settings based on account size.
    Smaller accounts get a higher risk% so trades remain meaningful in dollar terms.
    """
    for max_cap, risk_pct, min_notional, label in CAPITAL_TIERS:
        if capital <= max_cap:
            return {"risk_pct": risk_pct, "min_notional": min_notional, "label": label}
    # Fallback (should never reach here due to float('inf') tier)
    return {"risk_pct": 0.01, "min_notional": 10.0, "label": "Large $2k+"}


class FeeFilter:
    """
    Filters trades where expected profit doesn't justify the fees.
    
    Rule: expected_profit >= total_fee * FEE_MULTIPLIER
    """
    
    def __init__(self, maker_fee=None, taker_fee=None, 
                 slippage=SLIPPAGE, multiplier=FEE_MULTIPLIER):
        mf = maker_fee if maker_fee is not None else MAKER_FEE
        tf = taker_fee if taker_fee is not None else TAKER_FEE
        self.total_fee = (tf * 2) + slippage  # Entry + Exit + Slippage
        self.multiplier = multiplier
    
    def filter_signals(self, signals: list) -> tuple:
        """
        Filter signals by fee viability.
        Returns: (passed_signals, rejected_signals)
        """
        passed = []
        rejected = []
        
        for signal in signals:
            min_profit_pct = self.total_fee * self.multiplier * 100
            
            if signal.expected_profit_pct >= min_profit_pct:
                passed.append(signal)
            else:
                rejected.append(signal)
        
        return passed, rejected
    
    def get_stats(self, signals: list, passed: list, rejected: list) -> dict:
        return {
            "total_signals": len(signals),
            "passed": len(passed),
            "rejected": len(rejected),
            "pass_rate": f"{len(passed)/max(len(signals),1)*100:.1f}%",
            "min_profit_threshold": f"{self.total_fee * self.multiplier * 100:.3f}%",
            "total_fee_per_trade": f"{self.total_fee * 100:.3f}%"
        }


@dataclass
class Position:
    """Active position tracker."""
    signal: object
    entry_price: float
    quantity: float
    entry_time: pd.Timestamp
    pnl: float = 0.0
    exit_price: float = 0.0
    exit_time: Optional[pd.Timestamp] = None
    exit_reason: str = ""
    is_open: bool = True
    fees_paid: float = 0.0


class RiskManager:
    """
    Position sizing and risk control.
    - Kelly-inspired position sizing based on win rate and RR
    - Max drawdown circuit breaker
    - Daily loss limit
    """
    
    def __init__(self, initial_capital=INITIAL_CAPITAL,
                 risk_per_trade=RISK_PER_TRADE,
                 max_daily_loss=MAX_DAILY_LOSS,
                 max_drawdown=MAX_DRAWDOWN,
                 max_open_trades=MAX_OPEN_TRADES,
                 taker_fee=None):

        self.taker_fee = taker_fee if taker_fee is not None else TAKER_FEE

        # Use provided capital; 0 means "not yet synced from exchange"
        start_capital = initial_capital if initial_capital > 0 else 1000.0
        self.initial_capital = start_capital
        self.capital = start_capital
        self.peak_capital = start_capital
        self.risk_per_trade = risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_drawdown = max_drawdown
        self.max_open_trades = max_open_trades

        self.open_positions: List[Position] = []
        self.closed_positions: List[Position] = []
        self.daily_pnl = 0.0
        self.current_date = None
        self.is_circuit_broken = False
        self.equity_curve = []

        # Track trade results for Kelly sizing
        self.trade_results = deque(maxlen=100)
        self._current_heat = 0.0  # Portfolio heat tracking

        # Dynamic tier — recalculated whenever capital is synced
        tier = get_risk_tier(start_capital)
        self._risk_pct: float = tier["risk_pct"]
        self._min_notional: float = tier["min_notional"]
        self._tier_label: str = tier["label"]
        self._capital_synced: bool = (initial_capital > 0)

    def sync_capital(self, live_balance: float) -> str:
        """
        Sync capital with the real Binance balance and recalculate risk tier.
        Called at startup and periodically during live trading.

        Returns a human-readable summary string for logging.
        """
        if live_balance <= 0:
            return f"[WARN]  sync_capital: invalid balance {live_balance} — keeping ${self.capital:.2f}"

        old_capital = self.capital
        self.capital = live_balance

        # Only set initial/peak on first real sync
        if not self._capital_synced:
            self.initial_capital = live_balance
            self.peak_capital = live_balance
            self._capital_synced = True
        else:
            # Keep peak tracking correct
            self.peak_capital = max(self.peak_capital, live_balance)

        # Recalculate tier based on new capital
        tier = get_risk_tier(live_balance)
        self._risk_pct = tier["risk_pct"]
        self._min_notional = tier["min_notional"]
        self._tier_label = tier["label"]

        return (
            f"[BALANCE] Capital synced: ${old_capital:.2f} → ${live_balance:.2f} | "
            f"Tier: {self._tier_label} | "
            f"Risk/trade: {self._risk_pct*100:.1f}% | "
            f"Min notional: ${self._min_notional:.1f}"
        )

    def get_tier_info(self) -> dict:
        """Return current tier settings for display/logging."""
        return {
            "capital": round(self.capital, 2),
            "tier": self._tier_label,
            "risk_pct": f"{self._risk_pct*100:.1f}%",
            "min_notional_usd": self._min_notional,
            "risk_amount_usd": round(self.capital * self._risk_pct, 2),
        }

    def reset(self):
        """Reset for new backtest."""
        self.capital = self.initial_capital
        self.peak_capital = self.initial_capital
        self.open_positions = []
        self.closed_positions = []
        self.daily_pnl = 0.0
        self.current_date = None
        self.is_circuit_broken = False
        self.equity_curve = []
        self.trade_results = deque(maxlen=100)
        self._current_heat = 0.0

    def _calculate_kelly_size(self) -> float:
        """Calculate Kelly fraction based on recent trade history.

        Uses self._risk_pct (tier-adjusted) instead of the static RISK_PER_TRADE.
        Returns the fraction of capital to risk per trade (margin side),
        already divided by LEVERAGE so actual notional exposure stays controlled.
        Cap at _risk_pct / 2 so Kelly can be adaptive above the fixed floor.
        """
        risk_pct = self._risk_pct  # tier-aware
        kelly_cap = risk_pct / 2

        if len(self.trade_results) < MIN_WIN_RATE_SAMPLE:
            return risk_pct / LEVERAGE
        recent = list(self.trade_results)[-MIN_WIN_RATE_SAMPLE:]
        wins   = [t for t in recent if t > 0]
        losses = [t for t in recent if t <= 0]
        if not wins or not losses:
            return risk_pct / LEVERAGE
        win_rate = len(wins) / len(recent)
        avg_win  = sum(wins) / len(wins)
        avg_loss = abs(sum(losses) / len(losses))
        if avg_loss == 0:
            return risk_pct / LEVERAGE
        b = avg_win / avg_loss
        kelly = (b * win_rate - (1 - win_rate)) / b
        kelly = max(0, kelly) * KELLY_FRACTION
        return min(kelly, kelly_cap) / LEVERAGE

    def _get_vol_adjustment(self, current_atr_pct: float, avg_atr_pct: float) -> float:
        """Scale position size based on current vs average volatility.
        
        Returns a multiplicative factor applied *on top of* Kelly sizing.
        ATR-based SL already shrinks size in high vol; this adds a smaller
        extra nudge rather than a hard 50% cut to avoid double-penalising.
        """
        if avg_atr_pct == 0:
            return 1.0
        vol_ratio = current_atr_pct / avg_atr_pct
        if vol_ratio > VOLATILITY_SCALE_HIGH:
            # Multiplicative reduction: e.g. 2x vol → 0.75x size (not 0.5x)
            return max(0.5, 1.0 / vol_ratio)
        elif vol_ratio < VOLATILITY_SCALE_LOW:
            return min(1.5, 1.0 / vol_ratio)  # Low vol: scale up, capped at 1.5x
        return 1.0

    def calculate_position_size(self, signal, current_atr_pct: float = None, avg_atr_pct: float = None) -> float:
        """
        Calculate position size based on adaptive Kelly sizing + volatility adjustment.

        Kelly size is already expressed as a fraction of margin capital (÷ LEVERAGE),
        so risk_amount is the margin committed, and actual notional = risk_amount × LEVERAGE.
        Position size = risk_amount / risk_per_unit  (standard ATR/SL-based sizing).
        """
        if self.is_circuit_broken:
            return 0.0

        # kelly_size is already in margin terms (divided by LEVERAGE in _calculate_kelly_size)
        kelly_size = self._calculate_kelly_size()

        risk_amount = self.capital * kelly_size
        risk_per_unit = abs(signal.entry_price - signal.stop_loss)

        if risk_per_unit <= 0:
            return 0.0

        position_size = risk_amount / risk_per_unit

        # Apply multiplicative volatility adjustment if ATR data is provided
        if current_atr_pct is not None and avg_atr_pct is not None:
            vol_adj = self._get_vol_adjustment(current_atr_pct, avg_atr_pct)
            position_size *= vol_adj

        # ── Max notional cap: total notional across all positions ≤ capital × LEVERAGE ──
        # This prevents 5x leverage × 3 trades = 15x effective exposure
        current_open_notional = sum(
            p.entry_price * p.quantity for p in self.open_positions
        )
        max_total_notional = self.capital * LEVERAGE
        remaining_notional = max_total_notional - current_open_notional
        if remaining_notional <= 0:
            return 0.0
        max_size_by_notional = remaining_notional / signal.entry_price

        # Also cap per-trade at 50% of capital margin (not 50% of leveraged notional)
        max_margin_per_trade = self.capital * 0.5
        max_size_by_margin = (max_margin_per_trade * LEVERAGE) / signal.entry_price

        position_size = min(position_size, max_size_by_notional, max_size_by_margin)

        # Enforce minimum notional floor — bump size UP instead of rejecting
        # e.g. $6 minimum: even a $30 account will attempt at least a $6 order
        if position_size * signal.entry_price < self._min_notional:
            position_size = self._min_notional / signal.entry_price

        return round(position_size, 6)
    
    def _get_total_equity(self, current_price: float = None) -> float:
        """Get total equity = free capital + open position value."""
        equity = self.capital
        for pos in self.open_positions:
            notional = pos.entry_price * pos.quantity
            if current_price:
                if pos.signal.direction == "LONG":
                    unrealized = (current_price - pos.entry_price) * pos.quantity
                else:
                    unrealized = (pos.entry_price - current_price) * pos.quantity
                equity += notional + unrealized
            else:
                equity += notional  # At cost
        return equity

    def can_open_trade(self, signal, current_time: pd.Timestamp, current_price: float = None) -> tuple:
        """Check if we can open a new trade. Returns (can_trade, reason)."""
        # Reset daily PnL on new day
        current_date = current_time.date() if hasattr(current_time, 'date') else current_time
        if current_date != self.current_date:
            self.daily_pnl = 0.0
            self.current_date = current_date
            self.is_circuit_broken = False
        
        # Check circuit breaker
        if self.is_circuit_broken:
            return False, "Circuit breaker active"
        
        # Check max open trades
        if len(self.open_positions) >= self.max_open_trades:
            return False, f"Max {self.max_open_trades} open trades reached"
        
        # Check max drawdown using total equity
        total_equity = self._get_total_equity(current_price or signal.entry_price)
        drawdown = (self.peak_capital - total_equity) / self.peak_capital
        if drawdown >= self.max_drawdown:
            self.is_circuit_broken = True
            return False, f"Max drawdown {self.max_drawdown*100}% reached"
        
        # Check daily loss limit
        if abs(self.daily_pnl) >= self.capital * self.max_daily_loss:
            self.is_circuit_broken = True
            return False, f"Daily loss limit {self.max_daily_loss*100}% reached"
        
        # Check capital
        position_size = self.calculate_position_size(signal)
        if position_size <= 0:
            return False, "Insufficient capital for position"
        
        return True, "OK"
    
    def open_position(self, signal, current_time: pd.Timestamp) -> Optional[Position]:
        """Open a new position."""
        can_trade, reason = self.can_open_trade(signal, current_time, signal.entry_price)
        if not can_trade:
            return None
        
        quantity = self.calculate_position_size(signal)
        notional = signal.entry_price * quantity
        entry_fee = notional * self.taker_fee
        
        # Check if we have enough capital for notional + fee
        if notional + entry_fee > self.capital:
            quantity = (self.capital * 0.95) / (signal.entry_price * (1 + self.taker_fee))
            quantity = round(quantity, 6)
            notional = signal.entry_price * quantity
            entry_fee = notional * self.taker_fee
            # Hard reject only if balance itself is too small to cover even min notional
            if notional < self._min_notional:
                return None
        
        position = Position(
            signal=signal,
            entry_price=signal.entry_price,
            quantity=quantity,
            entry_time=current_time,
            fees_paid=entry_fee
        )
        
        self.open_positions.append(position)
        self.capital -= (notional + entry_fee)  # Lock capital for position
        
        return position
    
    def check_exits(self, current_bar: pd.Series, current_time: pd.Timestamp):
        """Check all open positions for exit conditions.
        
        Exit prices include SLIPPAGE in the adverse direction to simulate
        realistic fills (SL fills worse, TP fills worse).
        """
        positions_to_close = []

        for pos in self.open_positions:
            high = current_bar['high']
            low = current_bar['low']
            close = current_bar['close']
            signal = pos.signal

            exit_price = None
            exit_reason = ""

            if signal.direction == "LONG":
                # Check stop loss
                if low <= signal.stop_loss:
                    # SL: fill below stop (adverse slip)
                    exit_price = signal.stop_loss * (1 - SLIPPAGE)
                    exit_reason = "Stop Loss"
                # Check take profit
                elif high >= signal.take_profit:
                    # TP: fill below TP (adverse slip)
                    exit_price = signal.take_profit * (1 - SLIPPAGE)
                    exit_reason = "Take Profit"

            elif signal.direction == "SHORT":
                # Check stop loss
                if high >= signal.stop_loss:
                    # SL: fill above stop (adverse slip)
                    exit_price = signal.stop_loss * (1 + SLIPPAGE)
                    exit_reason = "Stop Loss"
                # Check take profit
                elif low <= signal.take_profit:
                    # TP: fill above TP (adverse slip)
                    exit_price = signal.take_profit * (1 + SLIPPAGE)
                    exit_reason = "Take Profit"

            if exit_price is not None:
                positions_to_close.append((pos, exit_price, exit_reason, current_time))

        for pos, exit_price, exit_reason, exit_time in positions_to_close:
            self._close_position(pos, exit_price, exit_reason, exit_time)
    
    def _close_position(self, position: Position, exit_price: float,
                        reason: str, exit_time: pd.Timestamp):
        """Close a position and update capital."""
        position.exit_price = exit_price
        position.exit_reason = reason
        position.exit_time = exit_time
        position.is_open = False

        # Calculate PnL
        if position.signal.direction == "LONG":
            pnl = (exit_price - position.entry_price) * position.quantity
        else:
            pnl = (position.entry_price - exit_price) * position.quantity

        # Exit fee
        exit_notional = exit_price * position.quantity
        exit_fee = exit_notional * self.taker_fee
        position.fees_paid += exit_fee

        # Net PnL after all fees
        position.pnl = pnl - position.fees_paid

        # Track trade result for Kelly sizing (as a percentage return)
        position_cost = position.entry_price * position.quantity
        if position_cost > 0:
            pnl_return = position.pnl / position_cost
            self.trade_results.append(pnl_return)

        # Return capital: original notional + PnL - exit fee
        entry_notional = position.entry_price * position.quantity
        self.capital += entry_notional + pnl - exit_fee
        self.daily_pnl += position.pnl
        # peak_capital tracked in record_equity()

        # Move to closed
        self.open_positions.remove(position)
        self.closed_positions.append(position)
    
    def update_trailing_stop(self, position: dict, current_price: float) -> float:
        """Return new stop loss price if trailing stop should move."""
        entry = float(position.get('entry_fill_price') or position.get('entry_price', 0))
        current_sl = float(position.get('stop_loss', 0))
        direction = position.get('direction', 'LONG')
        qty = float(position.get('quantity', 0))

        if direction == 'LONG':
            profit_pct = (current_price - entry) / entry
            if profit_pct < TRAILING_STOP_ACTIVATION:
                return current_sl  # Not activated yet
            new_sl = current_price * (1 - TRAILING_STOP_DISTANCE)
            return max(new_sl, current_sl)  # Only move up
        else:  # SHORT
            profit_pct = (entry - current_price) / entry
            if profit_pct < TRAILING_STOP_ACTIVATION:
                return current_sl
            new_sl = current_price * (1 + TRAILING_STOP_DISTANCE)
            return min(new_sl, current_sl)  # Only move down

    def update_trailing_tp(self, position: dict, current_price: float) -> float:
        """Return new take profit price if trailing TP should move (issue #7)."""
        entry = float(position.get('entry_fill_price') or position.get('entry_price', 0))
        current_tp = float(position.get('take_profit', 0))
        direction = position.get('direction', 'LONG')

        if direction == 'LONG':
            profit_pct = (current_price - entry) / entry
            if profit_pct > 0.02:  # >2% profit
                new_tp = current_price * 0.985  # Trail 1.5% behind
                return max(new_tp, current_tp)  # Only move up
        else:  # SHORT
            profit_pct = (entry - current_price) / entry
            if profit_pct > 0.02:
                new_tp = current_price * 1.015  # Trail 1.5% above
                return min(new_tp, current_tp)  # Only move down
        
        return current_tp

    def should_time_exit(self, position: dict) -> bool:
        """Return True if position has been open too long and funding costs bleed out (issue #2)."""
        entry_time_str = position.get('entry_time')
        if not entry_time_str:
            return False
        try:
            if isinstance(entry_time_str, str):
                entry_time = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
            else:
                entry_time = entry_time_str
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)
            
            age_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
            unrealized = float(position.get('unrealized_pnl', 0))
            
            entry_val = float(position.get('quantity', 0)) * float(position.get('entry_fill_price') or position.get('entry_price', 0))
            est_funding_per_8h = entry_val * MAX_FUNDING_RATE  # ~0.1% max default config
            cumulative_funding = est_funding_per_8h * (age_hours / 8)
            
            # Exit if age > 4h AND unrealized < -2x cumulative funding cost
            if age_hours > 4 and unrealized < -(cumulative_funding * 2):
                return True
            
            # Additional fallback: exit if stuck beyond 72h without profit
            if age_hours > 72 and unrealized <= 0:
                return True
                
            return False
        except:
            return False

    def force_close_all(self, current_price: float, current_time: pd.Timestamp):
        """Force close all open positions (end of backtest)."""
        for pos in list(self.open_positions):
            self._close_position(pos, current_price, "Force Close", current_time)
    
    def record_equity(self, timestamp: pd.Timestamp, price: float):
        """Record equity for curve plotting."""
        total_equity = self._get_total_equity(price)
        self.peak_capital = max(self.peak_capital, total_equity)
        
        self.equity_curve.append({
            'timestamp': timestamp,
            'equity': total_equity,
            'capital': self.capital,
            'unrealized': total_equity - self.capital,
            'open_positions': len(self.open_positions)
        })
    
    def get_stats(self) -> dict:
        """Calculate comprehensive trading statistics."""
        if not self.closed_positions:
            return {"error": "No closed trades"}
        
        trades = self.closed_positions
        pnls = [t.pnl for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        total_pnl = sum(pnls)
        total_fees = sum(t.fees_paid for t in trades)
        
        # Drawdown calculation
        equity = pd.Series([e['equity'] for e in self.equity_curve])
        peak = equity.expanding().max()
        drawdown = (peak - equity) / peak * 100
        
        # Trade duration
        durations = []
        for t in trades:
            if t.exit_time and t.entry_time:
                dur = (t.exit_time - t.entry_time).total_seconds() / 3600
                durations.append(dur)
        
        # Per-strategy stats
        strategy_stats = {}
        for t in trades:
            s = t.signal.strategy
            if s not in strategy_stats:
                strategy_stats[s] = {"trades": 0, "wins": 0, "pnl": 0}
            strategy_stats[s]["trades"] += 1
            strategy_stats[s]["pnl"] += t.pnl
            if t.pnl > 0:
                strategy_stats[s]["wins"] += 1
        
        for s in strategy_stats:
            st = strategy_stats[s]
            st["win_rate"] = f"{st['wins']/max(st['trades'],1)*100:.1f}%"
            st["avg_pnl"] = round(st["pnl"] / max(st["trades"], 1), 2)
        
        return {
            "total_trades": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": f"{len(wins)/len(trades)*100:.1f}%",
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": f"{total_pnl/self.initial_capital*100:.2f}%",
            "total_fees_paid": round(total_fees, 2),
            "fees_pct_of_capital": f"{total_fees/self.initial_capital*100:.2f}%",
            "net_profit_after_fees": round(total_pnl, 2),
            "avg_win": round(np.mean(wins), 2) if wins else 0,
            "avg_loss": round(np.mean(losses), 2) if losses else 0,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else float('inf'),
            "max_drawdown": f"{drawdown.max():.2f}%",
            "final_capital": round(self.capital, 2),
            "return_pct": f"{(self.capital - self.initial_capital)/self.initial_capital*100:.2f}%",
            "avg_trade_duration_hours": round(np.mean(durations), 1) if durations else 0,
            "sharpe_ratio": self._calculate_sharpe(pnls),
            "strategy_breakdown": strategy_stats
        }

    def _calculate_sharpe(self, pnl_series: list) -> float:
        """
        Issue #2 fix — Sharpe Ratio was computed on dollar PnL, not % returns.

        Dollar PnL has a scale that changes with position size, so
        mean/std is not comparable across time or strategies.

        Fix: derive daily % returns from the equity curve, then annualise.
        This matches the standard Sharpe definition used in finance.
        Crypto trades 24/7 → annualise by 365 days, not 252.
        """
        if not self.equity_curve or len(self.equity_curve) < 2:
            # Fall back to trade-level % returns if equity curve isn't built yet
            # (e.g. called before record_equity, or in unit tests)
            if len(pnl_series) < 2:
                return 0.0
            # Compute % return per trade relative to initial capital
            initial = self.initial_capital or 1.0
            pct_returns = pd.Series(pnl_series) / initial
            if pct_returns.std() == 0:
                return 0.0
            # Per-trade Sharpe: assume ~6 trades/day average for annualisation
            trades_per_day = 6
            sharpe = (pct_returns.mean() / pct_returns.std()) * np.sqrt(trades_per_day * 365)
            return round(sharpe, 2)

        # ── Equity-curve based daily returns ──
        equity_vals = pd.Series(
            [e['equity'] for e in self.equity_curve],
            index=[e['timestamp'] for e in self.equity_curve]
        )
        # Resample to daily buckets (use last equity value per UTC day)
        try:
            if hasattr(equity_vals.index[0], 'date'):
                daily = equity_vals.resample('D').last().dropna()
            else:
                # Positional index — fall back to raw equity points
                daily = equity_vals
        except Exception:
            daily = equity_vals

        if len(daily) < 2:
            return 0.0

        daily_returns = daily.pct_change().dropna()
        if daily_returns.std() == 0:
            return 0.0

        # Risk-free rate ≈ 0 for crypto (no overnight rate)
        sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(365)
        return round(sharpe, 2)

    def calculate_liquidation_price(self, entry_price: float, direction: str,
                                     leverage: int, margin_type: str = "ISOLATED") -> float:
        """Calculate approximate liquidation price for a futures position.
        
        Binance USDM Futures maintenance margin rate ≈ 2.5% for most tiers.
        Formula: liq_price = entry × (1 ∓ 1/lev ± maintenance_ratio)
        """
        lev = leverage or LEVERAGE
        maintenance_ratio = 0.025  # Binance USDM ~2.5% (was incorrect 0.004)
        if margin_type == "ISOLATED":
            if direction == "LONG":
                return entry_price * (1 - 1.0 / lev + maintenance_ratio)
            else:
                return entry_price * (1 + 1.0 / lev - maintenance_ratio)
        else:
            # CROSSED: liquidation depends on total account, approximate
            return 0  # Can't calculate without full account state

    def check_margin_ratio(self, account_data: dict) -> dict:
        """Check if margin ratio is safe. Returns status and recommended action."""
        total_margin = float(account_data.get("totalMaintainMargin", 0))
        total_balance = float(account_data.get("totalMarginBalance", 0))
        if total_balance == 0:
            return {"ratio": 0, "status": "unknown"}
        ratio = total_margin / total_balance
        if ratio >= EMERGENCY_MARGIN_RATIO:
            return {"ratio": ratio, "status": "emergency", "action": "close_all"}
        elif ratio >= MAX_MARGIN_RATIO:
            return {"ratio": ratio, "status": "warning", "action": "reduce_size"}
        return {"ratio": ratio, "status": "safe", "action": "none"}

    def validate_stop_vs_liquidation(self, entry_price: float, stop_loss: float,
                                       direction: str, leverage: int) -> float:
        """Ensure stop loss triggers BEFORE liquidation. Returns adjusted SL if needed."""
        liq_price = self.calculate_liquidation_price(entry_price, direction, leverage)
        if liq_price == 0:
            return stop_loss  # Can't validate for CROSSED

        if direction == "LONG":
            # SL must be ABOVE liquidation by safety margin
            safe_sl = liq_price * (1 + LIQUIDATION_SAFETY_PCT)
            if stop_loss < safe_sl:
                return safe_sl
        else:
            safe_sl = liq_price * (1 - LIQUIDATION_SAFETY_PCT)
            if stop_loss > safe_sl:
                return safe_sl
        return stop_loss

    # ─── Portfolio Heat ───
    def get_portfolio_heat(self, open_positions: list) -> float:
        """
        Total capital % currently at risk across all open positions.
        Heat = sum(risk_per_position) / capital
        risk = (entry - sl) * qty for LONG, (sl - entry) * qty for SHORT
        """
        total_risk = 0.0
        for pos in open_positions:
            try:
                entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))
                sl = float(pos.get('stop_loss', 0))
                qty = float(pos.get('quantity', 0))
                direction = pos.get('direction', 'LONG')
                if entry <= 0 or sl <= 0 or qty <= 0:
                    continue
                if direction == 'LONG':
                    risk = (entry - sl) * qty
                else:
                    risk = (sl - entry) * qty
                total_risk += max(risk, 0)
            except Exception:
                continue
        heat = total_risk / max(self.capital, 1.0)
        self._current_heat = heat
        return heat

    def heat_allows_new_trade(self, open_positions: list, signal) -> tuple:
        """Check portfolio heat before opening a new trade."""
        heat = self.get_portfolio_heat(open_positions)
        if heat >= MAX_PORTFOLIO_HEAT:
            return False, f"Portfolio heat {heat:.1%} >= max {MAX_PORTFOLIO_HEAT:.1%}"
        return True, f"Heat OK ({heat:.1%})"

    def get_heat_size_multiplier(self, open_positions: list) -> float:
        """Scale down new position if heat is approaching the limit."""
        heat = self.get_portfolio_heat(open_positions)
        headroom = MAX_PORTFOLIO_HEAT - heat
        if headroom <= 0:
            return 0.0
        fraction = heat / MAX_PORTFOLIO_HEAT
        if fraction > 0.75:
            return 0.5   # Close to limit: half size
        return 1.0

    # ─── Drawdown-Adaptive Sizing ───
    def get_drawdown_size_multiplier(self, current_equity: float = None) -> float:
        """
        Gradually reduce position size as drawdown increases.
        0-5%: full size | 5-8%: 0.75x | 8-12%: 0.5x | 12-15%: 0.25x | >15%: 0
        """
        equity = current_equity or self.capital
        if self.peak_capital <= 0:
            return 1.0
        dd = (self.peak_capital - equity) / self.peak_capital
        multiplier = 1.0
        for threshold, factor in zip(DRAWDOWN_SCALE_LEVELS, DRAWDOWN_SIZE_FACTORS):
            if dd >= threshold:
                multiplier = factor
        return multiplier

    # ─── Regime-Based Risk Scaling ───
    def get_regime_size_multiplier(self, regime_name: str) -> float:
        """Adjust position size based on current market regime."""
        regime_multipliers = {
            'Trending-Up':   1.20,   # Best conditions for directional trades
            'Trending-Down': 1.10,   # Good for shorts
            'Ranging':       1.00,   # Normal conditions
            'Volatile':      0.70,   # Reduce size in chaotic markets
            'Trending':      1.10,   # Legacy compatibility
        }
        return regime_multipliers.get(regime_name, 1.0)

    def check_funding_cost(self, symbol: str, position_value: float) -> dict:
        """Estimate daily funding cost for a position."""
        try:
            from data import ccxt_client as bnb
            mark = bnb.get_mark_price(symbol)
            rate = float(mark.get("lastFundingRate", 0))
            daily_cost = abs(position_value * rate * 3)  # 3 funding periods per day
            annual_cost_pct = abs(rate * 3 * 365) * 100
            return {"rate_8h": rate, "daily_cost": daily_cost, "annual_pct": annual_cost_pct}
        except:
            return {"rate_8h": 0, "daily_cost": 0, "annual_pct": 0}
