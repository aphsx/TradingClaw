import { useEffect, useMemo, useState } from "react";

type Kline = [
  number,
  string,
  string,
  string,
  string,
  string,
  number,
  string,
  number,
  string,
  string,
  string
];

type DashboardData = {
  symbol: string;
  updatedAt: string;
  market: {
    ticker: {
      lastPrice: string;
      priceChangePercent: string;
      highPrice: string;
      lowPrice: string;
      volume: string;
      quoteVolume: string;
    };
    premiumIndex: {
      markPrice: string;
      indexPrice: string;
      lastFundingRate: string;
      nextFundingTime: number;
    };
    openInterest: {
      openInterest: string;
    };
    klines: Kline[];
  };
  private: {
    configured: boolean;
    position: PositionRisk | null;
    positions: PositionRisk[];
    activePositions: PositionRisk[];
    account: null | {
      totalWalletBalance?: string;
      totalUnrealizedProfit?: string;
      availableBalance?: string;
      totalMarginBalance?: string;
      totalMaintMargin?: string;
      assets?: AccountAsset[];
    };
  };
};

type PositionRisk = {
  symbol: string;
  positionAmt: string;
  entryPrice: string;
  markPrice: string;
  unRealizedProfit: string;
  liquidationPrice: string;
  leverage: string;
  marginType: string;
  notional: string;
  updateTime: number;
};

type AccountAsset = {
  asset: string;
  walletBalance: string;
  unrealizedProfit: string;
  marginBalance: string;
  availableBalance: string;
};

type LoadState = {
  data: DashboardData | null;
  error: string | null;
  loading: boolean;
};

const formatUsd = (value: string | number | undefined, maximumFractionDigits = 2) => {
  const number = Number(value ?? 0);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits
  }).format(Number.isFinite(number) ? number : 0);
};

const formatNumber = (value: string | number | undefined, maximumFractionDigits = 2) => {
  const number = Number(value ?? 0);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits }).format(Number.isFinite(number) ? number : 0);
};

const formatPercent = (value: string | number | undefined, fractionDigits = 2) => {
  const number = Number(value ?? 0);
  return `${number >= 0 ? "+" : ""}${number.toFixed(fractionDigits)}%`;
};

function Sparkline({ klines }: { klines: Kline[] }) {
  const points = useMemo(() => {
    const closes = klines.map((kline) => Number(kline[4])).filter(Number.isFinite);
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const range = max - min || 1;

    return closes
      .map((close, index) => {
        const x = (index / Math.max(closes.length - 1, 1)) * 100;
        const y = 100 - ((close - min) / range) * 100;
        return `${x},${y}`;
      })
      .join(" ");
  }, [klines]);

  return (
    <svg className="sparkline" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="BNB price chart">
      <defs>
        <linearGradient id="chartGlow" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="#2563eb" />
          <stop offset="52%" stopColor="#7c3aed" />
          <stop offset="100%" stopColor="#06b6d4" />
        </linearGradient>
      </defs>
      <polyline points={points} fill="none" stroke="url(#chartGlow)" strokeLinecap="round" strokeWidth="3" />
    </svg>
  );
}

