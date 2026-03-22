"""
Database Module v3 - MySQL operations with source tagging
"""
import json
from datetime import datetime
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


def log(level, component, message, data=None):
    try:
        with get_engine().begin() as c:
            c.execute(text(
                "INSERT INTO system_log (level,component,message,data) VALUES(:l,:c,:m,:d)"
            ), {"l":level,"c":component,"m":message,
                "d":json.dumps(data,default=str) if data else None})
    except Exception:
        pass


# ═══════════════════════════════════════
# CANDLES
# ═══════════════════════════════════════
def save_candles(df, symbol, timeframe):
    with get_engine().begin() as c:
        for idx, row in df.iterrows():
            c.execute(text("""
                INSERT INTO candles (symbol,timeframe,timestamp,open,high,low,close,volume,quote_volume,num_trades)
                VALUES(:s,:tf,:ts,:o,:h,:l,:cl,:v,:qv,:t)
                ON DUPLICATE KEY UPDATE open=:o,high=:h,low=:l,close=:cl,volume=:v
            """), {"s":symbol,"tf":timeframe,"ts":idx,
                   "o":float(row['open']),"h":float(row['high']),
                   "l":float(row['low']),"cl":float(row['close']),
                   "v":float(row['volume']),
                   "qv":float(row.get('quote_volume',0)),
                   "t":int(row.get('trades',0))})


# ═══════════════════════════════════════
# SIGNALS
# ═══════════════════════════════════════
def save_signal(signal, symbol, source="LIVE", run_id=None, fee_filtered=True):
    tp2 = getattr(signal, 'take_profit_2', None)
    score = getattr(signal, 'composite_score', None)
    # Try v5 INSERT with new columns first; fall back if DB schema is old
    try:
        with get_engine().begin() as c:
            r = c.execute(text("""
                INSERT INTO signals (source,run_id,symbol,timestamp,direction,strategy,regime,
                    entry_price,stop_loss,take_profit,take_profit_2,atr,confidence,
                    expected_profit_pct,fee_filtered,composite_score)
                VALUES(:src,:rid,:sym,:ts,:dir,:strat,:reg,:ep,:sl,:tp,:tp2,:atr,:conf,:epp,:ff,:cs)
            """), {"src":source,"rid":run_id,"sym":symbol,"ts":signal.timestamp,
                   "dir":signal.direction,"strat":signal.strategy,"reg":signal.regime,
                   "ep":signal.entry_price,"sl":signal.stop_loss,"tp":signal.take_profit,
                   "tp2":tp2,"atr":signal.atr,"conf":signal.confidence,
                   "epp":signal.expected_profit_pct,"ff":fee_filtered,"cs":score})
            return r.lastrowid
    except Exception as e:
        # Columns may not exist in older schema — fall back without new v5 columns
        if 'take_profit_2' in str(e) or 'composite_score' in str(e):
            with get_engine().begin() as c:
                r = c.execute(text("""
                    INSERT INTO signals (source,run_id,symbol,timestamp,direction,strategy,regime,
                        entry_price,stop_loss,take_profit,atr,confidence,expected_profit_pct,fee_filtered)
                    VALUES(:src,:rid,:sym,:ts,:dir,:strat,:reg,:ep,:sl,:tp,:atr,:conf,:epp,:ff)
                """), {"src":source,"rid":run_id,"sym":symbol,"ts":signal.timestamp,
                       "dir":signal.direction,"strat":signal.strategy,"reg":signal.regime,
                       "ep":signal.entry_price,"sl":signal.stop_loss,"tp":signal.take_profit,
                       "atr":signal.atr,"conf":signal.confidence,
                       "epp":signal.expected_profit_pct,"ff":fee_filtered})
                return r.lastrowid
        raise


