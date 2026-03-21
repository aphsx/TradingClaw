"""
Database Module - MySQL operations for the trading system
"""
import json
from datetime import datetime
from typing import Optional, List
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
import pandas as pd
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

_engine = None

def get_engine():
    global _engine
    if _engine is None:
        url = f"mysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        _engine = create_engine(url, poolclass=QueuePool, pool_size=5,
                                pool_recycle=3600, echo=False)
    return _engine


def log(level: str, component: str, message: str, data: dict = None):
    """Write to system_log table."""
    try:
        eng = get_engine()
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO system_log (level, component, message, data) "
                "VALUES (:l, :c, :m, :d)"
            ), {"l": level, "c": component, "m": message,
                "d": json.dumps(data, default=str) if data else None})
    except Exception:
        pass  # Don't crash on log failure


# ═══════════════════════════════════════
# CANDLES
# ═══════════════════════════════════════
def save_candles(df: pd.DataFrame, symbol: str, timeframe: str):
    """Bulk upsert candle data."""
    eng = get_engine()
    with eng.begin() as conn:
        for idx, row in df.iterrows():
            conn.execute(text("""
                INSERT INTO candles (symbol, timeframe, timestamp, open, high, low, close, volume, quote_volume, trades)
                VALUES (:sym, :tf, :ts, :o, :h, :l, :c, :v, :qv, :t)
                ON DUPLICATE KEY UPDATE open=:o, high=:h, low=:l, close=:c, volume=:v, quote_volume=:qv, trades=:t
            """), {"sym": symbol, "tf": timeframe, "ts": idx,
                   "o": float(row['open']), "h": float(row['high']),
                   "l": float(row['low']), "c": float(row['close']),
                   "v": float(row['volume']),
                   "qv": float(row.get('quote_volume', 0)),
                   "t": int(row.get('trades', 0))})
    log("INFO", "data", f"Saved {len(df)} candles for {symbol} {timeframe}")


def load_candles(symbol: str, timeframe: str, limit: int = 5000) -> pd.DataFrame:
    """Load candles from DB."""
    eng = get_engine()
    df = pd.read_sql(text(
        "SELECT timestamp, open, high, low, close, volume, quote_volume, trades "
        "FROM candles WHERE symbol=:s AND timeframe=:tf "
        "ORDER BY timestamp DESC LIMIT :lim"
    ), eng, params={"s": symbol, "tf": timeframe, "lim": limit})
    if len(df) > 0:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp').sort_index()
    return df


# ═══════════════════════════════════════
# REGIMES
# ═══════════════════════════════════════
def save_regimes(regimes_df: pd.DataFrame, symbol: str, timeframe: str):
    """Save regime predictions."""
    eng = get_engine()
    with eng.begin() as conn:
        for idx, row in regimes_df.iterrows():
            conn.execute(text("""
                INSERT INTO regimes (symbol, timeframe, timestamp, regime, regime_name,
                    confidence, prob_trending, prob_ranging, prob_volatile, adx, atr_pct, volatility)
                VALUES (:sym, :tf, :ts, :r, :rn, :conf, :pt, :pr, :pv, :adx, :atr, :vol)
                ON DUPLICATE KEY UPDATE regime=:r, regime_name=:rn, confidence=:conf,
                    prob_trending=:pt, prob_ranging=:pr, prob_volatile=:pv
            """), {"sym": symbol, "tf": timeframe, "ts": idx,
                   "r": int(row.get('regime', 0)), "rn": str(row.get('regime_name', '')),
                   "conf": float(row.get('confidence', 0)),
                   "pt": float(row.get('prob_trending', 0)),
                   "pr": float(row.get('prob_ranging', 0)),
                   "pv": float(row.get('prob_volatile', 0)),
                   "adx": float(row.get('adx', 0)) if 'adx' in row else None,
                   "atr": float(row.get('atr_pct', 0)) if 'atr_pct' in row else None,
                   "vol": float(row.get('volatility_20', 0)) if 'volatility_20' in row else None})


# ═══════════════════════════════════════
# SIGNALS
# ═══════════════════════════════════════
def save_signal(signal, symbol: str, fee_filtered: bool = True) -> int:
    """Save a trading signal, return its ID."""
    eng = get_engine()
    with eng.begin() as conn:
        result = conn.execute(text("""
            INSERT INTO signals (symbol, timestamp, direction, strategy, regime,
                entry_price, stop_loss, take_profit, atr, confidence,
                expected_profit_pct, fee_filtered)
            VALUES (:sym, :ts, :dir, :strat, :reg, :ep, :sl, :tp, :atr, :conf, :epp, :ff)
        """), {"sym": symbol, "ts": signal.timestamp, "dir": signal.direction,
               "strat": signal.strategy, "reg": signal.regime,
               "ep": signal.entry_price, "sl": signal.stop_loss,
               "tp": signal.take_profit, "atr": signal.atr,
               "conf": signal.confidence, "epp": signal.expected_profit_pct,
               "ff": fee_filtered})
        return result.lastrowid


