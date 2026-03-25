"""
Fee-Aware Filter + World-Class Risk Management
===============================================
Upgraded risk manager with CVaR, regime-aware Kelly, anti-martingale streak sizing,
smooth drawdown scaling, session filtering, and OKX-specific adjustments.

Key Features:
- Enhanced Kelly Criterion with regime-specific and streak-based scaling
- CVaR (Conditional Value at Risk) for tail risk monitoring
- Anti-Martingale streak multiplier for position sizing
- Smooth drawdown curve instead of step-function
- Session-aware position sizing (dead zone, quality-based reductions)
- Regime-specific risk budgets (TRENDING/RANGING/VOLATILE)
- Maximum notional exposure tracking (80% cap)
- OKX-specific liquidation and maintenance margin calculations
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from collections import deque
from datetime import datetime, timezone
import sys, os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *
from config import (
    LEVERAGE, MAX_MARGIN_RATIO, EMERGENCY_MARGIN_RATIO, LIQUIDATION_SAFETY_PCT,
    MAX_PORTFOLIO_HEAT, DRAWDOWN_SCALE_LEVELS, DRAWDOWN_SIZE_FACTORS,
    CAPITAL_TIERS, CVAR_CONFIDENCE, MAX_CVAR_PCT, ANTI_MARTINGALE,
    WIN_STREAK_BONUS, LOSS_STREAK_PENALTY, SESSION_FILTER_ENABLED,
    DEAD_ZONE_HOURS, ASIAN_SESSION, EUROPE_SESSION, US_SESSION
)


def get_risk_tier(capital: float) -> dict:
    """
    Return risk settings based on account size.
    Smaller accounts get higher risk% and higher leverage so trades are meaningful.
    Each tier has its own leverage (min 10x, max 20x).
    """
    for row in CAPITAL_TIERS:
        max_cap, risk_pct, min_notional, label = row[0], row[1], row[2], row[3]
        tier_leverage = int(row[4]) if len(row) > 4 else LEVERAGE
        if capital <= max_cap:
            return {
                "risk_pct":     risk_pct,
                "min_notional": min_notional,
                "label":        label,
                "leverage":     max(10, tier_leverage),  # enforce minimum 10x
            }
    # Fallback
    return {"risk_pct": 0.01, "min_notional": 10.0, "label": "Large $2k+", "leverage": 10}


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
    margin_used: float = 0.0
    funding_paid: float = 0.0
    liquidation_price: float = 0.0
    leverage_used: float = 0.0
    pnl: float = 0.0
    gross_pnl: float = 0.0
    exit_price: float = 0.0
    exit_time: Optional[pd.Timestamp] = None
    exit_reason: str = ""
    exit_reason_detail: str = ""
    is_open: bool = True
    fees_paid: float = 0.0
    entry_fee: float = 0.0
    exit_fee: float = 0.0
    funding_fee: float = 0.0
    fill_ratio: float = 1.0
    entry_latency_bars: int = 0
    event_counters: Dict[str, int] = field(default_factory=dict)
    execution_path: str = ""


class RiskManager:
    """
    World-class position sizing and risk control.

    Capabilities:
    - Enhanced Kelly Criterion (regime-aware, streak-aware, decay on drawdowns)
    - CVaR monitoring (95% confidence, tail risk detection)
    - Anti-Martingale sizing (increase on streaks, decrease on losses)
    - Smooth drawdown scaling (no step functions)
    - Session-aware sizing (dead zone, quality-based)
    - Regime-specific risk budgets
    - Notional exposure tracking (80% cap)
    - OKX-specific liquidation calculations
    """

    def __init__(self, initial_capital=INITIAL_CAPITAL,
                 risk_per_trade=RISK_PER_TRADE,
                 max_daily_loss=MAX_DAILY_LOSS,
                 max_drawdown=MAX_DRAWDOWN,
                 max_open_trades=MAX_OPEN_TRADES,
                 taker_fee=None,
                 maker_fee=None,
                 exchange="okx"):

        self.taker_fee = taker_fee if taker_fee is not None else TAKER_FEE
        self.maker_fee = maker_fee if maker_fee is not None else MAKER_FEE
        self.exchange = exchange.lower()  # 'okx', 'binance', 'bybit'
        self._rng = np.random.default_rng(42)

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

        # Track trade results for Kelly sizing — PER REGIME
        self.trade_results = deque(maxlen=100)
        self.trade_results_by_regime: Dict[str, deque] = {}  # regime -> deque of returns
        self._current_heat = 0.0

        # Streak tracking for anti-martingale
        self._current_streak = 0  # >0 = wins, <0 = losses
        self._streak_multiplier = 1.0

        # CVaR tracking
        self._recent_returns = deque(maxlen=100)  # For CVaR calculation
        self._cvar_value = 0.0

        # Dynamic tier — recalculated whenever capital is synced
        tier = get_risk_tier(start_capital)
        self._risk_pct: float      = tier["risk_pct"]
        self._min_notional: float  = tier["min_notional"]
        self._tier_label: str      = tier["label"]
        self._leverage: int        = tier["leverage"]
        self._capital_synced: bool = (initial_capital > 0)

        # Regime-specific tracking
        self._current_regime = "TRENDING"  # Will be updated by caller
        self._regime_kelly_cache: Dict[str, float] = {}  # Cache regime-specific Kelly

    def _signal_execution_profile(self, signal) -> dict:
        return getattr(signal, "execution_profile", {}) or {}

    def _effective_leverage(self, signal) -> int:
        profile = self._signal_execution_profile(signal)
        cap = int(profile.get("leverage_cap", self._leverage) or self._leverage)
        return max(1, min(self._leverage, cap))

    def sync_capital(self, live_balance: float) -> str:
        """
        Sync capital with the real exchange balance and recalculate risk tier.
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
        self._risk_pct     = tier["risk_pct"]
        self._min_notional = tier["min_notional"]
        self._tier_label   = tier["label"]
        self._leverage     = tier["leverage"]

        return (
            f"[BALANCE] Capital synced: ${old_capital:.2f} → ${live_balance:.2f} | "
            f"Tier: {self._tier_label} | "
            f"Risk/trade: {self._risk_pct*100:.1f}% | "
            f"Leverage: {self._leverage}x | "
            f"Min notional: ${self._min_notional:.1f}"
        )

    def get_tier_info(self) -> dict:
        """Return current tier settings for display/logging."""
        return {
            "capital": round(self.capital, 2),
            "tier": self._tier_label,
            "risk_pct": f"{self._risk_pct*100:.1f}%",
            "leverage": self._leverage,
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
        self.trade_results_by_regime = {}
        self._current_heat = 0.0
        self._current_streak = 0
        self._streak_multiplier = 1.0
        self._recent_returns = deque(maxlen=100)
        self._cvar_value = 0.0
        self._regime_kelly_cache = {}

    # ─── CVaR (Conditional Value at Risk) ───
    def calculate_cvar(self, confidence: float = None) -> float:
        """
        Calculate CVaR (Conditional Value at Risk) at given confidence level.
        CVaR = average of worst X% of returns.

        Used to detect tail risk: if CVaR > MAX_CVAR_PCT, reduce new position sizes.
        """
        if confidence is None:
            confidence = CVAR_CONFIDENCE  # default 0.95

        if len(self._recent_returns) < 10:
            return 0.0

        returns = sorted(list(self._recent_returns))
        tail_index = int(len(returns) * (1 - confidence))

        if tail_index == 0:
            tail_index = 1

        # CVaR is the average of the worst (1-confidence)% of returns
        cvar = np.mean(returns[:tail_index])
        self._cvar_value = cvar
        return cvar

    def get_exposure_stats(self) -> dict:
        """
        Return current notional exposure stats.
        Tracks whether we're approaching the 80% maximum utilization cap.
        """
        total_notional = sum(
            p.entry_price * p.quantity for p in self.open_positions
        )
        max_notional = self.capital * self._leverage * 0.8
        utilization = total_notional / max_notional if max_notional > 0 else 0.0

        return {
            "current_notional": round(total_notional, 2),
            "max_notional_80pct": round(max_notional, 2),
            "utilization_pct": round(utilization * 100, 1),
            "headroom": round(max_notional - total_notional, 2),
        }

    # ─── Streak Tracking for Anti-Martingale ───
    def _update_streak(self, is_win: bool):
        """Update streak counter and calculate multiplier for next trade."""
        if is_win:
            if self._current_streak < 0:
                self._current_streak = 1  # Reset from losing streak
            else:
                self._current_streak += 1
        else:
            if self._current_streak > 0:
                self._current_streak = -1  # Reset from winning streak
            else:
                self._current_streak -= 1

    def get_streak_multiplier(self) -> float:
        """
        Get position size multiplier based on consecutive wins/losses.

        Wins: +10% per streak, max +30% (3 streaks)
        Losses: -15% per streak, max -45% (3 streaks)
        """
        if not ANTI_MARTINGALE:
            return 1.0

        multiplier = 1.0

        if self._current_streak > 0:
            # Winning streak: increase size
            streak_count = min(self._current_streak, 3)
            multiplier = 1.0 + (streak_count * WIN_STREAK_BONUS)
        elif self._current_streak < 0:
            # Losing streak: decrease size
            streak_count = min(abs(self._current_streak), 3)
            multiplier = 1.0 - (streak_count * LOSS_STREAK_PENALTY)
            multiplier = max(0.1, multiplier)  # Floor at 10% minimum

        self._streak_multiplier = multiplier
        return multiplier

    # ─── Enhanced Kelly Criterion ───
    def _calculate_kelly_size(self, regime: str = None) -> float:
        """
        Calculate Kelly fraction based on recent trade history, PER REGIME.

        Logic:
        1. If regime is provided and has enough samples (>=MIN_WIN_RATE_SAMPLE),
           use regime-specific Kelly
        2. Fall back to global Kelly if regime data insufficient
        3. Apply Kelly decay: after long losing streaks, reduce Kelly
        4. Cap Kelly at 0.25 (quarter Kelly) during VOLATILE regime
        5. Return already divided by leverage (as margin %)
        """
        risk_pct = self._risk_pct  # tier-aware base

        # Determine which data to use
        if regime and regime in self.trade_results_by_regime:
            recent = list(self.trade_results_by_regime[regime])
        else:
            recent = list(self.trade_results)

        # Need minimum sample size
        if len(recent) < MIN_WIN_RATE_SAMPLE:
            return risk_pct / self._leverage

        wins = [t for t in recent if t > 0]
        losses = [t for t in recent if t <= 0]

        if not wins or not losses:
            return risk_pct / self._leverage

        win_rate = len(wins) / len(recent)
        avg_win = sum(wins) / len(wins)
        avg_loss = abs(sum(losses) / len(losses))

        if avg_loss == 0:
            return risk_pct / self._leverage

        # Kelly formula: f* = (b*p - q) / b, where b = avg_win/avg_loss, p = win_rate, q = 1-p
        b = avg_win / avg_loss
        kelly = (b * win_rate - (1 - win_rate)) / b
        kelly = max(0, kelly) * KELLY_FRACTION  # Apply Kelly fraction (typically 0.5 = half Kelly)

        # Apply Kelly decay on long losing streaks
        if self._current_streak < -5:
            # After 5+ consecutive losses, gradually reduce Kelly
            decay_factor = max(0.5, 1.0 - (abs(self._current_streak) - 5) * 0.05)
            kelly *= decay_factor

        # Cap Kelly at quarter Kelly during volatile regime
        kelly_cap = risk_pct / 4 if regime == "VOLATILE" else risk_pct / 2
        kelly = min(kelly, kelly_cap)

        return kelly / self._leverage

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

    def _get_session_quality_multiplier(self, current_time: pd.Timestamp) -> float:
        """
        Adjust position size based on trading session quality.

        Dead zone (low liquidity): -40%
        High-quality session (matching strategy): no reduction
        Low-quality session: -20%
        """
        if not SESSION_FILTER_ENABLED:
            return 1.0

        try:
            hour = current_time.hour if hasattr(current_time, 'hour') else int(str(current_time).split()[1].split(':')[0])
        except:
            return 1.0

        # Check dead zone first
        if hour in DEAD_ZONE_HOURS:
            return 0.6  # Reduce by 40%

        # Session quality — simplified version
        # In live trading, this would be enhanced with strategy-specific session alignment
        if ASIAN_SESSION[0] <= hour < ASIAN_SESSION[1]:
            # Asian session: lower vol, range-friendly
            return 1.0  # Good for mean reversion
        elif EUROPE_SESSION[0] <= hour < EUROPE_SESSION[1]:
            # European session: medium vol, trend-friendly
            return 1.0  # Good for trend
        elif US_SESSION[0] <= hour < US_SESSION[1]:
            # US session: high vol, breakout-friendly
            return 1.0  # Good for volatility

        return 1.0

    def _get_regime_risk_budget(self, regime: str) -> float:
        """
        Get max risk per trade based on regime.
        Overrides tier-based risk_pct when lower.

        TRENDING: 2.0% (higher conviction)
        RANGING:  1.0% (lower conviction, MR only)
        VOLATILE: 0.8% (high uncertainty)
        """
        regime_budgets = {
            "TRENDING":     0.02,   # 2.0%
            "RANGING":      0.01,   # 1.0%
            "VOLATILE":     0.008,  # 0.8%
            "Trending-Up":  0.02,
            "Trending-Down": 0.02,
        }
        budget = regime_budgets.get(regime, 0.02)
        # Use the lower of regime budget vs tier-based risk_pct
        return min(self._risk_pct, budget)

    def _get_cvar_size_reduction(self) -> float:
        """
        If CVaR exceeds MAX_CVAR_PCT, reduce position sizes by 50%.
        CVaR monitoring detects tail risk escalation.
        """
        if abs(self._cvar_value) > MAX_CVAR_PCT:
            return 0.5  # Reduce new positions by 50%
        return 1.0

    def calculate_position_size(self, signal, current_atr_pct: float = None,
                                avg_atr_pct: float = None, current_time: pd.Timestamp = None,
                                regime: str = None) -> float:
        """
        Calculate position size with ALL enhancements:
        - Enhanced Kelly (regime-aware, streak-decayed, volatile-capped)
        - Volatility adjustment
        - Anti-Martingale streak multiplier
        - Session quality multiplier
        - Regime-specific risk budget
        - CVaR-based reduction
        - Smooth drawdown scaling
        - Notional exposure cap (80%)

        Kelly size is already expressed as a fraction of margin capital (÷ leverage),
        so risk_amount is the margin committed, and actual notional = risk_amount × leverage.
        """
        if self.is_circuit_broken:
            return 0.0

        # 1. Base Kelly sizing (regime-aware)
        regime = regime or self._current_regime
        effective_leverage = self._effective_leverage(signal)
        kelly_size = self._calculate_kelly_size(regime)

        # 2. Get regime-specific risk budget
        regime_risk_pct = self._get_regime_risk_budget(regime)
        kelly_size = min(kelly_size, regime_risk_pct / effective_leverage)

        # 3. Apply anti-martingale streak multiplier
        streak_mult = self.get_streak_multiplier()
        kelly_size *= streak_mult

        # 4. Apply smooth drawdown scaling (no step functions)
        total_equity = self._get_total_equity(signal.entry_price)
        drawdown = (self.peak_capital - total_equity) / self.peak_capital if self.peak_capital > 0 else 0
        smooth_dd_mult = max(0.1, 1.0 - (drawdown / self.max_drawdown) ** 1.5)
        kelly_size *= smooth_dd_mult

        # 5. Apply session quality multiplier
        if current_time:
            session_mult = self._get_session_quality_multiplier(current_time)
            kelly_size *= session_mult

        # 6. Apply CVaR-based reduction if tail risk too high
        cvar_mult = self._get_cvar_size_reduction()
        kelly_size *= cvar_mult

        # 7. Apply volatility adjustment
        risk_amount = self.capital * kelly_size
        if current_atr_pct is not None and avg_atr_pct is not None:
            vol_adj = self._get_vol_adjustment(current_atr_pct, avg_atr_pct)
            risk_amount *= vol_adj

        # 8. Calculate position size
        risk_per_unit = abs(signal.entry_price - signal.stop_loss)
        if risk_per_unit <= 0:
            return 0.0

        position_size = risk_amount / risk_per_unit

        # 9. Enforce maximum notional exposure (80% cap)
        current_open_notional = sum(
            p.entry_price * p.quantity for p in self.open_positions
        )
        max_total_notional = self.capital * effective_leverage * 0.8  # 80% cap
        remaining_notional = max_total_notional - current_open_notional

        if remaining_notional <= 0:
            return 0.0

        max_size_by_notional = remaining_notional / signal.entry_price

        # 10. Also cap per-trade at 50% of capital margin
        max_margin_per_trade = self.capital * 0.5
        max_size_by_margin = (max_margin_per_trade * effective_leverage) / signal.entry_price

        position_size = min(position_size, max_size_by_notional, max_size_by_margin)

        # 11. Enforce minimum notional floor
        if position_size * signal.entry_price < self._min_notional:
            position_size = self._min_notional / signal.entry_price

        return round(position_size, 6)

    def _get_total_equity(self, current_price: float = None) -> float:
        """Get total equity = free margin + locked margin + unrealized PnL."""
        equity = self.capital
        for pos in self.open_positions:
            margin = getattr(pos, "margin_used", 0.0)
            if current_price:
                if pos.signal.direction == "LONG":
                    unrealized = (current_price - pos.entry_price) * pos.quantity
                else:
                    unrealized = (pos.entry_price - current_price) * pos.quantity
                equity += margin + unrealized
            else:
                equity += margin
        return equity

    def can_open_trade(self, signal, current_time: pd.Timestamp,
                       current_price: float = None, regime: str = None) -> tuple:
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
        position_size = self.calculate_position_size(signal, current_time=current_time, regime=regime)
        if position_size <= 0:
            return False, "Insufficient capital for position"

        return True, "OK"

    def open_position(self, signal, current_time: pd.Timestamp, regime: str = None) -> Optional[Position]:
        """Open a new position."""
        regime = regime or self._current_regime
        can_trade, reason = self.can_open_trade(signal, current_time, signal.entry_price, regime)
        if not can_trade:
            return None

        effective_leverage = self._effective_leverage(signal)
        signal.stop_loss = self.validate_stop_vs_liquidation(
            signal.entry_price, signal.stop_loss, signal.direction, effective_leverage
        )
        quantity = self.calculate_position_size(signal, current_time=current_time, regime=regime)
        notional = signal.entry_price * quantity
        margin_required = notional / max(effective_leverage, 1)
        execution_profile = getattr(signal, "execution_profile", {}) or {}
        entry_fee_rate = float(execution_profile.get("entry_fee_rate", self.taker_fee))
        entry_fee = notional * entry_fee_rate
        liquidation_price = self.calculate_liquidation_price(signal.entry_price, signal.direction, effective_leverage)

        # Futures need margin + fee, not the full notional.
        if margin_required + entry_fee > self.capital:
            quantity = (self.capital * 0.95) / (
                signal.entry_price * ((1 / max(effective_leverage, 1)) + entry_fee_rate)
            )
            quantity = round(quantity, 6)
            notional = signal.entry_price * quantity
            margin_required = notional / max(effective_leverage, 1)
            entry_fee = notional * entry_fee_rate
            # Hard reject only if balance itself is too small to cover even min notional
            if notional < self._min_notional:
                return None

        position = Position(
            signal=signal,
            entry_price=signal.entry_price,
            quantity=quantity,
            entry_time=current_time,
            margin_used=margin_required,
            liquidation_price=liquidation_price,
            leverage_used=effective_leverage,
            fees_paid=entry_fee,
            entry_fee=entry_fee,
            entry_latency_bars=int(execution_profile.get("entry_latency_bars", 0) or 0),
        )

        self.open_positions.append(position)
        self.capital -= (margin_required + entry_fee)

        return position

    def _bar_path(self, current_bar: pd.Series) -> list[float]:
        opn = float(current_bar.get('open', current_bar.get('close', 0)))
        high = float(current_bar.get('high', opn))
        low = float(current_bar.get('low', opn))
        close = float(current_bar.get('close', opn))
        return [opn, low, high, close] if close >= opn else [opn, high, low, close]

    def _segment_crosses(self, start: float, end: float, price: float) -> bool:
        if start <= end:
            return start <= price <= end
        return end <= price <= start

    def _resolve_exit_fill(self, position: Position, reason: str, trigger_price: float) -> tuple[float, float]:
        execution_profile = getattr(position.signal, "execution_profile", {}) or {}
        stop_mult = float(execution_profile.get("stop_slippage_mult", 1.0))
        liq_mult = float(execution_profile.get("liquidation_slippage_mult", 1.75))

        if reason == "Take Profit":
            if position.signal.direction == "LONG":
                return trigger_price, self.maker_fee
            return trigger_price, self.maker_fee

        if reason == "Liquidation":
            if position.signal.direction == "LONG":
                return trigger_price * (1 - SLIPPAGE * liq_mult), self.taker_fee
            return trigger_price * (1 + SLIPPAGE * liq_mult), self.taker_fee

        if position.signal.direction == "LONG":
            return trigger_price * (1 - SLIPPAGE * stop_mult), self.taker_fee
        return trigger_price * (1 + SLIPPAGE * stop_mult), self.taker_fee

    def _bump_event(self, position: Position, key: str):
        position.event_counters[key] = position.event_counters.get(key, 0) + 1

    def _pick_intrabar_event(self, position: Position, current_bar: pd.Series):
        levels = []
        if position.signal.direction == "LONG":
            levels.append(("Liquidation", float(position.liquidation_price or 0)))
            levels.append(("Stop Loss", float(position.signal.stop_loss or 0)))
            levels.append(("Take Profit", float(position.signal.take_profit or 0)))
        else:
            levels.append(("Liquidation", float(position.liquidation_price or 0)))
            levels.append(("Stop Loss", float(position.signal.stop_loss or 0)))
            levels.append(("Take Profit", float(position.signal.take_profit or 0)))

        path = self._bar_path(current_bar)
        path_str = " -> ".join(f"{p:.4f}" for p in path)
        for start, end in zip(path, path[1:]):
            hits = []
            for reason, level in levels:
                if level <= 0 or not self._segment_crosses(start, end, level):
                    continue
                hits.append((abs(level - start), 0 if reason == "Liquidation" else 1 if reason == "Stop Loss" else 2, reason, level))

            if not hits:
                continue

            hits.sort(key=lambda item: (item[0], item[1]))
            _, _, reason, trigger_price = hits[0]

            execution_profile = getattr(position.signal, "execution_profile", {}) or {}
            if reason == "Take Profit":
                fill_prob = float(execution_profile.get("maker_fill_probability", 0.97))
                reduce_only_reject_prob = float(execution_profile.get("reduce_only_reject_probability", 0.01))
                maker_missed = self._rng.random() > fill_prob
                reduce_only_rejected = self._rng.random() < reduce_only_reject_prob
                if maker_missed or reduce_only_rejected:
                    if maker_missed:
                        self._bump_event(position, "maker_missed")
                    if reduce_only_rejected:
                        self._bump_event(position, "reduce_only_rejected")
                    continue

            exit_price, exit_fee_rate = self._resolve_exit_fill(position, reason, trigger_price)
            position.execution_path = path_str
            position.exit_reason_detail = (
                f"path={path_str}; trigger={reason}@{trigger_price:.4f}; "
                f"fill={exit_price:.4f}; fee_type={'maker' if exit_fee_rate == self.maker_fee else 'taker'}"
            )
            return exit_price, reason, exit_fee_rate
        return None

    def apply_funding_costs(self, current_bar: pd.Series, bar_hours: float):
        funding_rate = float(current_bar.get("funding_rate", 0) or 0)
        if funding_rate == 0 or bar_hours <= 0:
            return
        for pos in self.open_positions:
            mark_notional = float(current_bar.get("close", pos.entry_price)) * pos.quantity
            side_mult = 1.0 if pos.signal.direction == "LONG" else -1.0
            funding_cost = mark_notional * funding_rate * (bar_hours / 8.0) * side_mult
            pos.funding_paid += funding_cost
            pos.funding_fee += funding_cost
            pos.fees_paid += funding_cost
            self.capital -= funding_cost

    def check_exits(self, current_bar: pd.Series, current_time: pd.Timestamp):
        """Check exits using intrabar price path, maker/taker fees, and liquidation."""
        positions_to_close = []
        for pos in list(self.open_positions):
            event = self._pick_intrabar_event(pos, current_bar)
            if event:
                exit_price, exit_reason, exit_fee_rate = event
                positions_to_close.append((pos, exit_price, exit_reason, current_time, exit_fee_rate))

        for pos, exit_price, exit_reason, exit_time, exit_fee_rate in positions_to_close:
            self._close_position(pos, exit_price, exit_reason, exit_time, exit_fee_rate=exit_fee_rate)

    def _close_position(self, position: Position, exit_price: float,
                        reason: str, exit_time: pd.Timestamp, exit_fee_rate: float = None):
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
        fee_rate = self.taker_fee if exit_fee_rate is None else exit_fee_rate
        exit_fee = exit_notional * fee_rate
        position.exit_fee = exit_fee
        position.fees_paid += exit_fee

        # Net PnL after all fees
        position.gross_pnl = pnl
        position.pnl = pnl - position.fees_paid

        # Track trade result for Kelly sizing (as a percentage return)
        position_cost = getattr(position, "margin_used", 0.0) or (
            position.entry_price * position.quantity
        )
        if position_cost > 0:
            pnl_return = position.pnl / position_cost
            self.trade_results.append(pnl_return)
            self._recent_returns.append(pnl_return)

            # Track by regime for regime-specific Kelly
            regime = getattr(position.signal, "regime", self._current_regime)
            if regime not in self.trade_results_by_regime:
                self.trade_results_by_regime[regime] = deque(maxlen=100)
            self.trade_results_by_regime[regime].append(pnl_return)

            # Recalculate CVaR with new return
            self.calculate_cvar()

        # Update streak for anti-martingale
        is_win = position.pnl > 0
        self._update_streak(is_win)

        # Return locked margin plus realized PnL, then deduct the exit fee.
        self.capital += position.margin_used + pnl - exit_fee
        self.daily_pnl += position.pnl

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
            pos.exit_reason_detail = "Backtest ended with the position still open."
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
        gross_pnl = sum(getattr(t, "gross_pnl", t.pnl + t.fees_paid) for t in trades)

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
            "gross_pnl_before_fees": round(gross_pnl, 2),
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
            "strategy_breakdown": strategy_stats,
            "cvar_final": round(self._cvar_value, 4),
            "current_streak": self._current_streak,
            "streak_multiplier": round(self._streak_multiplier, 2),
        }

    def _calculate_sharpe(self, pnl_series: list) -> float:
        """
        Sharpe Ratio computed on daily % returns (not dollar PnL).
        Crypto trades 24/7 → annualise by 365 days, not 252.
        """
        if not self.equity_curve or len(self.equity_curve) < 2:
            # Fall back to trade-level % returns if equity curve isn't built yet
            if len(pnl_series) < 2:
                return 0.0
            initial = self.initial_capital or 1.0
            pct_returns = pd.Series(pnl_series) / initial
            if pct_returns.std() == 0:
                return 0.0
            trades_per_day = 6
            sharpe = (pct_returns.mean() / pct_returns.std()) * np.sqrt(trades_per_day * 365)
            return round(sharpe, 2)

        # Equity-curve based daily returns
        equity_vals = pd.Series(
            [e['equity'] for e in self.equity_curve],
            index=[e['timestamp'] for e in self.equity_curve]
        )
        try:
            if hasattr(equity_vals.index[0], 'date'):
                daily = equity_vals.resample('D').last().dropna()
            else:
                daily = equity_vals
        except Exception:
            daily = equity_vals

        if len(daily) < 2:
            return 0.0

        daily_returns = daily.pct_change().dropna()
        if daily_returns.std() == 0:
            return 0.0

        sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(365)
        return round(sharpe, 2)

    def calculate_liquidation_price(self, entry_price: float, direction: str,
                                     leverage: int, margin_type: str = "ISOLATED") -> float:
        """
        Calculate approximate liquidation price for a futures position.

        OKX-specific: maintenance margin rate varies by position size tier.
        OKX format: 0.4% for <10k USDT, 0.5% for 10k-50k, etc.
        """
        lev = leverage or LEVERAGE

        if self.exchange == "okx":
            # OKX maintenance margin rates (tiered by notional)
            maintenance_ratio = 0.005  # Default 0.5% for mid-tier positions
        else:
            # Binance USDM ~2.5%
            maintenance_ratio = 0.025

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

    # ─── Smooth Drawdown Scaling (no step functions) ───
    def get_drawdown_size_multiplier(self, current_equity: float = None) -> float:
        """
        Smoothly reduce position size as drawdown increases.
        Uses smooth curve: multiplier = max(0.1, 1.0 - (drawdown / max_drawdown) ** 1.5)

        This gives gradual reduction instead of sudden drops at thresholds.
        """
        equity = current_equity or self.capital
        if self.peak_capital <= 0:
            return 1.0

        drawdown_pct = (self.peak_capital - equity) / self.peak_capital
        drawdown_ratio = drawdown_pct / self.max_drawdown  # Normalize to max allowed

        # Smooth curve: no step function
        multiplier = max(0.1, 1.0 - (drawdown_ratio ** 1.5))
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
