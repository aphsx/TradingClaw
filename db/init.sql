CREATE DATABASE IF NOT EXISTS regime_trader;
USE regime_trader;

-- ─── Market Data ───
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
    num_trades INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_candle (symbol, timeframe, timestamp),
    INDEX idx_sym_tf_ts (symbol, timeframe, timestamp)
) ENGINE=InnoDB;

-- ─── Regime Log ───
CREATE TABLE IF NOT EXISTS regimes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    timestamp DATETIME NOT NULL,
    regime TINYINT NOT NULL,
    regime_name VARCHAR(20) NOT NULL,
    confidence DECIMAL(5,4),
    prob_trending DECIMAL(5,4),
    prob_ranging DECIMAL(5,4),
    prob_volatile DECIMAL(5,4),
    adx DECIMAL(10,4),
    atr_pct DECIMAL(10,4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_regime (symbol, timeframe, timestamp)
) ENGINE=InnoDB;

-- ─── Signals (source-tagged) ───
CREATE TABLE IF NOT EXISTS signals (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source ENUM('BACKTEST','LIVE','PAPER') NOT NULL,
    run_id BIGINT NULL COMMENT 'backtest_runs.id when source=BACKTEST',
    symbol VARCHAR(20) NOT NULL,
    timestamp DATETIME NOT NULL,
    direction VARCHAR(10) NOT NULL,
    strategy VARCHAR(50) NOT NULL,
    regime TINYINT NOT NULL,
    entry_price DECIMAL(20,8) NOT NULL,
    stop_loss DECIMAL(20,8) NOT NULL,
    take_profit DECIMAL(20,8) NOT NULL,
    atr DECIMAL(20,8),
    confidence DECIMAL(5,4),
    expected_profit_pct DECIMAL(10,4),
    fee_filtered BOOLEAN DEFAULT FALSE,
    executed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sig_src (source, timestamp)
) ENGINE=InnoDB;

-- ─── Positions (with REAL Binance order data) ───
CREATE TABLE IF NOT EXISTS positions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source ENUM('BACKTEST','LIVE','PAPER') NOT NULL,
    run_id BIGINT NULL,
    signal_id BIGINT NULL,
    symbol VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    strategy VARCHAR(50) NOT NULL,
    regime TINYINT NOT NULL,
    status ENUM('OPEN','CLOSED','CANCELLED','ERROR') NOT NULL DEFAULT 'OPEN',

    -- ENTRY
    entry_price DECIMAL(20,8) NOT NULL,
    entry_time DATETIME NOT NULL,
    quantity DECIMAL(20,8) NOT NULL,

    -- Binance entry order (NULL for BACKTEST)
    entry_order_id BIGINT NULL COMMENT 'Binance orderId',
    entry_client_oid VARCHAR(100) NULL COMMENT 'our clientOrderId',
    entry_fill_price DECIMAL(20,8) NULL COMMENT 'actual avg fill',
    entry_fill_qty DECIMAL(20,8) NULL,
    entry_commission DECIMAL(20,8) NULL COMMENT 'fee from Binance',
    entry_commission_asset VARCHAR(20) NULL COMMENT 'BNB/USDT/...',
    entry_status VARCHAR(20) NULL COMMENT 'FILLED/PARTIALLY_FILLED/...',
    entry_raw JSON NULL COMMENT 'full Binance response',

    -- EXIT
    exit_price DECIMAL(20,8) NULL,
    exit_time DATETIME NULL,
    exit_reason VARCHAR(50) NULL,

    -- Binance exit order
    exit_order_id BIGINT NULL,
    exit_client_oid VARCHAR(100) NULL,
    exit_fill_price DECIMAL(20,8) NULL,
    exit_fill_qty DECIMAL(20,8) NULL,
    exit_commission DECIMAL(20,8) NULL,
    exit_commission_asset VARCHAR(20) NULL,
    exit_status VARCHAR(20) NULL,
    exit_raw JSON NULL,

    -- P&L (real from Binance for LIVE, calculated for BACKTEST)
    pnl DECIMAL(20,8) DEFAULT 0,
    pnl_pct DECIMAL(10,4) DEFAULT 0,
    total_fees DECIMAL(20,8) DEFAULT 0,

    -- Risk
    stop_loss DECIMAL(20,8),
    take_profit DECIMAL(20,8),
    risk_reward DECIMAL(10,4),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE SET NULL,
    INDEX idx_pos_src_status (source, status),
    INDEX idx_pos_open (status, symbol),
    INDEX idx_pos_entry (entry_time)
) ENGINE=InnoDB;

-- ─── Equity Curve ───
CREATE TABLE IF NOT EXISTS equity_curve (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source ENUM('BACKTEST','LIVE','PAPER') NOT NULL,
    run_id BIGINT NULL,
    timestamp DATETIME NOT NULL,
    equity DECIMAL(20,8) NOT NULL,
    capital DECIMAL(20,8) NOT NULL,
    unrealized DECIMAL(20,8) DEFAULT 0,
    open_positions INT DEFAULT 0,
    drawdown_pct DECIMAL(10,4) DEFAULT 0,
    peak_equity DECIMAL(20,8),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_eq_src (source, timestamp)
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ─── System Log ───
CREATE TABLE IF NOT EXISTS system_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    level VARCHAR(10) NOT NULL DEFAULT 'INFO',
    component VARCHAR(50),
    message TEXT,
    data JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_log_time (created_at)
) ENGINE=InnoDB;

-- ─── Funding Rates Log ───
CREATE TABLE IF NOT EXISTS funding_rates (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp DATETIME NOT NULL,
    funding_rate DECIMAL(12,8) NOT NULL,
    mark_price DECIMAL(20,8) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_funding (symbol, timestamp),
    INDEX idx_funding_sym_ts (symbol, timestamp)
) ENGINE=InnoDB;

-- ─── Margin Health Log ───
CREATE TABLE IF NOT EXISTS margin_health_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    total_wallet_balance DECIMAL(20,8),
    total_initial_margin DECIMAL(20,8),
    total_maintain_margin DECIMAL(20,8),
    margin_ratio DECIMAL(6,4),
    total_unrealized_pnl DECIMAL(20,8),
    available_balance DECIMAL(20,8),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_margin_ts (timestamp)
) ENGINE=InnoDB;