# ═══════════════════════════════════════
# POSITIONS - LIVE (with Binance order data)
# ═══════════════════════════════════════
def open_position_live(signal_id, symbol, direction, strategy, regime,
                       entry_price, entry_time, quantity,
                       order_data: dict,
                       stop_loss, take_profit, risk_reward,
                       sl_order_id=None, tp_order_id=None, confidence=None):
    """
    Open a LIVE position with real Binance order data.
    order_data = parsed output from binance_client.parse_order_response()
    """
    with get_engine().begin() as c:
        r = c.execute(text("""
            INSERT INTO positions (
                source, signal_id, symbol, direction, strategy, regime, status,
                entry_price, entry_time, quantity,
                entry_order_id, entry_client_oid, entry_fill_price, entry_fill_qty,
                entry_commission, entry_commission_asset, entry_status, entry_raw,
                stop_loss, take_profit, risk_reward, confidence
            ) VALUES (
                'LIVE', :sid, :sym, :dir, :strat, :reg, 'OPEN',
                :ep, :et, :qty,
                :eoid, :ecoid, :efp, :efq, :ecomm, :eca, :es, :eraw,
                :sl, :tp, :rr, :conf
            )
        """), {
            "sid":signal_id, "sym":symbol, "dir":direction,
            "strat":strategy, "reg":regime,
            "ep":entry_price, "et":entry_time, "qty":quantity,
            "eoid":order_data.get("order_id"),
            "ecoid":order_data.get("client_order_id"),
            "efp":order_data.get("fill_price"),
            "efq":order_data.get("fill_qty"),
            "ecomm":order_data.get("commission"),
            "eca":order_data.get("commission_asset"),
            "es":order_data.get("status"),
            "eraw":json.dumps(order_data.get("raw"), default=str),
            "sl":stop_loss, "tp":take_profit, "rr":risk_reward,
            "conf":confidence,
        })
        pos_id = r.lastrowid

        # Store SL/TP order IDs as JSON in entry_raw if provided
        # (we'll read these back during monitoring)
        if sl_order_id or tp_order_id:
            raw = order_data.get("raw", {})
            raw["_sl_order_id"] = sl_order_id
            raw["_tp_order_id"] = tp_order_id
            c.execute(text("UPDATE positions SET entry_raw=:r WHERE id=:id"),
                      {"r": json.dumps(raw, default=str), "id": pos_id})

        return pos_id


def close_position_live(position_id, exit_price, exit_time, exit_reason,
                        exit_order_id=None, exit_client_oid=None,
                        exit_fill_price=None, exit_fill_qty=None,
                        exit_commission=None, exit_commission_asset=None,
                        exit_status=None, exit_raw=None,
                        pnl=0, pnl_pct=0, total_fees=0):
    """Close a LIVE position with real Binance exit data."""
    with get_engine().begin() as c:
        c.execute(text("""
            UPDATE positions SET
                status='CLOSED', exit_price=:ep, exit_time=:et, exit_reason=:er,
                exit_order_id=:eoid, exit_client_oid=:ecoid,
                exit_fill_price=:efp, exit_fill_qty=:efq,
                exit_commission=:ecomm, exit_commission_asset=:eca,
                exit_status=:es, exit_raw=:eraw,
                pnl=:pnl, pnl_pct=:pp, total_fees=:tf
            WHERE id=:id
        """), {"ep":exit_price, "et":exit_time, "er":exit_reason,
               "eoid":exit_order_id, "ecoid":exit_client_oid,
               "efp":exit_fill_price, "efq":exit_fill_qty,
               "ecomm":exit_commission, "eca":exit_commission_asset,
               "es":exit_status,
               "eraw":json.dumps(exit_raw, default=str) if exit_raw else None,
               "pnl":pnl, "pp":pnl_pct, "tf":total_fees, "id":position_id})


# ═══════════════════════════════════════
# POSITIONS - BACKTEST (no Binance data)
# ═══════════════════════════════════════
def open_position_bt(run_id, signal_id, symbol, direction, strategy, regime,
                     entry_price, entry_time, quantity, entry_fee,
                     stop_loss, take_profit, risk_reward):
    with get_engine().begin() as c:
        r = c.execute(text("""
            INSERT INTO positions (source,run_id,signal_id,symbol,direction,strategy,regime,status,
                entry_price,entry_time,quantity,stop_loss,take_profit,risk_reward,total_fees)
            VALUES('BACKTEST',:rid,:sid,:sym,:dir,:strat,:reg,'CLOSED',
                :ep,:et,:qty,:sl,:tp,:rr,:ef)
        """), {"rid":run_id,"sid":signal_id,"sym":symbol,"dir":direction,
               "strat":strategy,"reg":regime,"ep":entry_price,"et":entry_time,
               "qty":quantity,"sl":stop_loss,"tp":take_profit,"rr":risk_reward,"ef":entry_fee})
        return r.lastrowid


def close_position_bt(position_id, exit_price, exit_time, exit_reason,
                      pnl, pnl_pct, total_fees):
    with get_engine().begin() as c:
        c.execute(text("""
            UPDATE positions SET exit_price=:ep,exit_time=:et,exit_reason=:er,
                pnl=:pnl,pnl_pct=:pp,total_fees=:tf WHERE id=:id
        """), {"ep":exit_price,"et":exit_time,"er":exit_reason,
               "pnl":pnl,"pp":pnl_pct,"tf":total_fees,"id":position_id})


# ═══════════════════════════════════════
# QUERIES (dashboard)
# ═══════════════════════════════════════
def get_open_positions(source="LIVE"):
    return pd.read_sql(text(
        "SELECT * FROM positions WHERE status='OPEN' AND source=:s ORDER BY entry_time DESC"
    ), get_engine(), params={"s":source})


def get_closed_trades(source="LIVE", limit=100):
    return pd.read_sql(text(
        "SELECT * FROM positions WHERE status='CLOSED' AND source=:s ORDER BY exit_time DESC LIMIT :lim"
    ), get_engine(), params={"s":source,"lim":limit})


