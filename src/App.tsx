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
          <stop offset="0%" stopColor="#19fb9b" />
          <stop offset="100%" stopColor="#f0b90b" />
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
    <main className="dashboard-shell">
      <div className="background-grid" />
      <header className="hero">
        <div>
          <p className="eyebrow">TradingClaw Read-Only Terminal</p>
          <h1>BNB Futures Dashboard</h1>
          <p className="hero-copy">Live Binance Futures data for monitoring BNBUSDT without any trade actions.</p>
        </div>
        <div className="status-panel">
          <span className={state.error ? "status-dot error" : "status-dot"} />
          <div>
            <strong>{state.error ? "API Warning" : "Live Feed"}</strong>
            <small>{data ? `Updated ${new Date(data.updatedAt).toLocaleTimeString()}` : "Connecting..."}</small>
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
          <code>.env.local</code> to view your read-only position.
        </div>
      ) : null}

      <section className="market-grid">
        <MetricCard
          label="BNBUSDT Last Price"
          value={formatUsd(data?.market.ticker.lastPrice, 3)}
          subValue="Binance USD-M Futures"
          tone={priceChange >= 0 ? "positive" : "negative"}
        />
        <MetricCard
          label="24h Change"
          value={formatPercent(data?.market.ticker.priceChangePercent)}
          subValue={`${formatUsd(data?.market.ticker.highPrice)} high / ${formatUsd(data?.market.ticker.lowPrice)} low`}
          tone={priceChange >= 0 ? "positive" : "negative"}
        />
        <MetricCard
          label="Mark / Index"
          value={formatUsd(data?.market.premiumIndex.markPrice, 3)}
          subValue={`${formatUsd(data?.market.premiumIndex.indexPrice, 3)} index`}
        />
        <MetricCard
          label="Open Interest"
          value={`${formatNumber(data?.market.openInterest.openInterest, 2)} BNB`}
          subValue={`${formatUsd(data?.market.ticker.quoteVolume, 0)} 24h quote volume`}
        />
      </section>

      <section className="workspace-grid">
        <article className="chart-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">5m Candles</p>
              <h2>BNB Momentum</h2>
            </div>
            <div className="funding-pill">
              Funding {formatPercent(Number(data?.market.premiumIndex.lastFundingRate ?? 0) * 100, 4)}
              <span>Next {nextFunding}</span>
            </div>
          </div>
          {data ? <Sparkline klines={data.market.klines} /> : <div className="chart-skeleton">Loading chart...</div>}
        </article>

        <article className="position-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Private Read-Only</p>
              <h2>Current Position</h2>
            </div>
            <span className={`side-pill ${positionAmount >= 0 ? "long" : "short"}`}>
              {hasPosition ? (positionAmount > 0 ? "Long" : "Short") : "No Position"}
            </span>
          </div>

          <div className="position-size">
            <span>Position Size</span>
            <strong>{hasPosition ? `${formatNumber(Math.abs(positionAmount), 4)} BNB` : "--"}</strong>
          </div>

          <div className="position-details">
            <div>
              <span>Entry</span>
              <strong>{formatUsd(position?.entryPrice, 3)}</strong>
            </div>
            <div>
              <span>Mark</span>
              <strong>{formatUsd(position?.markPrice ?? data?.market.premiumIndex.markPrice, 3)}</strong>
            </div>
            <div>
              <span>Unrealized PnL</span>
              <strong className={pnl >= 0 ? "positive-text" : "negative-text"}>{formatUsd(pnl, 2)}</strong>
            </div>
            <div>
              <span>Liquidation</span>
              <strong>{hasPosition ? formatUsd(position?.liquidationPrice, 3) : "--"}</strong>
            </div>
            <div>
              <span>Leverage</span>
              <strong>{position?.leverage ? `${position.leverage}x` : "--"}</strong>
            </div>
            <div>
              <span>Margin</span>
              <strong>{position?.marginType ?? "--"}</strong>
            </div>
          </div>
        </article>
      </section>

      <section className="account-strip">
        <MetricCard label="Wallet Balance" value={formatUsd(data?.private.account?.totalWalletBalance)} />
        <MetricCard label="Account PnL" value={formatUsd(data?.private.account?.totalUnrealizedProfit)} tone={pnl >= 0 ? "positive" : "negative"} />
        <MetricCard label="Margin Balance" value={formatUsd(data?.private.account?.totalMarginBalance)} />
        <MetricCard label="Maint Margin" value={formatUsd(data?.private.account?.totalMaintMargin)} />
        <MetricCard label="Available Balance" value={formatUsd(data?.private.account?.availableBalance)} />
      </section>

      <section className="data-grid">
        <article className="table-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">All Futures Positions</p>
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

        <article className="table-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Account Assets</p>
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
