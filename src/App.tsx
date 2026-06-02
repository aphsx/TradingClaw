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

const panel = "border-2 border-neutral-800 bg-black";
const label = "text-[0.68rem] font-black uppercase tracking-[0.18em] text-neutral-500";

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
      className="h-[330px] w-full border-2 border-neutral-800 bg-[linear-gradient(rgba(255,255,255,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.08)_1px,transparent_1px),linear-gradient(180deg,#050505,#111111)] bg-[length:34px_34px,34px_34px,auto] md:h-[460px]"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      aria-label="BNB price chart"
    >
      <defs>
        <linearGradient id="chartGlow" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="46%" stopColor="#a3a3a3" />
          <stop offset="100%" stopColor="#525252" />
        </linearGradient>
      </defs>
      <polyline points={points} fill="none" stroke="url(#chartGlow)" strokeLinecap="round" strokeWidth="2.6" />
    </svg>
  );
}

function StatCard({ label: title, value, meta, accent = "bg-neutral-950 text-neutral-50" }: { label: string; value: string; meta?: string; accent?: string }) {
  return (
    <article className={`${panel} min-h-40 p-5 transition hover:-translate-y-1 hover:shadow-[8px_8px_0_#404040]`}>
      <div className="flex items-start justify-between gap-3">
        <span className={label}>{title}</span>
        <span className={`rounded-full px-2 py-1 text-[0.62rem] font-black uppercase tracking-widest ${accent}`}>Live</span>
      </div>
      <strong className="mt-8 block text-3xl font-black leading-none tracking-[-0.07em] text-neutral-50 sm:text-4xl">{value}</strong>
      {meta ? <small className="mt-3 block text-sm font-bold text-neutral-500">{meta}</small> : null}
    </article>
  );
}

