import { useEffect, useRef, useState } from "react";

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

type DashboardSocketMessage =
  | {
      type: "dashboard";
      payload: DashboardData;
    }
  | {
      type: "error";
      payload: {
        error: string;
      };
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

const frame = "pixel-frame";
const headingCell = "pixel-thead-cell";
const valueCell = "pixel-tcell";

function SummaryCard({
  label,
  value,
  meta,
  tone = "blue"
}: {
  label: string;
  value: string;
  meta?: React.ReactNode;
  tone?: "green" | "red" | "blue" | "purple";
}) {
  const toneClass = {
    green: "text-emerald-300",
    red: "text-rose-300",
    blue: "text-sky-300",
    purple: "text-violet-300"
  }[tone];

  return (
    <article className="pixel-card p-5">
      <div className="flex items-center gap-3">
        <span className="pixel-token grid size-7 place-items-center">$</span>
        <span className="pixel-label">{label}</span>
      </div>
      <strong className={`pixel-metric pixel-number mt-5 block ${toneClass}`}>{value}</strong>
      {meta ? <small className="pixel-meta mt-3 block">{meta}</small> : null}
    </article>
  );
}

function SectionFrame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className={frame}>
      <div className="pixel-frame-head px-4 py-3">
        <h2 className="pixel-section-title">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function DetailTile({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "green" | "red" | "blue" | "neutral" }) {
  const toneClass = {
    green: "text-emerald-300",
    red: "text-rose-300",
    blue: "text-sky-300",
    neutral: "text-neutral-100"
  }[tone];

  return (
    <div className="pixel-tile p-4">
      <span className="pixel-label-muted">{label}</span>
      <strong className={`pixel-value pixel-number mt-3 block ${toneClass}`}>{value}</strong>
    </div>
  );
}

function CandleChart({
  symbol,
  klines,
  lastPrice,
  position
}: {
  symbol: string;
  klines: Kline[];
  lastPrice?: string;
  position?: PositionRisk | null;
}) {
  const candles = klines.map((kline) => ({
    time: kline[0],
    open: Number(kline[1]),
    high: Number(kline[2]),
    low: Number(kline[3]),
    close: Number(kline[4]),
    volume: Number(kline[5])
  })).filter((candle) => [candle.open, candle.high, candle.low, candle.close, candle.volume].every(Number.isFinite));

  if (!candles.length) {
    return <div className="p-8 text-center text-sm font-bold text-neutral-500">Waiting for chart data.</div>;
  }

  const width = 1160;
  const height = 430;
  const pad = { top: 28, right: 86, bottom: 58, left: 28 };
  const chartHeight = 282;
  const volumeTop = pad.top + chartHeight + 22;
  const volumeHeight = height - volumeTop - pad.bottom;
  const plotWidth = width - pad.left - pad.right;
  const entryPrice = Number(position?.entryPrice);
  const liquidationPrice = Number(position?.liquidationPrice);
  const entryMarker = Number.isFinite(entryPrice) && entryPrice > 0 ? entryPrice : null;
  const liquidationMarker = Number.isFinite(liquidationPrice) && liquidationPrice > 0 ? liquidationPrice : null;
  const markerPrices = [entryMarker, liquidationMarker].filter((price): price is number => price !== null);
  const minLow = Math.min(...candles.map((candle) => candle.low), ...markerPrices);
  const maxHigh = Math.max(...candles.map((candle) => candle.high), ...markerPrices);
  const pricePadding = Math.max((maxHigh - minLow) * 0.08, maxHigh * 0.001);
  const minPrice = minLow - pricePadding;
  const maxPrice = maxHigh + pricePadding;
  const priceRange = Math.max(maxPrice - minPrice, 1);
  const maxVolume = Math.max(...candles.map((candle) => candle.volume), 1);
  const candleSlot = plotWidth / candles.length;
  const candleWidth = Math.max(Math.min(candleSlot * 0.58, 14), 4);
  const yForPrice = (price: number) => pad.top + ((maxPrice - price) / priceRange) * chartHeight;
  const xForIndex = (index: number) => pad.left + candleSlot * index + candleSlot / 2;
  const priceTicks = Array.from({ length: 5 }, (_, index) => minPrice + (priceRange / 4) * index).reverse();
  const timeTicks = candles.filter((_, index) => index % Math.max(Math.floor(candles.length / 6), 1) === 0);
  const latest = candles[candles.length - 1];
  const latestPrice = Number(lastPrice ?? latest?.close ?? 0);
  const latestY = yForPrice(Number.isFinite(latestPrice) ? latestPrice : latest?.close ?? 0);
  const firstClose = candles[0]?.close ?? 0;
  const change = latest ? ((latest.close - firstClose) / firstClose) * 100 : 0;
  const isUp = latest ? latest.close >= firstClose : true;
  const markerLine = (price: number, label: string, className: string) => {
    const y = yForPrice(price);

    return (
      <g key={label}>
        <line className={className} x1={pad.left} x2={width - pad.right} y1={y} y2={y} />
        <text className={`${className}-label`} x={width - pad.right + 12} y={y + 4}>
          {label} {formatNumber(price, 4)}
        </text>
      </g>
    );
  };

  return (
    <div className="p-4">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="pixel-label-muted">{symbol} Perpetual / 5m</p>
          <strong className={`pixel-chart-price pixel-number mt-2 block ${isUp ? "text-emerald-300" : "text-rose-300"}`}>
            {formatUsd(latest?.close, 4)}
          </strong>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="pixel-chip px-3 py-2">O {formatUsd(latest?.open, 4)}</span>
          <span className="pixel-chip px-3 py-2">H {formatUsd(latest?.high, 4)}</span>
          <span className="pixel-chip px-3 py-2">L {formatUsd(latest?.low, 4)}</span>
          <span className={`pixel-chip px-3 py-2 ${isUp ? "text-emerald-300" : "text-rose-300"}`}>
            {change >= 0 ? "+" : ""}{formatNumber(change, 2)}%
          </span>
        </div>
      </div>

      <div className="pixel-chart-wrap">
        <svg className="pixel-chart" role="img" aria-label={`${symbol} candlestick chart`} viewBox={`0 0 ${width} ${height}`}>
          <defs>
            <linearGradient id="chartGlow" x1="0" x2="1" y1="0" y2="1">
              <stop offset="0%" stopColor="#6bff6b" stopOpacity="0.2" />
              <stop offset="100%" stopColor="#38bdf8" stopOpacity="0" />
            </linearGradient>
          </defs>
          <rect x={pad.left} y={pad.top} width={plotWidth} height={chartHeight} fill="url(#chartGlow)" opacity="0.65" />
          {priceTicks.map((tick) => {
            const y = yForPrice(tick);

            return (
              <g key={tick}>
                <line className="pixel-chart-grid" x1={pad.left} x2={width - pad.right} y1={y} y2={y} />
                <text className="pixel-chart-label" x={width - pad.right + 12} y={y + 4}>{formatNumber(tick, 2)}</text>
              </g>
            );
          })}
          {timeTicks.map((tick) => {
            const index = candles.indexOf(tick);
            const x = xForIndex(index);

            return (
              <g key={tick.time}>
                <line className="pixel-chart-grid-faint" x1={x} x2={x} y1={pad.top} y2={volumeTop + volumeHeight} />
                <text className="pixel-chart-label" textAnchor="middle" x={x} y={height - 24}>
                  {new Date(tick.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </text>
              </g>
            );
          })}
          <line className="pixel-chart-last-line" x1={pad.left} x2={width - pad.right} y1={latestY} y2={latestY} />
          <text className="pixel-chart-last-label" x={width - pad.right + 12} y={latestY + 4}>{formatNumber(latestPrice, 4)}</text>
          {entryMarker ? markerLine(entryMarker, "ENTRY", "pixel-chart-entry-line") : null}
          {liquidationMarker ? markerLine(liquidationMarker, "LIQ", "pixel-chart-liquidation-line") : null}
          {candles.map((candle, index) => {
            const x = xForIndex(index);
            const openY = yForPrice(candle.open);
            const closeY = yForPrice(candle.close);
            const highY = yForPrice(candle.high);
            const lowY = yForPrice(candle.low);
            const candleTop = Math.min(openY, closeY);
            const candleHeight = Math.max(Math.abs(closeY - openY), 2);
            const volumeBarHeight = Math.max((candle.volume / maxVolume) * volumeHeight, 2);
            const up = candle.close >= candle.open;

            return (
              <g className={up ? "pixel-candle-up" : "pixel-candle-down"} key={`${candle.time}-${index}`}>
                <line x1={x} x2={x} y1={highY} y2={lowY} />
                <rect x={x - candleWidth / 2} y={candleTop} width={candleWidth} height={candleHeight} />
                <rect
                  className="pixel-volume-bar"
                  x={x - candleWidth / 2}
                  y={volumeTop + volumeHeight - volumeBarHeight}
                  width={candleWidth}
                  height={volumeBarHeight}
                />
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

export function App() {
  const [state, setState] = useState<LoadState>({ data: null, error: null, loading: true });
  const [socketStatus, setSocketStatus] = useState<"connecting" | "live" | "reconnecting" | "offline" | "polling">("connecting");
  const socketRef = useRef<WebSocket | null>(null);

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
    if (!import.meta.env.DEV) {
      setSocketStatus("polling");
      loadDashboard();
      const timer = window.setInterval(loadDashboard, 5000);
      return () => window.clearInterval(timer);
    }

    let reconnectTimer: number | undefined;
    let stopped = false;

    function connect() {
      setSocketStatus(socketRef.current ? "reconnecting" : "connecting");
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(`${protocol}//${window.location.host}/api/binance/bnb-dashboard/socket`);
      socketRef.current = socket;

      socket.onopen = () => {
        setSocketStatus("live");
      };

      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as DashboardSocketMessage;

        if (message.type === "dashboard") {
          setState({ data: message.payload, error: null, loading: false });
          return;
        }

        setState((current) => ({
          data: current.data,
          error: message.payload.error,
          loading: false
        }));
      };

      socket.onerror = () => {
        setSocketStatus("offline");
      };

      socket.onclose = () => {
        if (socketRef.current === socket) {
          socketRef.current = null;
        }

        if (!stopped) {
          setSocketStatus("reconnecting");
          reconnectTimer = window.setTimeout(connect, 2000);
        }
      };
    }

    connect();

    return () => {
      stopped = true;
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
      }
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, []);

  const data = state.data;
  const account = data?.private.account;
  const activePositions = data?.private.activePositions ?? [];
  const losingPositions = activePositions.filter((position) => Number(position.unRealizedProfit) < 0);
  const accountAssets = account?.assets?.filter((asset) => Number(asset.walletBalance) !== 0 || Number(asset.marginBalance) !== 0) ?? [];
  const totalPnl = Number(account?.totalUnrealizedProfit ?? activePositions.reduce((sum, position) => sum + Number(position.unRealizedProfit), 0));
  const totalNotional = activePositions.reduce((sum, position) => sum + Math.abs(Number(position.notional ?? 0)), 0);
  const updatedAt = data ? new Date(data.updatedAt).toLocaleTimeString() : "Connecting";

  function refreshDashboard() {
    setState((current) => ({ ...current, loading: true, error: null }));

    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send("refresh");
      return;
    }

    loadDashboard();
  }

  return (
    <main className="pixel-stage min-h-screen text-neutral-100">
      <div className="pixel-topbar px-4 py-3">
        <div className="mx-auto flex max-w-[1540px] flex-wrap items-center justify-between gap-3">
          <div>
            <p className="pixel-eyebrow">Current Portfolio Dashboard</p>
            <h1 className="pixel-title mt-2">TradingClaw</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="pixel-chip px-3 py-2">
              {state.error ? "Feed issue" : `${socketStatus === "polling" ? "Realtime polling" : `Socket ${socketStatus}`} / ${updatedAt}`}
            </span>
            <span className="pixel-chip px-3 py-2">
              {data?.private.configured ? "Private API loaded" : "Public only"}
            </span>
            <button
              className="pixel-button px-4 py-2 disabled:cursor-wait disabled:opacity-60"
              type="button"
              onClick={refreshDashboard}
              disabled={state.loading}
            >
              {state.loading ? "Syncing" : "Refresh"}
            </button>
          </div>
        </div>
      </div>

      <div className="mx-auto grid max-w-[1540px] gap-5 px-4 py-5 sm:px-6 lg:px-8">
        {state.error ? <div className="pixel-alert pixel-alert-error p-4">Binance API: {state.error}</div> : null}
        {data && !data.private.configured ? (
          <div className="pixel-alert pixel-alert-info p-4 text-sm">
            Add <code>BINANCE_API_KEY</code> and <code>BINANCE_API_SECRET</code> in <code>.env.local</code> to show wallet balance, private positions, and account risk.
          </div>
        ) : null}

        <section className="grid gap-5 md:grid-cols-3">
          <SummaryCard label="Wallet Balance" value={formatUsd(account?.totalWalletBalance)} meta="Current account wallet" tone="green" />
          <SummaryCard
            label="Unrealized PnL"
            value={formatUsd(totalPnl)}
            meta={(
              <span>
                <span className="pixel-number">{losingPositions.length}</span> losing positions
              </span>
            )}
            tone={totalPnl >= 0 ? "green" : "red"}
          />
          <SummaryCard
            label="Active Positions"
            value={String(activePositions.length)}
            meta={(
              <span>
                Exposure <span className="pixel-number">{formatUsd(totalNotional)}</span>
              </span>
            )}
            tone="purple"
          />
        </section>

        <SectionFrame title={data ? `${data.symbol} Futures Chart` : "Futures Chart"}>
          {data ? (
            <CandleChart
              symbol={data.symbol}
              klines={data.market.klines}
              lastPrice={data.market.ticker.lastPrice}
              position={data.private.position}
            />
          ) : (
            <div className="p-8 text-center text-sm font-bold text-neutral-500">Loading BNB chart.</div>
          )}
        </SectionFrame>

        <SectionFrame title="Account Summary">
          <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-6">
            <DetailTile label="Wallet" value={formatUsd(account?.totalWalletBalance)} />
            <DetailTile label="Margin Balance" value={formatUsd(account?.totalMarginBalance)} />
            <DetailTile label="Available" value={formatUsd(account?.availableBalance)} tone="blue" />
            <DetailTile label="Maintenance" value={formatUsd(account?.totalMaintMargin)} tone="red" />
            <DetailTile label="UPnL" value={formatUsd(totalPnl)} tone={totalPnl >= 0 ? "green" : "red"} />
            <DetailTile label="Notional" value={formatUsd(totalNotional)} />
          </div>
        </SectionFrame>

        <SectionFrame title="Active Positions">
          {activePositions.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] border-collapse">
                <thead>
                  <tr className="pixel-thead">
                    {['Symbol', 'Side', 'Size', 'Entry', 'Mark', 'UPnL', 'Notional', 'Leverage', 'Liquidation'].map((heading) => (
                      <th className={headingCell} key={heading}>{heading}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {activePositions.map((item) => {
                    const size = Number(item.positionAmt);
                    const itemPnl = Number(item.unRealizedProfit);

                    return (
                      <tr className="pixel-trow" key={item.symbol}>
                        <td className={valueCell}>{item.symbol}</td>
                        <td className={`${valueCell} ${size > 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{size > 0 ? 'Long' : 'Short'}</td>
                        <td className={`${valueCell} pixel-number`}>{formatNumber(Math.abs(size), 4)}</td>
                        <td className={`${valueCell} pixel-number`}>{formatUsd(item.entryPrice, 4)}</td>
                        <td className={`${valueCell} pixel-number`}>{formatUsd(item.markPrice, 4)}</td>
                        <td className={`${valueCell} pixel-number ${itemPnl >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{formatUsd(itemPnl)}</td>
                        <td className={`${valueCell} pixel-number`}>{formatUsd(item.notional)}</td>
                        <td className={`${valueCell} pixel-number`}>{item.leverage ? `${item.leverage}x` : '--'}</td>
                        <td className={`${valueCell} pixel-number`}>{formatUsd(item.liquidationPrice, 4)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="p-6 text-center text-sm font-bold text-neutral-500">No active positions right now.</div>
          )}
        </SectionFrame>

        <SectionFrame title="Negative Positions">
          {losingPositions.length ? (
            <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
              {losingPositions.map((item) => {
                const size = Number(item.positionAmt);

                return (
                  <article className="pixel-card pixel-card-danger p-4" key={item.symbol}>
                    <div className="flex items-center justify-between gap-3">
                      <strong className="pixel-value text-lg text-neutral-50">{item.symbol}</strong>
                      <span className={size > 0 ? "text-sm font-black text-emerald-300" : "text-sm font-black text-rose-300"}>
                        {size > 0 ? "Long" : "Short"}
                      </span>
                    </div>
                    <strong className="pixel-metric pixel-number mt-4 block text-rose-300">{formatUsd(item.unRealizedProfit)}</strong>
                    <p className="pixel-meta mt-3">
                      Size <span className="pixel-number">{formatNumber(Math.abs(size), 4)}</span> / Entry{" "}
                      <span className="pixel-number">{formatUsd(item.entryPrice, 4)}</span> / Mark{" "}
                      <span className="pixel-number">{formatUsd(item.markPrice, 4)}</span>
                    </p>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="p-6 text-center text-sm font-bold text-neutral-500">No losing active positions right now.</div>
          )}
        </SectionFrame>

        <SectionFrame title="Balances">
          {accountAssets.length ? (
            <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
              {accountAssets.map((asset) => {
                const assetPnl = Number(asset.unrealizedProfit);

                return (
                  <article className="pixel-card p-4" key={asset.asset}>
                    <div className="flex items-center justify-between gap-3">
                      <strong className="pixel-value text-lg text-neutral-50">{asset.asset}</strong>
                      <span className={assetPnl >= 0 ? "text-sm font-black text-emerald-300" : "text-sm font-black text-rose-300"}>
                        PnL <span className="pixel-number">{formatNumber(asset.unrealizedProfit, 6)}</span>
                      </span>
                    </div>
                    <div className="pixel-meta mt-4 grid gap-2">
                      <span>
                        Wallet <span className="pixel-number">{formatNumber(asset.walletBalance, 6)}</span>
                      </span>
                      <span>
                        Margin <span className="pixel-number">{formatNumber(asset.marginBalance, 6)}</span>
                      </span>
                      <span className="text-sky-300">
                        Available <span className="pixel-number">{formatNumber(asset.availableBalance, 6)}</span>
                      </span>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="p-6 text-center text-sm font-bold text-neutral-500">No non-zero assets found, or private API keys are not loaded yet.</div>
          )}
        </SectionFrame>
      </div>
    </main>
  );
}
