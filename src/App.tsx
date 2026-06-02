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
    <svg
      className="min-h-[320px] w-full rounded-[2rem] border border-white/10 bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px),radial-gradient(circle_at_50%_28%,rgba(59,130,246,0.2),transparent_26rem),linear-gradient(180deg,rgba(15,23,42,0.86),rgba(2,6,23,0.92))] bg-[length:42px_42px,42px_42px,auto,auto] shadow-inner shadow-black/30 lg:h-[540px]"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      aria-label="BNB price chart"
    >
      <defs>
        <linearGradient id="chartGlow" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="#38bdf8" />
          <stop offset="48%" stopColor="#818cf8" />
          <stop offset="100%" stopColor="#c084fc" />
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
  const toneStyles = {
    positive: "border-emerald-300/20 bg-emerald-400/[0.07]",
    negative: "border-rose-300/20 bg-rose-400/[0.07]",
    neutral: "border-white/10 bg-white/[0.045]"
  };

  return (
    <section className={`rounded-3xl border p-4 shadow-2xl shadow-black/10 ${toneStyles[tone]}`}>
      <span className="text-[0.68rem] font-black uppercase tracking-[0.18em] text-slate-500">{label}</span>
      <strong className="mt-3 block text-2xl font-black tracking-[-0.06em] text-slate-100">{value}</strong>
      {subValue ? <small className="mt-1 block text-sm font-semibold text-slate-500">{subValue}</small> : null}
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

  const priceTone = priceChange >= 0 ? "text-emerald-300" : "text-rose-300";
  const pnlTone = pnl >= 0 ? "text-emerald-300" : "text-rose-300";
  const positionSide = hasPosition ? (positionAmount > 0 ? "Long" : "Short") : "Flat";

  return (
    <main className="min-h-screen overflow-hidden bg-[#050816] text-slate-100">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_12%_5%,rgba(14,165,233,0.22),transparent_28rem),radial-gradient(circle_at_88%_8%,rgba(168,85,247,0.18),transparent_26rem),linear-gradient(135deg,#050816_0%,#0b1020_48%,#030712_100%)]" />
      <div className="pointer-events-none fixed inset-0 bg-[linear-gradient(rgba(148,163,184,0.045)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.045)_1px,transparent_1px)] bg-[length:86px_86px] opacity-80 [mask-image:linear-gradient(to_bottom,black,transparent_85%)]" />

      <div className="relative mx-auto flex min-h-screen max-w-[1800px] gap-4 p-3 sm:p-4">
        <aside className="hidden w-[76px] shrink-0 flex-col items-center gap-4 rounded-[2rem] border border-white/10 bg-white/[0.045] p-3 shadow-2xl shadow-black/30 backdrop-blur-2xl xl:flex">
          <div className="grid size-12 place-items-center rounded-2xl bg-gradient-to-br from-sky-400 via-indigo-400 to-fuchsia-400 text-sm font-black text-white shadow-lg shadow-sky-950/40">
            TC
          </div>
          {["MKT", "POS", "RISK", "API"].map((item, index) => (
            <div
              className={`grid size-12 place-items-center rounded-2xl border text-[0.62rem] font-black ${
                index === 0
                  ? "border-sky-300/30 bg-sky-300/15 text-sky-200"
                  : "border-white/8 bg-white/[0.035] text-slate-500"
              }`}
              key={item}
            >
              {item}
            </div>
          ))}
          <div className="mt-auto h-24 w-1 rounded-full bg-gradient-to-b from-sky-300 via-indigo-300 to-fuchsia-300" />
        </aside>

        <section className="min-w-0 flex-1 space-y-4">
          <header className="grid gap-3 rounded-[2rem] border border-white/10 bg-white/[0.055] p-3 shadow-2xl shadow-black/25 backdrop-blur-2xl lg:grid-cols-[1fr_auto] lg:items-center">
            <div>
              <p className="text-xs font-black uppercase tracking-[0.22em] text-sky-300">TradingClaw Command Center</p>
              <h1 className="mt-2 text-3xl font-black tracking-[-0.06em] text-white sm:text-4xl">BNB Perpetual Intelligence</h1>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-3">
                <span className={`size-2.5 rounded-full ${state.error ? "bg-rose-400" : "bg-emerald-400"}`} />
                <div>
                  <strong className="block text-sm font-black text-slate-100">{state.error ? "Feed Issue" : "Live Read-Only"}</strong>
                  <small className="text-xs font-semibold text-slate-500">
                    {data ? new Date(data.updatedAt).toLocaleTimeString() : "Connecting..."}
                  </small>
                </div>
              </div>
              <button
                className="rounded-2xl border border-sky-300/30 bg-gradient-to-br from-sky-400 to-indigo-500 px-5 py-3 text-sm font-black text-white shadow-lg shadow-sky-950/30 transition hover:-translate-y-0.5 hover:border-sky-200/50 disabled:cursor-wait disabled:opacity-50"
                type="button"
                onClick={loadDashboard}
                disabled={state.loading}
              >
                {state.loading ? "Syncing" : "Refresh"}
              </button>
            </div>
          </header>

          {state.error ? (
            <div className="rounded-3xl border border-rose-300/20 bg-rose-500/10 p-4 text-sm font-semibold text-rose-100">
              Binance API: {state.error}
            </div>
          ) : null}
          {data && !data.private.configured ? (
            <div className="rounded-3xl border border-sky-300/15 bg-sky-400/10 p-4 text-sm font-semibold text-slate-300">
              Public market data is live. Add <code className="text-sky-200">BINANCE_API_KEY</code> and{" "}
              <code className="text-sky-200">BINANCE_API_SECRET</code> in <code className="text-sky-200">.env.local</code> to view
              your read-only account state.
            </div>
          ) : null}

          <section className="grid gap-4 2xl:grid-cols-[360px_minmax(0,1fr)_420px]">
            <div className="space-y-4">
              <article className="overflow-hidden rounded-[2rem] border border-white/10 bg-white/[0.055] shadow-2xl shadow-black/25 backdrop-blur-2xl">
                <div className="border-b border-white/10 p-5">
                  <p className="text-xs font-black uppercase tracking-[0.22em] text-slate-500">Instrument</p>
                  <h2 className="mt-3 text-5xl font-black tracking-[-0.08em] text-white">{data?.symbol ?? "BNBUSDT"}</h2>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {["Binance Futures", "USD-M", "10s sync"].map((item) => (
                      <span className="rounded-full border border-white/10 bg-slate-950/40 px-3 py-1 text-xs font-bold text-slate-400" key={item}>
                        {item}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="p-5">
                  <span className="text-xs font-black uppercase tracking-[0.18em] text-slate-500">Last Price</span>
                  <strong className={`mt-3 block text-5xl font-black tracking-[-0.08em] sm:text-6xl ${priceTone}`}>
                    {formatUsd(data?.market.ticker.lastPrice, 3)}
                  </strong>
                  <small className={`mt-2 block text-lg font-black ${priceTone}`}>
                    {formatPercent(data?.market.ticker.priceChangePercent)} 24h
                  </small>
                </div>
              </article>

              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-1">
                <MetricCard label="24h High" value={formatUsd(data?.market.ticker.highPrice)} tone="positive" />
                <MetricCard label="24h Low" value={formatUsd(data?.market.ticker.lowPrice)} tone="negative" />
                <MetricCard label="Mark Price" value={formatUsd(data?.market.premiumIndex.markPrice, 3)} />
                <MetricCard label="Index Price" value={formatUsd(data?.market.premiumIndex.indexPrice, 3)} />
              </div>
            </div>

            <article className="rounded-[2rem] border border-white/10 bg-white/[0.055] p-4 shadow-2xl shadow-black/25 backdrop-blur-2xl">
              <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-black uppercase tracking-[0.22em] text-sky-300">Market Flow</p>
                  <h2 className="mt-2 text-2xl font-black tracking-[-0.05em] text-white">Momentum Surface</h2>
                </div>
                <div className="flex flex-wrap gap-2">
                  {["1m", "5m", "15m", "1h"].map((item) => (
                    <span
                      className={`rounded-full border px-3 py-1.5 text-xs font-black ${
                        item === "5m"
                          ? "border-sky-300/30 bg-sky-300/15 text-sky-100"
                          : "border-white/10 bg-slate-950/30 text-slate-500"
                      }`}
                      key={item}
                    >
                      {item}
                    </span>
                  ))}
                </div>
              </div>
              {data ? (
                <Sparkline klines={data.market.klines} />
              ) : (
                <div className="grid min-h-[320px] place-items-center rounded-[2rem] border border-white/10 bg-slate-950/40 text-slate-500 lg:h-[540px]">
                  Loading chart...
                </div>
              )}
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <MetricCard label="Open Interest" value={`${formatNumber(data?.market.openInterest.openInterest, 2)} BNB`} />
                <MetricCard label="Quote Volume" value={formatUsd(data?.market.ticker.quoteVolume, 0)} />
                <MetricCard label="BNB Volume" value={formatNumber(data?.market.ticker.volume, 2)} />
                <MetricCard
                  label="Funding"
                  value={formatPercent(Number(data?.market.premiumIndex.lastFundingRate ?? 0) * 100, 4)}
                  subValue={`Next ${nextFunding}`}
                />
              </div>
            </article>

            <div className="space-y-4">
              <article className="rounded-[2rem] border border-white/10 bg-white/[0.055] p-5 shadow-2xl shadow-black/25 backdrop-blur-2xl">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-black uppercase tracking-[0.22em] text-slate-500">Position</p>
                    <h2 className="mt-2 text-2xl font-black tracking-[-0.05em] text-white">Exposure</h2>
                  </div>
                  <span
                    className={`rounded-full border px-3 py-1.5 text-xs font-black ${
                      positionSide === "Short"
                        ? "border-rose-300/25 bg-rose-400/10 text-rose-200"
                        : "border-emerald-300/25 bg-emerald-400/10 text-emerald-200"
                    }`}
                  >
                    {positionSide}
                  </span>
                </div>
                <div className="mt-5 rounded-3xl border border-sky-300/15 bg-gradient-to-br from-sky-400/10 via-indigo-400/10 to-fuchsia-400/10 p-5">
                  <span className="text-xs font-black uppercase tracking-[0.18em] text-slate-500">Size</span>
                  <strong className="mt-3 block text-4xl font-black tracking-[-0.07em] text-white">
                    {hasPosition ? `${formatNumber(Math.abs(positionAmount), 4)} BNB` : "--"}
                  </strong>
                  <small className={`mt-2 block text-base font-black ${pnlTone}`}>UPnL {formatUsd(pnl, 2)}</small>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <MetricCard label="Entry" value={formatUsd(position?.entryPrice, 3)} />
                  <MetricCard label="Mark" value={formatUsd(position?.markPrice ?? data?.market.premiumIndex.markPrice, 3)} />
                  <MetricCard label="Liq" value={hasPosition ? formatUsd(position?.liquidationPrice, 3) : "--"} tone="negative" />
                  <MetricCard label="Leverage" value={position?.leverage ? `${position.leverage}x` : "--"} />
                </div>
              </article>

              <article className="rounded-[2rem] border border-white/10 bg-white/[0.055] p-5 shadow-2xl shadow-black/25 backdrop-blur-2xl">
                <p className="text-xs font-black uppercase tracking-[0.22em] text-slate-500">Account Risk</p>
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <MetricCard label="Wallet" value={formatUsd(data?.private.account?.totalWalletBalance)} />
                  <MetricCard label="Margin" value={formatUsd(data?.private.account?.totalMarginBalance)} />
                  <MetricCard label="Available" value={formatUsd(data?.private.account?.availableBalance)} tone="positive" />
                  <MetricCard label="Maint" value={formatUsd(data?.private.account?.totalMaintMargin)} tone="negative" />
                </div>
              </article>
            </div>
          </section>

          <section className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(360px,0.75fr)]">
            <article className="rounded-[2rem] border border-white/10 bg-white/[0.055] p-4 shadow-2xl shadow-black/25 backdrop-blur-2xl">
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-black uppercase tracking-[0.22em] text-slate-500">Portfolio</p>
                  <h2 className="mt-2 text-2xl font-black tracking-[-0.05em] text-white">Open Positions</h2>
                </div>
                <span className="rounded-full border border-sky-300/20 bg-sky-300/10 px-3 py-1.5 text-xs font-black text-sky-100">
                  {activePositions.length} active
                </span>
              </div>
              {activePositions.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[780px] border-collapse">
                    <thead>
                      <tr className="border-y border-white/10 bg-slate-950/35 text-[0.68rem] uppercase tracking-[0.14em] text-slate-500">
                        <th className="px-3 py-3 text-left">Symbol</th>
                        <th className="px-3 py-3 text-right">Side</th>
                        <th className="px-3 py-3 text-right">Size</th>
                        <th className="px-3 py-3 text-right">Entry</th>
                        <th className="px-3 py-3 text-right">Mark</th>
                        <th className="px-3 py-3 text-right">PnL</th>
                        <th className="px-3 py-3 text-right">Lev</th>
                        <th className="px-3 py-3 text-right">Liq</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activePositions.map((item) => {
                        const size = Number(item.positionAmt);
                        const itemPnl = Number(item.unRealizedProfit);

                        return (
                          <tr className="border-b border-white/10 text-sm font-bold text-slate-200" key={item.symbol}>
                            <td className="px-3 py-3 text-left">{item.symbol}</td>
                            <td className={`px-3 py-3 text-right ${size >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                              {size >= 0 ? "Long" : "Short"}
                            </td>
                            <td className="px-3 py-3 text-right">{formatNumber(Math.abs(size), 4)}</td>
                            <td className="px-3 py-3 text-right">{formatUsd(item.entryPrice, 4)}</td>
                            <td className="px-3 py-3 text-right">{formatUsd(item.markPrice, 4)}</td>
                            <td className={`px-3 py-3 text-right ${itemPnl >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                              {formatUsd(itemPnl)}
                            </td>
                            <td className="px-3 py-3 text-right">{item.leverage}x</td>
                            <td className="px-3 py-3 text-right">{formatUsd(item.liquidationPrice, 4)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="grid min-h-44 place-items-center rounded-3xl border border-dashed border-white/15 bg-slate-950/30 p-6 text-center text-sm font-semibold text-slate-500">
                  No open futures positions from the read-only account response.
                </div>
              )}
            </article>

            <article className="rounded-[2rem] border border-white/10 bg-white/[0.055] p-4 shadow-2xl shadow-black/25 backdrop-blur-2xl">
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-black uppercase tracking-[0.22em] text-slate-500">Collateral</p>
                  <h2 className="mt-2 text-2xl font-black tracking-[-0.05em] text-white">Balances</h2>
                </div>
                <span className="rounded-full border border-sky-300/20 bg-sky-300/10 px-3 py-1.5 text-xs font-black text-sky-100">
                  {accountAssets.length} assets
                </span>
              </div>
              {accountAssets.length ? (
                <div className="space-y-3">
                  {accountAssets.map((asset) => (
                    <div className="rounded-3xl border border-white/10 bg-slate-950/30 p-4" key={asset.asset}>
                      <div className="flex items-center justify-between gap-3">
                        <strong className="text-lg font-black text-sky-100">{asset.asset}</strong>
                        <span
                          className={
                            Number(asset.unrealizedProfit) >= 0
                              ? "text-sm font-black text-emerald-300"
                              : "text-sm font-black text-rose-300"
                          }
                        >
                          PnL {formatNumber(asset.unrealizedProfit, 6)}
                        </span>
                      </div>
                      <div className="mt-3 grid gap-2 text-sm font-semibold text-slate-400 sm:grid-cols-3">
                        <span>Wallet {formatNumber(asset.walletBalance, 6)}</span>
                        <span>Margin {formatNumber(asset.marginBalance, 6)}</span>
                        <span>Available {formatNumber(asset.availableBalance, 6)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="grid min-h-44 place-items-center rounded-3xl border border-dashed border-white/15 bg-slate-950/30 p-6 text-center text-sm font-semibold text-slate-500">
                  No non-zero assets found, or private API keys are not loaded yet.
                </div>
              )}
            </article>
          </section>
        </section>
      </div>
    </main>
  );
}
