"""
Fee-Aware Filter + Risk Management
====================================
Ensures every trade has positive expected value after fees.
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *


class FeeFilter:
    """
    Filters trades where expected profit doesn't justify the fees.
    
    Rule: expected_profit >= total_fee * FEE_MULTIPLIER
    """
    
    def __init__(self, maker_fee=MAKER_FEE, taker_fee=TAKER_FEE, 
                 slippage=SLIPPAGE, multiplier=FEE_MULTIPLIER):
        self.total_fee = (taker_fee * 2) + slippage  # Entry + Exit + Slippage
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
                 max_open_trades=MAX_OPEN_TRADES):
        
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.peak_capital = initial_capital
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
    
    def calculate_position_size(self, signal) -> float:
        """
        Calculate position size based on risk per trade.
        Risk amount = Capital * risk_per_trade
        Position size = Risk amount / (entry - stop_loss)
        """
        if self.is_circuit_broken:
            return 0.0
        
        risk_amount = self.capital * self.risk_per_trade
        risk_per_unit = abs(signal.entry_price - signal.stop_loss)
        
        if risk_per_unit <= 0:
            return 0.0
        
        position_size = risk_amount / risk_per_unit
        
        # Cap at 50% of capital in notional value
        max_notional = self.capital * 0.5
        max_size = max_notional / signal.entry_price
        position_size = min(position_size, max_size)
        
        # Minimum trade size (0.0001 BTC for Binance)
        if position_size * signal.entry_price < 10:  # Min $10 notional
            return 0.0
        
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
        entry_fee = notional * TAKER_FEE
        
        # Check if we have enough capital for notional + fee
        if notional + entry_fee > self.capital:
            quantity = (self.capital * 0.95) / (signal.entry_price * (1 + TAKER_FEE))
            quantity = round(quantity, 6)
            notional = signal.entry_price * quantity
            entry_fee = notional * TAKER_FEE
            if notional < 10:
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
        """Check all open positions for exit conditions."""
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
                    exit_price = signal.stop_loss
                    exit_reason = "Stop Loss"
                # Check take profit
                elif high >= signal.take_profit:
                    exit_price = signal.take_profit
                    exit_reason = "Take Profit"
            
            elif signal.direction == "SHORT":
                # Check stop loss
                if high >= signal.stop_loss:
                    exit_price = signal.stop_loss
                    exit_reason = "Stop Loss"
                # Check take profit
                elif low <= signal.take_profit:
                    exit_price = signal.take_profit
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
        exit_fee = exit_notional * TAKER_FEE
        position.fees_paid += exit_fee
        
        # Net PnL after all fees
        position.pnl = pnl - position.fees_paid
        
        # Return capital: original notional + PnL - exit fee
        entry_notional = position.entry_price * position.quantity
        self.capital += entry_notional + pnl - exit_fee
        self.daily_pnl += position.pnl
        # peak_capital tracked in record_equity()
        
        # Move to closed
        self.open_positions.remove(position)
        self.closed_positions.append(position)
    
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
            "sharpe_approx": round(np.mean(pnls) / max(np.std(pnls), 0.01) * np.sqrt(len(trades)), 2),
            "strategy_breakdown": strategy_stats
        }
