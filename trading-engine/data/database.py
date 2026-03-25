"""
Database Module v4 - MySQL operations with backtest run isolation
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


_SCHEMA_ENSURED = False


def _safe_add_column(table: str, column_ddl: str):
    try:
        with get_engine().begin() as c:
            c.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column_ddl}"))
    except Exception:
        pass


def _safe_add_index(table: str, index_name: str, index_ddl: str):
    try:
        with get_engine().begin() as c:
            c.execute(text(f"ALTER TABLE {table} ADD INDEX {index_name} {index_ddl}"))
    except Exception:
        pass


def ensure_extended_schema():
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        return

    # Signals metadata for regime/exit/execution auditing.
    _safe_add_column("signals", "timeframe VARCHAR(10) NULL")
    _safe_add_column("signals", "regime_name VARCHAR(20) NULL")
    _safe_add_column("signals", "market_profile VARCHAR(40) NULL")
    _safe_add_column("signals", "exit_profile VARCHAR(40) NULL")
    _safe_add_column("signals", "execution_profile_json JSON NULL")
    _safe_add_column("signals", "signal_metadata_json JSON NULL")
    _safe_add_column("signals", "entry_status VARCHAR(30) NULL")
    _safe_add_column("signals", "entry_status_detail VARCHAR(100) NULL")
    _safe_add_index("signals", "idx_sig_run_time", "(run_id, timestamp)")

    # Position-level accounting and execution realism.
    _safe_add_column("positions", "timeframe VARCHAR(10) NULL")
    _safe_add_column("positions", "regime_name VARCHAR(20) NULL")
    _safe_add_column("positions", "market_profile VARCHAR(40) NULL")
    _safe_add_column("positions", "exit_profile VARCHAR(40) NULL")
    _safe_add_column("positions", "leverage_used DECIMAL(10,4) NULL")
    _safe_add_column("positions", "gross_pnl DECIMAL(20,8) DEFAULT 0")
    _safe_add_column("positions", "entry_fee DECIMAL(20,8) DEFAULT 0")
    _safe_add_column("positions", "exit_fee DECIMAL(20,8) DEFAULT 0")
    _safe_add_column("positions", "funding_fee DECIMAL(20,8) DEFAULT 0")
    _safe_add_column("positions", "fill_ratio DECIMAL(10,6) DEFAULT 1")
    _safe_add_column("positions", "entry_latency_bars INT DEFAULT 0")
    _safe_add_column("positions", "entry_status_detail VARCHAR(100) NULL")
    _safe_add_column("positions", "exit_reason_detail VARCHAR(255) NULL")
    _safe_add_column("positions", "execution_profile_json JSON NULL")
    _safe_add_column("positions", "fee_details_json JSON NULL")
    _safe_add_column("positions", "trade_metadata_json JSON NULL")
    _safe_add_index("positions", "idx_pos_run_exit", "(run_id, exit_time)")

    # Backtest run lifecycle metadata.
    _safe_add_column("backtest_runs", "status VARCHAR(20) DEFAULT 'RUNNING'")
    _safe_add_column("backtest_runs", "started_at DATETIME NULL")
    _safe_add_column("backtest_runs", "completed_at DATETIME NULL")
    _safe_add_column("backtest_runs", "gross_pnl DECIMAL(20,8) DEFAULT 0")
    _safe_add_column("backtest_runs", "validation_json JSON NULL")

    _SCHEMA_ENSURED = True


def _json_or_none(value):
    if value is None:
        return None
    return json.dumps(value, default=str)


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
    ensure_extended_schema()
    tp2 = getattr(signal, 'take_profit_2', None)
    score = getattr(signal, 'composite_score', None)
    signal_metadata = {
        "regime_group": getattr(signal, "regime_group", ""),
        "exit_profile_reason": getattr(signal, "exit_profile_reason", ""),
        "trail_enabled": bool(getattr(signal, "trail_enabled", False)),
    }
    # Try v5 INSERT with new columns first; fall back if DB schema is old
    try:
        with get_engine().begin() as c:
            r = c.execute(text("""
                INSERT INTO signals (source,run_id,symbol,timestamp,direction,strategy,regime,
                    entry_price,stop_loss,take_profit,take_profit_2,atr,confidence,
                    expected_profit_pct,fee_filtered,composite_score,timeframe,regime_name,
                    market_profile,exit_profile,execution_profile_json,signal_metadata_json,
                    entry_status,entry_status_detail)
                VALUES(:src,:rid,:sym,:ts,:dir,:strat,:reg,:ep,:sl,:tp,:tp2,:atr,:conf,:epp,:ff,:cs,
                    :tf,:rn,:mp,:xp,:epj,:smj,:es,:esd)
            """), {"src":source,"rid":run_id,"sym":symbol,"ts":signal.timestamp,
                   "dir":signal.direction,"strat":signal.strategy,"reg":signal.regime,
                   "ep":signal.entry_price,"sl":signal.stop_loss,"tp":signal.take_profit,
                    "tp2":tp2,"atr":signal.atr,"conf":signal.confidence,
                   "epp":signal.expected_profit_pct,"ff":fee_filtered,"cs":score,
                   "tf":getattr(signal, "timeframe", None),
                   "rn":getattr(signal, "regime_name", None),
                   "mp":getattr(signal, "market_profile", None),
                   "xp":getattr(signal, "exit_profile", None),
                   "epj":_json_or_none(getattr(signal, "execution_profile", None)),
                   "smj":_json_or_none(signal_metadata),
                   "es":"QUEUED","esd":"pending_backtest_entry"})
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


def update_signal_entry_status(signal_id, executed: bool, status: str, detail: str | None = None):
    if not signal_id:
        return
    ensure_extended_schema()
    try:
        with get_engine().begin() as c:
            c.execute(text("""
                UPDATE signals
                SET executed=:ex, entry_status=:st, entry_status_detail=:dt
                WHERE id=:id
            """), {"ex": bool(executed), "st": status, "dt": detail, "id": signal_id})
    except Exception:
        pass


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
    if exit_reason and len(exit_reason) > 50:
        exit_reason = exit_reason[:47] + "..."
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
                     stop_loss, take_profit, risk_reward,
                     entry_order_id=None, entry_client_oid=None,
                     entry_fill_price=None, entry_fill_qty=None,
                     entry_status="FILLED",
                     timeframe=None, regime_name=None, market_profile=None,
                     exit_profile=None, leverage_used=None, fill_ratio=1.0,
                     entry_latency_bars=0, entry_status_detail=None,
                     execution_profile=None, trade_metadata=None):
    ensure_extended_schema()
    with get_engine().begin() as c:
        r = c.execute(text("""
            INSERT INTO positions (source,run_id,signal_id,symbol,direction,strategy,regime,status,
                entry_price,entry_time,quantity,
                entry_order_id,entry_client_oid,entry_fill_price,entry_fill_qty,entry_status,
                stop_loss,take_profit,risk_reward,total_fees,
                timeframe,regime_name,market_profile,exit_profile,leverage_used,
                entry_fee,fill_ratio,entry_latency_bars,entry_status_detail,
                execution_profile_json,trade_metadata_json)
            VALUES('BACKTEST',:rid,:sid,:sym,:dir,:strat,:reg,'CLOSED',
                :ep,:et,:qty,:eoid,:ecoid,:efp,:efq,:es,:sl,:tp,:rr,:ef,
                :tf,:rn,:mp,:xp,:lev,:enf,:fr,:elb,:esd,:epj,:tmj)
        """), {"rid":run_id,"sid":signal_id,"sym":symbol,"dir":direction,
                "strat":strategy,"reg":regime,"ep":entry_price,"et":entry_time,
               "qty":quantity,"eoid":entry_order_id,"ecoid":entry_client_oid,
               "efp":entry_fill_price if entry_fill_price is not None else entry_price,
               "efq":entry_fill_qty if entry_fill_qty is not None else quantity,
                "es":entry_status,
               "sl":stop_loss,"tp":take_profit,"rr":risk_reward,"ef":entry_fee,
               "tf":timeframe,"rn":regime_name,"mp":market_profile,"xp":exit_profile,
               "lev":leverage_used,"enf":entry_fee,"fr":fill_ratio,
               "elb":entry_latency_bars,"esd":entry_status_detail,
               "epj":_json_or_none(execution_profile),"tmj":_json_or_none(trade_metadata)})
        return r.lastrowid


def close_position_bt(position_id, exit_price, exit_time, exit_reason,
                      pnl, pnl_pct, total_fees,
                      exit_order_id=None, exit_client_oid=None,
                      exit_fill_price=None, exit_fill_qty=None,
                      exit_status="FILLED",
                      gross_pnl=None, exit_fee=None, funding_fee=None,
                      fee_details=None, exit_reason_detail=None, trade_metadata=None):
    ensure_extended_schema()
    with get_engine().begin() as c:
        # Truncate exit_reason to fit DB column (VARCHAR 50)
        if exit_reason and len(exit_reason) > 50:
            exit_reason = exit_reason[:47] + "..."
        c.execute(text("""
            UPDATE positions SET exit_price=:ep,exit_time=:et,exit_reason=:er,
                exit_order_id=:eoid,exit_client_oid=:ecoid,
                exit_fill_price=:efp,exit_fill_qty=:efq,exit_status=:es,
                pnl=:pnl,pnl_pct=:pp,total_fees=:tf,
                gross_pnl=:gp,exit_fee=:xf,funding_fee=:ff,
                fee_details_json=:fdj,exit_reason_detail=:erd,
                trade_metadata_json=:tmj
                WHERE id=:id
        """), {"ep":exit_price,"et":exit_time,"er":exit_reason,
               "eoid":exit_order_id,"ecoid":exit_client_oid,
               "efp":exit_fill_price if exit_fill_price is not None else exit_price,
               "efq":exit_fill_qty, "es":exit_status,
               "pnl":pnl,"pp":pnl_pct,"tf":total_fees,"id":position_id,
               "gp":gross_pnl if gross_pnl is not None else pnl + total_fees,
               "xf":exit_fee if exit_fee is not None else 0,
               "ff":funding_fee if funding_fee is not None else 0,
               "fdj":_json_or_none(fee_details),
               "erd":exit_reason_detail,
               "tmj":_json_or_none(trade_metadata)})


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


def clear_backtest_data():
    """Keep only the newest backtest by clearing all prior backtest artifacts first."""
    ensure_extended_schema()
    with get_engine().begin() as c:
        c.execute(text("DELETE FROM positions WHERE source='BACKTEST'"))
        c.execute(text("DELETE FROM signals WHERE source='BACKTEST'"))
        c.execute(text("DELETE FROM equity_curve WHERE source='BACKTEST'"))
        c.execute(text("DELETE FROM backtest_runs"))


def save_simulated_outcome(symbol: str, direction: str, strategy: str, regime,
                           entry_price: float, entry_time, stop_loss: float,
                           take_profit: float, risk_reward: float, confidence: float,
                           sim_pnl: float, outcome: int,
                           expected_profit_pct: float = 0.0,
                           composite_score: float = 0.0):
    """
    Issue #3 fix — Persist simulated signal outcomes to DB so ML can train on them.

    Simulated outcomes = signals that were NOT executed (rejected by filters) but whose
    SL/TP would have been hit based on subsequent price action (tracked via bar high/low).
    Stored as source='SIMULATED' so they are included in ML training but excluded from
    live PnL accounting.

    The positions table is reused: entry is the signal entry, exit is sim SL or TP,
    pnl is the simulated P&L, status is always 'CLOSED'.
    """
    try:
        with get_engine().begin() as c:
            c.execute(text("""
                INSERT INTO positions
                    (source, symbol, direction, strategy, regime, status,
                     entry_price, entry_time, quantity, stop_loss, take_profit,
                     risk_reward, confidence, pnl, total_fees)
                VALUES
                    ('SIMULATED', :sym, :dir, :strat, :reg, 'CLOSED',
                     :ep, :et, 0.0, :sl, :tp,
                     :rr, :conf, :pnl, 0.0)
            """), {
                "sym": symbol, "dir": direction, "strat": strategy, "reg": str(regime),
                "ep": entry_price, "et": entry_time,
                "sl": stop_loss, "tp": take_profit,
                "rr": risk_reward, "conf": confidence, "pnl": sim_pnl,
            })
    except Exception as e:
        # Gracefully ignore if schema doesn't support all fields
        try:
            with get_engine().begin() as c:
                c.execute(text("""
                    INSERT INTO positions
                        (source, symbol, direction, strategy, regime, status,
                         entry_price, entry_time, quantity, stop_loss, take_profit, pnl)
                    VALUES
                        ('SIMULATED', :sym, :dir, :strat, :reg, 'CLOSED',
                         :ep, :et, 0.0, :sl, :tp, :pnl)
                """), {
                    "sym": symbol, "dir": direction, "strat": strategy or "SIMULATED",
                    "reg": str(regime), "ep": entry_price, "et": entry_time,
                    "sl": stop_loss, "tp": take_profit, "pnl": sim_pnl,
                })
        except Exception:
            pass  # Never block main loop for simulated outcome save failures


def get_recent_trades(limit=200, source="LIVE"):
    """
    Fetch recent closed trades for ML filter training.
    Returns DataFrame with columns: entry_time, direction, regime, confidence, risk_reward, pnl.

    Issue #3 fix: source can now be 'LIVE', 'BACKTEST', or 'SIMULATED'.
    Pass source='ALL' to include all three (used for ML training when live data is sparse).
    """
    try:
        if source == "ALL":
            query = """SELECT entry_time, symbol, direction, strategy, regime, confidence,
                              risk_reward, pnl
                       FROM positions
                       WHERE status='CLOSED' AND source IN ('LIVE','BACKTEST','SIMULATED')
                       ORDER BY exit_time DESC LIMIT :lim"""
            params = {"lim": limit}
        else:
            query = """SELECT entry_time, symbol, direction, strategy, regime, confidence,
                              risk_reward, pnl
                       FROM positions
                       WHERE status='CLOSED' AND source=:s
                       ORDER BY exit_time DESC LIMIT :lim"""
            params = {"s": source, "lim": limit}

        return pd.read_sql(text(query), get_engine(), params=params)

    except Exception as e:
        print(f"[WARN] get_recent_trades error: {e}")
        # Fallback without confidence column for old schema
        try:
            if source == "ALL":
                query = """SELECT entry_time, symbol, direction, strategy, regime, risk_reward, pnl
                           FROM positions
                           WHERE status='CLOSED' AND source IN ('LIVE','BACKTEST','SIMULATED')
                           ORDER BY exit_time DESC LIMIT :lim"""
                params = {"lim": limit}
            else:
                query = """SELECT entry_time, symbol, direction, strategy, regime, risk_reward, pnl
                           FROM positions
                           WHERE status='CLOSED' AND source=:s
                           ORDER BY exit_time DESC LIMIT :lim"""
                params = {"s": source, "lim": limit}
            return pd.read_sql(text(query), get_engine(), params=params)
        except Exception:
            return None


# ═══════════════════════════════════════
# EQUITY + BACKTEST RUNS
# ═══════════════════════════════════════
def save_equity_batch(data, source="LIVE", run_id=None):
    ensure_extended_schema()
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


def create_backtest_run(symbol: str, timeframe: str, initial_capital: float, config: dict):
    ensure_extended_schema()
    with get_engine().begin() as c:
        r = c.execute(text("""
            INSERT INTO backtest_runs (
                run_name,symbol,timeframe,start_date,end_date,initial_capital,
                config_json,results_json,status,started_at
            ) VALUES (
                :rn,:sym,:tf,:sd,:ed,:ic,:cj,:rj,'RUNNING',:st
            )
        """), {
            "rn": f"BT_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "sym": symbol,
            "tf": timeframe,
            "sd": config.get("start_date"),
            "ed": config.get("end_date"),
            "ic": initial_capital,
            "cj": _json_or_none(config),
            "rj": _json_or_none({"status": "RUNNING"}),
            "st": datetime.utcnow(),
        })
        return r.lastrowid


def save_backtest_run(results, config, run_id=None):
    ensure_extended_schema()
    t = results.get('trading',{})
    gross_pnl = t.get('gross_pnl_before_fees', t.get('total_pnl', 0) + t.get('total_fees_paid', 0))
    payload = {"sym":results.get('data',{}).get('symbol',''),
               "tf":results.get('data',{}).get('timeframe',''),
               "ic":config.get('initial_capital',10000),
               "fc":t.get('final_capital',0),"tt":t.get('total_trades',0),
               "wr":float(str(t.get('win_rate','0')).replace('%','')),
               "pf":t.get('profit_factor',0),
               "md":float(str(t.get('max_drawdown','0')).replace('%','')),
               "sr":t.get('sharpe_ratio', t.get('sharpe_approx',0)),
               "tp":t.get('total_pnl',0),
               "gp":gross_pnl,
               "tfe":t.get('total_fees_paid',0),
               "cj":_json_or_none(config),
               "rj":_json_or_none(results),
               "vj":_json_or_none(results.get("validation", {})),
               "sd":results.get('data',{}).get('test_period_start'),
               "ed":results.get('data',{}).get('test_period_end'),
               "done":datetime.utcnow()}
    with get_engine().begin() as c:
        if run_id:
            c.execute(text("""
                UPDATE backtest_runs
                SET symbol=:sym,timeframe=:tf,start_date=:sd,end_date=:ed,
                    initial_capital=:ic,final_capital=:fc,total_trades=:tt,win_rate=:wr,
                    profit_factor=:pf,max_drawdown=:md,sharpe_ratio=:sr,total_pnl=:tp,
                    gross_pnl=:gp,total_fees=:tfe,config_json=:cj,results_json=:rj,
                    validation_json=:vj,status='COMPLETED',completed_at=:done
                WHERE id=:id
            """), {**payload, "id": run_id})
            return run_id
        r = c.execute(text("""
            INSERT INTO backtest_runs (run_name,symbol,timeframe,initial_capital,final_capital,
                total_trades,win_rate,profit_factor,max_drawdown,sharpe_ratio,total_pnl,gross_pnl,total_fees,
                config_json,results_json,validation_json,status,started_at,completed_at,start_date,end_date)
            VALUES(:rn,:sym,:tf,:ic,:fc,:tt,:wr,:pf,:md,:sr,:tp,:gp,:tfe,:cj,:rj,:vj,
                'COMPLETED',:done,:done,:sd,:ed)
        """), {"rn":f"BT_{datetime.now().strftime('%Y%m%d_%H%M')}", **payload})
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
        print(f"[WARN] Save funding rate error: {e}")