def get_recent_trades(limit=200, source="LIVE"):
    """Fetch recent closed trades for ML filter training.
    Returns DataFrame with columns: entry_time, direction, regime, confidence, risk_reward, pnl
    """
    try:
        return pd.read_sql(text(
            """SELECT entry_time, direction, strategy, regime, confidence, risk_reward, pnl
               FROM positions
               WHERE status='CLOSED' AND source=:s
               ORDER BY exit_time DESC LIMIT :lim"""
        ), get_engine(), params={"s": source, "lim": limit})
    except Exception as e:
        print(f"⚠️ get_recent_trades error: {e}")
        # Fallback without confidence column for old schema
        try:
            return pd.read_sql(text(
                """SELECT entry_time, direction, strategy, regime, risk_reward, pnl
                   FROM positions
                   WHERE status='CLOSED' AND source=:s
                   ORDER BY exit_time DESC LIMIT :lim"""
            ), get_engine(), params={"s": source, "lim": limit})
        except Exception:
            return None


# ═══════════════════════════════════════
# EQUITY + BACKTEST RUNS
# ═══════════════════════════════════════
def save_equity_batch(data, source="LIVE", run_id=None):
    with get_engine().begin() as c:
        for e in data:
            c.execute(text("""
                INSERT INTO equity_curve (source,run_id,timestamp,equity,capital,unrealized,
                    open_positions,drawdown_pct,peak_equity)
                VALUES(:src,:rid,:ts,:eq,:cap,:ur,:op,:dd,:pe)
            """), {"src":source,"rid":run_id,"ts":e['timestamp'],"eq":e['equity'],
                   "cap":e['capital'],"ur":e.get('unrealized',0),
                   "op":e.get('open_positions',0),"dd":e.get('drawdown_pct',0),
                   "pe":e.get('peak_equity',e['equity'])})


def save_backtest_run(results, config):
    t = results.get('trading',{})
    with get_engine().begin() as c:
        r = c.execute(text("""
            INSERT INTO backtest_runs (run_name,symbol,timeframe,initial_capital,final_capital,
                total_trades,win_rate,profit_factor,max_drawdown,sharpe_ratio,total_pnl,total_fees,
                config_json,results_json)
            VALUES(:rn,:sym,:tf,:ic,:fc,:tt,:wr,:pf,:md,:sr,:tp,:tfe,:cj,:rj)
        """), {"rn":f"BT_{datetime.now().strftime('%Y%m%d_%H%M')}",
               "sym":results.get('data',{}).get('symbol',''),
               "tf":results.get('data',{}).get('timeframe',''),
               "ic":config.get('initial_capital',10000),
               "fc":t.get('final_capital',0),"tt":t.get('total_trades',0),
               "wr":float(str(t.get('win_rate','0')).replace('%','')),
               "pf":t.get('profit_factor',0),
               "md":float(str(t.get('max_drawdown','0')).replace('%','')),
               "sr":t.get('sharpe_approx',0),"tp":t.get('total_pnl',0),
               "tfe":t.get('total_fees_paid',0),
               "cj":json.dumps(config,default=str),
               "rj":json.dumps(results,default=str)})
        return r.lastrowid


def save_regimes(regimes_df, symbol, timeframe):
    with get_engine().begin() as c:
        for idx, row in regimes_df.iterrows():
            c.execute(text("""
                INSERT INTO regimes (symbol,timeframe,timestamp,regime,regime_name,confidence,
                    prob_trending,prob_ranging,prob_volatile)
                VALUES(:s,:tf,:ts,:r,:rn,:conf,:pt,:pr,:pv)
                ON DUPLICATE KEY UPDATE regime=:r,regime_name=:rn,confidence=:conf
            """), {"s":symbol,"tf":timeframe,"ts":idx,
                   "r":int(row.get('regime',0)),"rn":str(row.get('regime_name','')),
                   "conf":float(row.get('confidence',0)),
                   "pt":float(row.get('prob_trending',0)),
                   "pr":float(row.get('prob_ranging',0)),
                   "pv":float(row.get('prob_volatile',0))})


def save_funding_rate(symbol: str, timestamp, rate: float, mark_price: float = 0):
    """Save funding rate to DB for audit."""
    try:
        with get_engine().begin() as c:
            c.execute(text(
                """INSERT INTO funding_rates (symbol, timestamp, funding_rate, mark_price)
                   VALUES (:s, :ts, :r, :mp)
                   ON DUPLICATE KEY UPDATE funding_rate=VALUES(funding_rate)"""),
                {"s": symbol, "ts": timestamp, "r": rate, "mp": mark_price}
            )
    except Exception as e:
        print(f"⚠️ Save funding rate error: {e}")