function CatalogCard({ name, description, tag, tone = "neutral" }: { name: string; description: string; tag: string; tone?: "positive" | "negative" | "neutral" }) {
  const toneClass = tone === "positive" ? "bg-neutral-900" : tone === "negative" ? "bg-neutral-800" : "bg-neutral-900";

  return (
    <article className={`${panel} group flex min-h-52 flex-col justify-between p-5 transition hover:-translate-y-1 hover:shadow-[10px_10px_0_#404040]`}>
      <div>
        <div className="mb-5 flex items-center justify-between gap-3">
          <span className={`size-9 border-2 border-neutral-800 ${toneClass}`} />
          <span className="rounded-full border-2 border-neutral-800 px-2.5 py-1 text-[0.62rem] font-black uppercase tracking-widest text-neutral-50">
            {tag}
          </span>
        </div>
        <h3 className="text-2xl font-black tracking-[-0.06em] text-neutral-50">{name}</h3>
        <p className="mt-3 text-sm font-semibold leading-6 text-neutral-400">{description}</p>
      </div>
      <div className="mt-6 flex items-center justify-between border-t border-neutral-800 pt-4 text-xs font-black uppercase tracking-[0.16em] text-neutral-500">
        <span>Analysis</span>
        <span>——</span>
      </div>
    </article>
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
  const positionSide = hasPosition ? (positionAmount > 0 ? "Long" : "Short") : "Flat";
  const updatedAt = data ? new Date(data.updatedAt).toLocaleTimeString() : "Connecting";

  return (
    <main className="min-h-screen bg-black text-neutral-50">
      <div className="border-b border-neutral-800 bg-neutral-950 px-4 py-2 text-neutral-50">
        <div className="mx-auto flex max-w-[1540px] flex-wrap items-center justify-between gap-3 text-xs font-black uppercase tracking-[0.18em]">
          <span>Sponsor getmarket.md and monitor BNB live</span>
          <span>{state.error ? "Feed issue" : `Live read-only / ${updatedAt}`}</span>
        </div>
      </div>

      <section className="mx-auto max-w-[1540px] px-4 py-5 sm:px-6 lg:px-8">
        <nav className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-neutral-800 pb-5">
          <div className="text-2xl font-black tracking-[-0.08em]">getmarket.md</div>
          <div className="flex flex-wrap gap-2">
            {['Market', 'Position', 'Risk', 'Collateral'].map((item) => (
              <span className="rounded-full border-2 border-neutral-800 bg-black px-4 py-2 text-xs font-black uppercase tracking-widest" key={item}>
                {item}
              </span>
            ))}
          </div>
        </nav>

        {state.error ? <div className="mb-5 border-2 border-neutral-800 bg-neutral-950 p-4 font-bold text-neutral-200">Binance API: {state.error}</div> : null}
        {data && !data.private.configured ? (
          <div className="mb-5 border-2 border-neutral-800 bg-neutral-900 p-4 text-sm font-bold">
            Public market data is live. Add <code>BINANCE_API_KEY</code> and <code>BINANCE_API_SECRET</code> in <code>.env.local</code> to view your read-only account state.
          </div>
        ) : null}

        <header className="grid gap-5 lg:grid-cols-[1.35fr_0.65fr]">
          <article className="border-2 border-neutral-800 bg-black p-5 sm:p-8">
            <p className="mb-6 inline-flex border-2 border-neutral-800 bg-neutral-900 px-3 py-1 text-xs font-black uppercase tracking-[0.18em]">
              Production-grade BNBUSDT analysis
            </p>
            <h1 className="max-w-5xl text-6xl font-black leading-[0.84] tracking-[-0.095em] text-neutral-50 sm:text-7xl lg:text-8xl">
              {data?.symbol ?? "BNBUSDT"} perpetual design index
            </h1>
            <p className="mt-6 max-w-2xl text-lg font-semibold leading-8 text-neutral-400">
              Analyzed market patterns, position state, and account signals as a crisp DESIGN.md-inspired catalog. Built for fast scanning, not terminal clutter.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <button
                className="border-2 border-neutral-800 bg-neutral-950 px-5 py-3 text-sm font-black uppercase tracking-widest text-neutral-50 shadow-[6px_6px_0_#525252] transition hover:translate-x-1 hover:translate-y-1 hover:shadow-none disabled:cursor-wait disabled:opacity-60"
                type="button"
                onClick={loadDashboard}
                disabled={state.loading}
              >
                {state.loading ? "Syncing" : "Refresh data"}
              </button>
              <span className="border-2 border-neutral-800 bg-black px-5 py-3 text-sm font-black uppercase tracking-widest">
                Built on Binance Futures
              </span>
            </div>
          </article>

          <aside className="grid border-2 border-neutral-800 bg-neutral-950 text-neutral-50">
            <div className="border-b border-white/20 p-5">
              <span className="text-xs font-black uppercase tracking-[0.18em] text-neutral-400">Last Price</span>
              <strong className="mt-5 block text-6xl font-black leading-none tracking-[-0.09em]">{formatUsd(data?.market.ticker.lastPrice, 3)}</strong>
              <small className={priceChange >= 0 ? "mt-4 block text-xl font-black text-neutral-100" : "mt-4 block text-xl font-black text-neutral-300"}>
                {formatPercent(data?.market.ticker.priceChangePercent)} 24h
              </small>
            </div>
            <div className="grid grid-cols-2 divide-x divide-white/20">
              <div className="p-5">
                <span className="text-xs font-black uppercase tracking-widest text-neutral-400">Funding</span>
                <strong className="mt-3 block text-2xl font-black tracking-[-0.06em]">
                  {formatPercent(Number(data?.market.premiumIndex.lastFundingRate ?? 0) * 100, 4)}
                </strong>
                <small className="mt-1 block text-neutral-500">Next {nextFunding}</small>
              </div>
              <div className="p-5">
                <span className="text-xs font-black uppercase tracking-widest text-neutral-400">Open Interest</span>
                <strong className="mt-3 block text-2xl font-black tracking-[-0.06em]">
                  {formatNumber(data?.market.openInterest.openInterest, 2)}
                </strong>
                <small className="mt-1 block text-neutral-500">BNB contracts</small>
              </div>
            </div>
          </aside>
        </header>

        <section className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Mark" value={formatUsd(data?.market.premiumIndex.markPrice, 3)} />
          <StatCard label="Index" value={formatUsd(data?.market.premiumIndex.indexPrice, 3)} />
          <StatCard label="24h High" value={formatUsd(data?.market.ticker.highPrice)} accent="bg-neutral-900 text-neutral-50" />
          <StatCard label="24h Low" value={formatUsd(data?.market.ticker.lowPrice)} accent="bg-neutral-800 text-neutral-50" />
        </section>

        <section className="mt-8 grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
          <article className="border-2 border-neutral-800 bg-black p-5">
            <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className={label}>Featured Design</p>
                <h2 className="mt-2 text-4xl font-black tracking-[-0.075em]">BNB Market Card</h2>
              </div>
              <div className="flex gap-2">
                {['1m', '5m', '15m', '1h'].map((item) => (
                  <span className={item === '5m' ? 'border-2 border-neutral-800 bg-neutral-950 px-3 py-1 text-xs font-black text-neutral-50' : 'border-2 border-neutral-800 bg-black px-3 py-1 text-xs font-black'} key={item}>
                    {item}
                  </span>
                ))}
              </div>
            </div>
            {data ? <Sparkline klines={data.market.klines} /> : <div className="grid h-[330px] place-items-center border-2 border-neutral-800 bg-neutral-950 font-black text-neutral-500 md:h-[460px]">Loading chart...</div>}
          </article>

          <div className="grid gap-4">
            <CatalogCard
              name="Exposure"
              tag={positionSide}
              tone={positionSide === 'Short' ? 'negative' : 'positive'}
              description={`Size ${hasPosition ? `${formatNumber(Math.abs(positionAmount), 4)} BNB` : '--'} / UPnL ${formatUsd(pnl, 2)} / leverage ${position?.leverage ? `${position.leverage}x` : '--'}.`}
            />
            <CatalogCard
              name="Risk balance"
              tag="Risk"
              description={`Wallet ${formatUsd(data?.private.account?.totalWalletBalance)} / Margin ${formatUsd(data?.private.account?.totalMarginBalance)} / Available ${formatUsd(data?.private.account?.availableBalance)}.`}
            />
          </div>
        </section>

        <section className="mt-8">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-neutral-800 pb-4">
            <div>
              <p className={label}>Find Designs</p>
              <h2 className="mt-1 text-4xl font-black tracking-[-0.075em]">Design Systems Analysis</h2>
            </div>
            <div className="flex flex-wrap gap-2">
              {['All', `${activePositions.length} Active`, `${accountAssets.length} Assets`, 'Bookmarked'].map((item) => (
                <span className="border-2 border-neutral-800 bg-black px-3 py-2 text-xs font-black uppercase tracking-widest" key={item}>{item}</span>
              ))}
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <CatalogCard name="Open Interest" tag="Market" description={`${formatNumber(data?.market.openInterest.openInterest, 2)} BNB in active futures interest with ${formatUsd(data?.market.ticker.quoteVolume, 0)} quote volume.`} />
            <CatalogCard name="Session Range" tag="Range" description={`High ${formatUsd(data?.market.ticker.highPrice)} / Low ${formatUsd(data?.market.ticker.lowPrice)} / BNB volume ${formatNumber(data?.market.ticker.volume, 2)}.`} />
            <CatalogCard name="Position Guard" tag="Private" tone={pnl >= 0 ? 'positive' : 'negative'} description={`Entry ${formatUsd(position?.entryPrice, 3)} / Mark ${formatUsd(position?.markPrice ?? data?.market.premiumIndex.markPrice, 3)} / Liq ${hasPosition ? formatUsd(position?.liquidationPrice, 3) : '--'}.`} />
          </div>
        </section>

        <section className="mt-8 grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(360px,0.75fr)]">
          <article className={`${panel} p-5`}>
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-3xl font-black tracking-[-0.07em]">Position Entries</h2>
              <span className="border-2 border-neutral-800 bg-neutral-900 px-3 py-1 text-xs font-black uppercase tracking-widest">{activePositions.length} active</span>
            </div>
            {activePositions.length ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[780px] border-collapse text-sm font-bold">
                  <thead>
                    <tr className="border-y border-neutral-800 bg-neutral-950 text-neutral-50">
                      {['Symbol', 'Side', 'Size', 'Entry', 'Mark', 'PnL', 'Lev', 'Liq'].map((heading, index) => (
                        <th className={`px-3 py-3 ${index === 0 ? 'text-left' : 'text-right'}`} key={heading}>{heading}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {activePositions.map((item) => {
                      const size = Number(item.positionAmt);
                      const itemPnl = Number(item.unRealizedProfit);

                      return (
                        <tr className="border-b border-neutral-800" key={item.symbol}>
                          <td className="px-3 py-3">{item.symbol}</td>
                          <td className={size >= 0 ? 'px-3 py-3 text-right text-neutral-100' : 'px-3 py-3 text-right text-neutral-300'}>{size >= 0 ? 'Long' : 'Short'}</td>
                          <td className="px-3 py-3 text-right">{formatNumber(Math.abs(size), 4)}</td>
                          <td className="px-3 py-3 text-right">{formatUsd(item.entryPrice, 4)}</td>
                          <td className="px-3 py-3 text-right">{formatUsd(item.markPrice, 4)}</td>
                          <td className={itemPnl >= 0 ? 'px-3 py-3 text-right text-neutral-100' : 'px-3 py-3 text-right text-neutral-300'}>{formatUsd(itemPnl)}</td>
                          <td className="px-3 py-3 text-right">{item.leverage}x</td>
                          <td className="px-3 py-3 text-right">{formatUsd(item.liquidationPrice, 4)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="grid min-h-44 place-items-center border border-dashed border-neutral-800 bg-neutral-950 p-6 text-center font-bold text-neutral-500">
                No open futures positions from the read-only account response.
              </div>
            )}
          </article>

          <article className={`${panel} p-5`}>
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-3xl font-black tracking-[-0.07em]">Collateral Cards</h2>
              <span className="border-2 border-neutral-800 bg-neutral-900 px-3 py-1 text-xs font-black uppercase tracking-widest">{accountAssets.length} assets</span>
            </div>
            {accountAssets.length ? (
              <div className="grid gap-3">
                {accountAssets.map((asset) => (
                  <div className="border-2 border-neutral-800 bg-neutral-950 p-4" key={asset.asset}>
                    <div className="flex items-center justify-between gap-3">
                      <strong className="text-xl font-black tracking-[-0.05em]">{asset.asset}</strong>
                      <span className={Number(asset.unrealizedProfit) >= 0 ? 'font-black text-neutral-100' : 'font-black text-neutral-300'}>
                        PnL {formatNumber(asset.unrealizedProfit, 6)}
                      </span>
                    </div>
                    <div className="mt-3 grid gap-2 text-sm font-bold text-neutral-500">
                      <span>Wallet {formatNumber(asset.walletBalance, 6)}</span>
                      <span>Margin {formatNumber(asset.marginBalance, 6)}</span>
                      <span>Available {formatNumber(asset.availableBalance, 6)}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="grid min-h-44 place-items-center border border-dashed border-neutral-800 bg-neutral-950 p-6 text-center font-bold text-neutral-500">
                No non-zero assets found, or private API keys are not loaded yet.
              </div>
            )}
          </article>
        </section>
      </section>
    </main>
  );
}
