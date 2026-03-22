"""
DEPRECATED — strategies.py
============================
Replaced by strategies/signal_engine.py (TradingClaw v5).
This file is kept as a compatibility shim only.
"""
# Re-export Signal dataclass and check_exit_signals so any external
# code that imported from strategies.strategies still works.
from strategies.signal_engine import Signal, check_exit_signals

__all__ = ['Signal', 'check_exit_signals']