# ═══════════════════════════════════════
# POSITIONS
# ═══════════════════════════════════════
def open_position(signal_id: int, symbol: str, direction: str, strategy: str,
                  regime: int, entry_price: float, entry_time, quantity: float,
                  entry_fee: float, stop_loss: float, take_profit: float,
                  risk_reward: float) -> int:
    """Record a new open position."""
    eng = get_engine()
    with eng.begin() as conn:
        result = conn.execute(text("""
            INSERT INTO positions (signal_id, symbol, direction, strategy, regime,
                status, entry_price, entry_time, quantity, entry_fee,
                stop_loss, take_profit, risk_reward)
            VALUES (:sid, :sym, :dir, :strat, :reg, 'OPEN', :ep, :et, :qty, :ef, :sl, :tp, :rr)
        """), {"sid": signal_id, "sym": symbol, "dir": direction,
               "strat": strategy, "reg": regime, "ep": entry_price,
               "et": entry_time, "qty": quantity, "ef": entry_fee,
               "sl": stop_loss, "tp": take_profit, "rr": risk_reward})
        return result.lastrowid


def close_position(position_id: int, exit_price: float, exit_time,
                   exit_reason: str, exit_fee: float, pnl: float, pnl_pct: float,
                   total_fees: float):
    """Close an open position."""
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            UPDATE positions SET status='CLOSED', exit_price=:ep, exit_time=:et,
                exit_reason=:er, exit_fee=:ef, pnl=:pnl, pnl_pct=:pp, total_fees=:tf
            WHERE id=:id
        """), {"ep": exit_price, "et": exit_time, "er": exit_reason,
               "ef": exit_fee, "pnl": pnl, "pp": pnl_pct, "tf": total_fees,
               "id": position_id})


def get_open_positions(symbol: str = None) -> pd.DataFrame:
    eng = get_engine()
    q = "SELECT * FROM positions WHERE status='OPEN'"
    params = {}
    if symbol:
        q += " AND symbol=:sym"
        params["sym"] = symbol
    return pd.read_sql(text(q), eng, params=params)


# ═══════════════════════════════════════
# EQUITY CURVE
# ═══════════════════════════════════════
def save_equity_point(timestamp, equity: float, capital: float,
                      unrealized: float, open_pos: int, drawdown_pct: float,
                      peak_equity: float):
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO equity_curve (timestamp, equity, capital, unrealized,
                open_positions, drawdown_pct, peak_equity)
            VALUES (:ts, :eq, :cap, :ur, :op, :dd, :pe)
        """), {"ts": timestamp, "eq": equity, "cap": capital,
               "ur": unrealized, "op": open_pos, "dd": drawdown_pct,
               "pe": peak_equity})


def save_equity_batch(equity_data: list):
    """Bulk save equity curve points."""
    eng = get_engine()
    with eng.begin() as conn:
        for e in equity_data:
            conn.execute(text("""
                INSERT INTO equity_curve (timestamp, equity, capital, unrealized,
                    open_positions, drawdown_pct, peak_equity)
                VALUES (:ts, :eq, :cap, :ur, :op, :dd, :pe)
            """), {"ts": e['timestamp'], "eq": e['equity'],
                   "cap": e['capital'], "ur": e.get('unrealized', 0),
                   "op": e.get('open_positions', 0),
                   "dd": e.get('drawdown_pct', 0),
                   "pe": e.get('peak_equity', e['equity'])})


# ═══════════════════════════════════════
# BACKTEST RUNS
# ═══════════════════════════════════════
def save_backtest_run(results: dict, config: dict) -> int:
    eng = get_engine()
    t = results.get('trading', {})
    d = results.get('data', {})
    with eng.begin() as conn:
        result = conn.execute(text("""
            INSERT INTO backtest_runs (run_name, symbol, timeframe, initial_capital,
                final_capital, total_trades, win_rate, profit_factor, max_drawdown,
                sharpe_ratio, total_pnl, total_fees, config_json, results_json)
            VALUES (:rn, :sym, :tf, :ic, :fc, :tt, :wr, :pf, :md, :sr, :tp, :tfe, :cj, :rj)
        """), {"rn": f"Backtest_{datetime.now().strftime('%Y%m%d_%H%M')}",
               "sym": d.get('symbol', ''), "tf": d.get('timeframe', ''),
               "ic": config.get('initial_capital', 10000),
               "fc": t.get('final_capital', 0), "tt": t.get('total_trades', 0),
               "wr": float(str(t.get('win_rate', '0')).replace('%', '')),
               "pf": t.get('profit_factor', 0),
               "md": float(str(t.get('max_drawdown', '0')).replace('%', '')),
               "sr": t.get('sharpe_approx', 0), "tp": t.get('total_pnl', 0),
               "tfe": t.get('total_fees_paid', 0),
               "cj": json.dumps(config, default=str),
               "rj": json.dumps(results, default=str)})
        return result.lastrowid
