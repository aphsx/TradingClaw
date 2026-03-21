-- ═══════════════════════════════════════════════════
-- REGIME DETECTION TRADING SYSTEM - DATABASE SCHEMA
-- ═══════════════════════════════════════════════════

CREATE DATABASE IF NOT EXISTS regime_trader;
USE regime_trader;

-- ─── Market Data Cache ───
CREATE TABLE IF NOT EXISTS candles (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    timestamp DATETIME NOT NULL,
    open DECIMAL(20,8) NOT NULL,
    high DECIMAL(20,8) NOT NULL,
    low DECIMAL(20,8) NOT NULL,
    close DECIMAL(20,8) NOT NULL,
    volume DECIMAL(20,8) NOT NULL,
    quote_volume DECIMAL(20,8),
    trades INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_candle (symbol, timeframe, timestamp),
    INDEX idx_symbol_time (symbol, timeframe, timestamp)
) ENGINE=InnoDB;

-- ─── Regime Classification Log ───
CREATE TABLE IF NOT EXISTS regimes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    timestamp DATETIME NOT NULL,
    regime TINYINT NOT NULL COMMENT '0=Trending, 1=Ranging, 2=Volatile',
    regime_name VARCHAR(20) NOT NULL,
    confidence DECIMAL(5,4),
    prob_trending DECIMAL(5,4),
    prob_ranging DECIMAL(5,4),
    prob_volatile DECIMAL(5,4),
    adx DECIMAL(10,4),
    atr_pct DECIMAL(10,4),
    volatility DECIMAL(10,4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_regime (symbol, timeframe, timestamp),
    INDEX idx_regime_time (symbol, timestamp)
) ENGINE=InnoDB;

-- ─── Trading Signals ───
CREATE TABLE IF NOT EXISTS signals (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp DATETIME NOT NULL,
    direction VARCHAR(10) NOT NULL COMMENT 'LONG or SHORT',
    strategy VARCHAR(50) NOT NULL,
    regime TINYINT NOT NULL,
    entry_price DECIMAL(20,8) NOT NULL,
    stop_loss DECIMAL(20,8) NOT NULL,
    take_profit DECIMAL(20,8) NOT NULL,
    atr DECIMAL(20,8),
    confidence DECIMAL(5,4),
    expected_profit_pct DECIMAL(10,4),
    fee_filtered BOOLEAN DEFAULT FALSE COMMENT 'TRUE=passed fee filter',
    executed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_signal_time (symbol, timestamp),
    INDEX idx_signal_exec (executed, fee_filtered)
) ENGINE=InnoDB;

-- ─── Positions (Open + Closed) ───
CREATE TABLE IF NOT EXISTS positions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    signal_id BIGINT,
    symbol VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    strategy VARCHAR(50) NOT NULL,
    regime TINYINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN, CLOSED, CANCELLED',
    
    -- Entry
    entry_price DECIMAL(20,8) NOT NULL,
    entry_time DATETIME NOT NULL,
    quantity DECIMAL(20,8) NOT NULL,
    entry_fee DECIMAL(20,8) DEFAULT 0,
    
    -- Exit (filled when closed)
    exit_price DECIMAL(20,8),
    exit_time DATETIME,
    exit_reason VARCHAR(50) COMMENT 'Take Profit, Stop Loss, Force Close, Manual',
    exit_fee DECIMAL(20,8) DEFAULT 0,
    
    -- P&L
    pnl DECIMAL(20,8) DEFAULT 0,
    pnl_pct DECIMAL(10,4) DEFAULT 0,
    total_fees DECIMAL(20,8) DEFAULT 0,
    
    -- Risk
    stop_loss DECIMAL(20,8),
    take_profit DECIMAL(20,8),
    risk_reward DECIMAL(10,4),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (signal_id) REFERENCES signals(id),
    INDEX idx_pos_status (status, symbol),
    INDEX idx_pos_time (entry_time),
    INDEX idx_pos_strategy (strategy)
) ENGINE=InnoDB;

-- ─── Equity Curve ───
CREATE TABLE IF NOT EXISTS equity_curve (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    equity DECIMAL(20,8) NOT NULL,
    capital DECIMAL(20,8) NOT NULL,
    unrealized DECIMAL(20,8) DEFAULT 0,
    open_positions INT DEFAULT 0,
    drawdown_pct DECIMAL(10,4) DEFAULT 0,
    peak_equity DECIMAL(20,8),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_eq_time (timestamp)
) ENGINE=InnoDB;

-- ─── Backtest Runs ───
CREATE TABLE IF NOT EXISTS backtest_runs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_name VARCHAR(100),
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    start_date DATETIME,
    end_date DATETIME,
    initial_capital DECIMAL(20,8),
    final_capital DECIMAL(20,8),
    total_trades INT,
    win_rate DECIMAL(5,2),
    profit_factor DECIMAL(10,4),
    max_drawdown DECIMAL(10,4),
    sharpe_ratio DECIMAL(10,4),
    total_pnl DECIMAL(20,8),
    total_fees DECIMAL(20,8),
    config_json JSON,
    results_json JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_run_time (created_at)
) ENGINE=InnoDB;

-- ─── System Log ───
CREATE TABLE IF NOT EXISTS system_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    level VARCHAR(10) NOT NULL DEFAULT 'INFO',
    component VARCHAR(50),
    message TEXT,
    data JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_log_time (created_at),
    INDEX idx_log_level (level)
) ENGINE=InnoDB;