function MetricCard({
  label,
  value,
  subValue,
  tone = "neutral"
}: {
  label: string;
  value: string;
  subValue?: string;
  tone?: "positive" | "negative" | "neutral";
}) {
  return (
    <section className={`metric-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {subValue ? <small>{subValue}</small> : null}
    </section>
  );
}

export function App() {
  const [state, setState] = useState<LoadState>({ data: null, error: null, loading: true });

  async function loadDashboard() {
    setState((current) => ({ ...current, loading: true, error: null }));

    try {
      const response = await fetch("/api/binance/bnb-dashboard");
      const payload = await response.json();

      if (!response.ok) {
        throw new Error(payload.error || "Unable to load dashboard");
      }

      setState({ data: payload, error: null, loading: false });
    } catch (error) {
      setState((current) => ({
        data: current.data,
        error: error instanceof Error ? error.message : "Unable to load dashboard",
        loading: false
      }));
    }
  }

  useEffect(() => {
    loadDashboard();
    const timer = window.setInterval(loadDashboard, 10_000);
    return () => window.clearInterval(timer);
  }, []);

  const data = state.data;
  const position = data?.private.position;
  const positionAmount = Number(position?.positionAmt ?? 0);
  const hasPosition = Boolean(position && positionAmount !== 0);
  const pnl = Number(position?.unRealizedProfit ?? 0);
  const priceChange = Number(data?.market.ticker.priceChangePercent ?? 0);
  const activePositions = data?.private.activePositions ?? [];
  const accountAssets =
    data?.private.account?.assets?.filter((asset) => Number(asset.walletBalance) !== 0 || Number(asset.marginBalance) !== 0) ?? [];
  const nextFunding = data?.market.premiumIndex.nextFundingTime
    ? new Date(data.market.premiumIndex.nextFundingTime).toLocaleTimeString()
    : "-";

  return (
    <main className="terminal-shell">
      <div className="background-grid" />

      <header className="terminal-topbar">
        <div className="brand-lockup">
          <span className="brand-mark">TC</span>
          <div>
            <p>TradingClaw</p>
            <strong>BNB Perpetual Monitor</strong>
          </div>
        </div>
        <div className="session-controls">
          <div className="feed-status">
            <span className={state.error ? "status-dot error" : "status-dot"} />
            <div>
              <strong>{state.error ? "Feed Issue" : "Live Read-Only"}</strong>
              <small>{data ? new Date(data.updatedAt).toLocaleTimeString() : "Connecting..."}</small>
            </div>
          </div>
          <button type="button" onClick={loadDashboard} disabled={state.loading}>
            {state.loading ? "Syncing" : "Refresh"}
          </button>
        </div>
      </header>

      {state.error ? <div className="alert">Binance API: {state.error}</div> : null}
      {data && !data.private.configured ? (
        <div className="notice">
          Public market data is live. Add <code>BINANCE_API_KEY</code> and <code>BINANCE_API_SECRET</code> in{" "}
          <code>.env.local</code> to view your read-only account state.
        </div>
      ) : null}

      <section className="price-hero">
        <div className="symbol-block">
          <p className="eyebrow">USD-M Futures</p>
          <h1>{data?.symbol ?? "BNBUSDT"}</h1>
          <div className="symbol-meta">
            <span>Binance Futures</span>
            <span>5m refresh chart</span>
            <span>No trade actions</span>
          </div>
        </div>
        <div className="last-price-block">
          <span>Last Price</span>
          <strong className={priceChange >= 0 ? "positive-text" : "negative-text"}>
            {formatUsd(data?.market.ticker.lastPrice, 3)}
          </strong>
          <small className={priceChange >= 0 ? "positive-text" : "negative-text"}>
            {formatPercent(data?.market.ticker.priceChangePercent)} 24h
          </small>
        </div>
        <div className="mini-market-grid">
          <MetricCard label="Mark" value={formatUsd(data?.market.premiumIndex.markPrice, 3)} />
          <MetricCard label="Index" value={formatUsd(data?.market.premiumIndex.indexPrice, 3)} />
          <MetricCard label="24h High" value={formatUsd(data?.market.ticker.highPrice)} />
          <MetricCard label="24h Low" value={formatUsd(data?.market.ticker.lowPrice)} />
        </div>
      </section>

      <section className="cockpit-grid">
        <article className="chart-board">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Market Tape</p>
              <h2>BNB Momentum</h2>
            </div>
            <div className="funding-pill">
              Funding {formatPercent(Number(data?.market.premiumIndex.lastFundingRate ?? 0) * 100, 4)}
              <span>Next {nextFunding}</span>
            </div>
          </div>
          {data ? <Sparkline klines={data.market.klines} /> : <div className="chart-skeleton">Loading chart...</div>}
          <div className="chart-footer">
            <div>
              <span>Open Interest</span>
              <strong>{formatNumber(data?.market.openInterest.openInterest, 2)} BNB</strong>
            </div>
            <div>
              <span>24h Quote Volume</span>
              <strong>{formatUsd(data?.market.ticker.quoteVolume, 0)}</strong>
            </div>
            <div>
              <span>BNB Volume</span>
              <strong>{formatNumber(data?.market.ticker.volume, 2)}</strong>
            </div>
          </div>
        </article>

        <aside className="side-stack">
          <article className="position-card">
            <div className="panel-heading compact">
              <div>
                <p className="eyebrow">BNB Position</p>
                <h2>Exposure</h2>
              </div>
              <span className={`side-pill ${positionAmount >= 0 ? "long" : "short"}`}>
                {hasPosition ? (positionAmount > 0 ? "Long" : "Short") : "Flat"}
              </span>
            </div>

            <div className="position-hero">
              <span>Size</span>
              <strong>{hasPosition ? `${formatNumber(Math.abs(positionAmount), 4)} BNB` : "--"}</strong>
              <small className={pnl >= 0 ? "positive-text" : "negative-text"}>UPnL {formatUsd(pnl, 2)}</small>
            </div>

            <div className="position-stats">
              <div>
                <span>Entry</span>
                <strong>{formatUsd(position?.entryPrice, 3)}</strong>
              </div>
              <div>
                <span>Mark</span>
                <strong>{formatUsd(position?.markPrice ?? data?.market.premiumIndex.markPrice, 3)}</strong>
              </div>
              <div>
                <span>Liquidation</span>
                <strong>{hasPosition ? formatUsd(position?.liquidationPrice, 3) : "--"}</strong>
              </div>
              <div>
                <span>Leverage</span>
                <strong>{position?.leverage ? `${position.leverage}x` : "--"}</strong>
              </div>
            </div>
          </article>

          <article className="risk-card">
            <p className="eyebrow">Account Risk</p>
            <div className="risk-list">
              <div>
                <span>Wallet</span>
                <strong>{formatUsd(data?.private.account?.totalWalletBalance)}</strong>
              </div>
              <div>
                <span>Margin</span>
                <strong>{formatUsd(data?.private.account?.totalMarginBalance)}</strong>
              </div>
              <div>
                <span>Available</span>
                <strong>{formatUsd(data?.private.account?.availableBalance)}</strong>
              </div>
              <div>
                <span>Maint</span>
                <strong>{formatUsd(data?.private.account?.totalMaintMargin)}</strong>
              </div>
            </div>
          </article>
        </aside>
      </section>

      <section className="lower-grid">
        <article className="table-panel positions-table">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Portfolio</p>
              <h2>Open Positions</h2>
            </div>
            <span className="count-pill">{activePositions.length} active</span>
          </div>
          {activePositions.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>Size</th>
                    <th>Entry</th>
                    <th>Mark</th>
                    <th>PnL</th>
                    <th>Lev</th>
                    <th>Liq</th>
                  </tr>
                </thead>
                <tbody>
                  {activePositions.map((item) => {
                    const size = Number(item.positionAmt);
                    const itemPnl = Number(item.unRealizedProfit);

                    return (
                      <tr key={item.symbol}>
                        <td>{item.symbol}</td>
                        <td className={size >= 0 ? "positive-text" : "negative-text"}>{size >= 0 ? "Long" : "Short"}</td>
                        <td>{formatNumber(Math.abs(size), 4)}</td>
                        <td>{formatUsd(item.entryPrice, 4)}</td>
                        <td>{formatUsd(item.markPrice, 4)}</td>
                        <td className={itemPnl >= 0 ? "positive-text" : "negative-text"}>{formatUsd(itemPnl)}</td>
                        <td>{item.leverage}x</td>
                        <td>{formatUsd(item.liquidationPrice, 4)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state">No open futures positions from the read-only account response.</div>
          )}
        </article>

        <article className="asset-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Collateral</p>
              <h2>Balances</h2>
            </div>
            <span className="count-pill">{accountAssets.length} assets</span>
          </div>
          {accountAssets.length ? (
            <div className="asset-list">
              {accountAssets.map((asset) => (
                <div className="asset-row" key={asset.asset}>
                  <strong>{asset.asset}</strong>
                  <span>Wallet {formatNumber(asset.walletBalance, 6)}</span>
                  <span>Margin {formatNumber(asset.marginBalance, 6)}</span>
                  <span>Available {formatNumber(asset.availableBalance, 6)}</span>
                  <span className={Number(asset.unrealizedProfit) >= 0 ? "positive-text" : "negative-text"}>
                    PnL {formatNumber(asset.unrealizedProfit, 6)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state">No non-zero assets found, or private API keys are not loaded yet.</div>
          )}
        </article>
      </section>
    </main>
  );
}
