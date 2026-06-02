import { useEffect, useState } from "react";

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

const panel = "border-2 border-neutral-800 bg-neutral-950";
const label = "text-[0.68rem] font-black uppercase tracking-[0.18em] text-sky-300";

function MoneyCard({ label: title, value, meta, tone = "neutral" }: { label: string; value: string; meta?: string; tone?: "positive" | "negative" | "neutral" | "blue" }) {
  const toneClass = {
    positive: "border-emerald-400/70 bg-emerald-400/10 text-emerald-200",
    negative: "border-rose-400/70 bg-rose-400/10 text-rose-200",
    blue: "border-sky-400/70 bg-sky-400/10 text-sky-200",
    neutral: "border-neutral-800 bg-neutral-950 text-neutral-100"
  }[tone];

  return (
    <article className={`border-2 p-4 ${toneClass}`}>
      <span className="text-[0.68rem] font-black uppercase tracking-[0.18em] text-neutral-500">{title}</span>
      <strong className="mt-4 block text-3xl font-black leading-none tracking-[-0.07em] sm:text-4xl">{value}</strong>
      {meta ? <small className="mt-2 block text-sm font-bold text-neutral-500">{meta}</small> : null}
    </article>
  );
}

function PositionLine({ position, compact = false }: { position: PositionRisk; compact?: boolean }) {
  const size = Number(position.positionAmt);
  const pnl = Number(position.unRealizedProfit);
  const isLong = size >= 0;

  return (
    <div className="grid gap-3 border-2 border-neutral-800 bg-black p-4 md:grid-cols-[1fr_auto] md:items-center">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <strong className="text-xl font-black tracking-[-0.05em] text-neutral-50">{position.symbol}</strong>
          <span className={isLong ? "border border-emerald-400/60 px-2 py-0.5 text-xs font-black text-emerald-300" : "border border-rose-400/60 px-2 py-0.5 text-xs font-black text-rose-300"}>
            {isLong ? "LONG" : "SHORT"}
          </span>
          <span className="border border-neutral-700 px-2 py-0.5 text-xs font-black text-neutral-400">{position.leverage}x</span>
        </div>
        {!compact ? (
          <p className="mt-2 text-sm font-semibold text-neutral-500">
            Size {formatNumber(Math.abs(size), 4)} / Entry {formatUsd(position.entryPrice, 4)} / Mark {formatUsd(position.markPrice, 4)} / Liq {formatUsd(position.liquidationPrice, 4)}
          </p>
        ) : null}
      </div>
      <div className="text-left md:text-right">
        <span className="text-xs font-black uppercase tracking-[0.18em] text-neutral-500">UPnL</span>
        <strong className={pnl >= 0 ? "block text-2xl font-black text-emerald-300" : "block text-2xl font-black text-rose-300"}>{formatUsd(pnl)}</strong>
      </div>
    </div>
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
  const account = data?.private.account;
  const bnbPosition = data?.private.position;
  const bnbPositionAmount = Number(bnbPosition?.positionAmt ?? 0);
  const hasBnbPosition = Boolean(bnbPosition && bnbPositionAmount !== 0);
  const activePositions = data?.private.activePositions ?? [];
  const negativePositions = activePositions.filter((position) => Number(position.unRealizedProfit) < 0);
  const accountAssets = account?.assets?.filter((asset) => Number(asset.walletBalance) !== 0 || Number(asset.marginBalance) !== 0) ?? [];
  const totalPnl = Number(account?.totalUnrealizedProfit ?? activePositions.reduce((sum, position) => sum + Number(position.unRealizedProfit), 0));
  const totalNotional = activePositions.reduce((sum, position) => sum + Math.abs(Number(position.notional ?? 0)), 0);
  const updatedAt = data ? new Date(data.updatedAt).toLocaleTimeString() : "Connecting";

  return (
    <main className="min-h-screen bg-black bg-[radial-gradient(circle_at_12%_0%,rgba(14,165,233,0.2),transparent_28rem),radial-gradient(circle_at_92%_4%,rgba(168,85,247,0.16),transparent_24rem)] text-neutral-50">
      <div className="border-b border-neutral-800 bg-neutral-950 px-4 py-2">
        <div className="mx-auto flex max-w-[1540px] flex-wrap items-center justify-between gap-3 text-xs font-black uppercase tracking-[0.18em] text-neutral-300">
          <span>TradingClaw portfolio cockpit</span>
          <span>{state.error ? "Feed issue" : `Last sync / ${updatedAt}`}</span>
        </div>
      </div>

      <section className="mx-auto max-w-[1540px] px-4 py-5 sm:px-6 lg:px-8">
        <nav className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-neutral-800 pb-5">
          <div>
            <p className={label}>Private account first</p>
            <h1 className="mt-1 text-4xl font-black leading-none tracking-[-0.08em] text-neutral-50 sm:text-5xl">Portfolio Overview</h1>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="border-2 border-neutral-800 bg-sky-400 px-5 py-3 text-sm font-black uppercase tracking-widest text-neutral-950 shadow-[6px_6px_0_#7c3aed] transition hover:translate-x-1 hover:translate-y-1 hover:shadow-none disabled:cursor-wait disabled:opacity-60"
              type="button"
              onClick={loadDashboard}
              disabled={state.loading}
            >
              {state.loading ? "Syncing" : "Refresh portfolio"}
            </button>
            <span className="border-2 border-neutral-800 bg-neutral-950 px-4 py-3 text-xs font-black uppercase tracking-widest text-neutral-400">
              {data?.private.configured ? "Private API loaded" : "Public only"}
            </span>
          </div>
        </nav>

        {state.error ? <div className="mb-5 border-2 border-neutral-800 bg-rose-950/70 p-4 font-bold text-rose-100">Binance API: {state.error}</div> : null}
        {data && !data.private.configured ? (
          <div className="mb-5 border-2 border-neutral-800 bg-sky-950/70 p-4 text-sm font-bold text-sky-100">
            Add <code>BINANCE_API_KEY</code> and <code>BINANCE_API_SECRET</code> in <code>.env.local</code> to show wallet balance, private positions, and account risk.
          </div>
        ) : null}

        <section className="grid gap-4 xl:grid-cols-[minmax(360px,0.9fr)_minmax(0,1.1fr)]">
          <article className={`${panel} p-5`}>
            <span className={label}>Wallet Balance</span>
            <strong className="mt-5 block text-7xl font-black leading-none tracking-[-0.1em] text-neutral-50 sm:text-8xl">
              {formatUsd(account?.totalWalletBalance)}
            </strong>
            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              <MoneyCard label="Unrealized PnL" value={formatUsd(totalPnl)} tone={totalPnl >= 0 ? "positive" : "negative"} />
              <MoneyCard label="Available" value={formatUsd(account?.availableBalance)} tone="blue" />
            </div>
          </article>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MoneyCard label="Margin Balance" value={formatUsd(account?.totalMarginBalance)} />
            <MoneyCard label="Maintenance" value={formatUsd(account?.totalMaintMargin)} tone="negative" />
            <MoneyCard label="Active Positions" value={String(activePositions.length)} meta={`${negativePositions.length} losing`} tone={negativePositions.length ? "negative" : "positive"} />
            <MoneyCard label="Total Notional" value={formatUsd(totalNotional)} meta="Absolute exposure" tone="blue" />
          </div>
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_430px]">
          <article className={`${panel} p-5`}>
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className={label}>Current BNB position</p>
                <h2 className="mt-2 text-4xl font-black tracking-[-0.075em] text-neutral-50">{data?.symbol ?? "BNBUSDT"}</h2>
              </div>
              <span className={hasBnbPosition ? (bnbPositionAmount > 0 ? "border-2 border-emerald-400 bg-emerald-400 px-3 py-1 text-xs font-black uppercase tracking-widest text-neutral-950" : "border-2 border-rose-400 bg-rose-400 px-3 py-1 text-xs font-black uppercase tracking-widest text-neutral-950") : "border-2 border-neutral-800 bg-neutral-900 px-3 py-1 text-xs font-black uppercase tracking-widest text-neutral-300"}>
                {hasBnbPosition ? (bnbPositionAmount > 0 ? "Long" : "Short") : "Flat"}
              </span>
            </div>
            <div className="grid gap-4 lg:grid-cols-[0.72fr_1fr]">
              <div className="border-2 border-neutral-800 bg-black p-5">
                <span className="text-xs font-black uppercase tracking-[0.18em] text-neutral-500">Position Size</span>
                <strong className="mt-4 block text-5xl font-black leading-none tracking-[-0.08em] text-neutral-50">
                  {hasBnbPosition ? `${formatNumber(Math.abs(bnbPositionAmount), 4)} BNB` : "--"}
                </strong>
                <small className={Number(bnbPosition?.unRealizedProfit ?? 0) >= 0 ? "mt-4 block text-xl font-black text-emerald-300" : "mt-4 block text-xl font-black text-rose-300"}>
                  UPnL {formatUsd(bnbPosition?.unRealizedProfit)}
                </small>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <MoneyCard label="Entry" value={formatUsd(bnbPosition?.entryPrice, 3)} />
                <MoneyCard label="Mark" value={formatUsd(bnbPosition?.markPrice ?? data?.market.premiumIndex.markPrice, 3)} tone="blue" />
                <MoneyCard label="Liquidation" value={hasBnbPosition ? formatUsd(bnbPosition?.liquidationPrice, 3) : "--"} tone="negative" />
                <MoneyCard label="Leverage" value={bnbPosition?.leverage ? `${bnbPosition.leverage}x` : "--"} />
              </div>
            </div>
          </article>

          <aside className={`${panel} p-5`}>
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <p className={label}>Loss watch</p>
                <h2 className="mt-1 text-3xl font-black tracking-[-0.07em] text-neutral-50">Negative Positions</h2>
              </div>
              <span className="border-2 border-rose-400 bg-rose-400 px-3 py-1 text-xs font-black uppercase tracking-widest text-neutral-950">
                {negativePositions.length} losing
              </span>
            </div>
            {negativePositions.length ? (
              <div className="grid gap-3">
                {negativePositions.map((position) => (
                  <PositionLine compact key={position.symbol} position={position} />
                ))}
              </div>
            ) : (
              <div className="grid min-h-44 place-items-center border border-dashed border-neutral-800 bg-black p-6 text-center font-bold text-neutral-500">
                No losing active positions right now.
              </div>
            )}
          </aside>
        </section>

        <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(360px,0.75fr)]">
          <article className={`${panel} p-5`}>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className={label}>Current active exposure only</p>
                <h2 className="mt-1 text-3xl font-black tracking-[-0.07em] text-neutral-50">Active Positions</h2>
              </div>
              <span className="border-2 border-sky-400 bg-sky-400 px-3 py-1 text-xs font-black uppercase tracking-widest text-neutral-950">
                {activePositions.length} current
              </span>
            </div>
            {activePositions.length ? (
              <div className="max-h-[560px] overflow-auto border-2 border-neutral-800">
                <table className="w-full min-w-[880px] border-collapse text-sm font-bold">
                  <thead className="sticky top-0 bg-neutral-900 text-neutral-300">
                    <tr className="border-b border-neutral-800">
                      {['Symbol', 'Side', 'Size', 'Entry', 'Mark', 'PnL', 'Notional', 'Lev', 'Liq'].map((heading, index) => (
                        <th className={`px-3 py-3 ${index === 0 ? 'text-left' : 'text-right'}`} key={heading}>{heading}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {activePositions.map((item) => {
                      const size = Number(item.positionAmt);
                      const itemPnl = Number(item.unRealizedProfit);

                      return (
                        <tr className="border-b border-neutral-800 bg-black text-neutral-100" key={item.symbol}>
                          <td className="px-3 py-3 text-left">{item.symbol}</td>
                          <td className={size > 0 ? 'px-3 py-3 text-right text-emerald-300' : size < 0 ? 'px-3 py-3 text-right text-rose-300' : 'px-3 py-3 text-right text-neutral-600'}>
                            {size > 0 ? 'Long' : size < 0 ? 'Short' : 'Flat'}
                          </td>
                          <td className="px-3 py-3 text-right">{formatNumber(Math.abs(size), 4)}</td>
                          <td className="px-3 py-3 text-right">{formatUsd(item.entryPrice, 4)}</td>
                          <td className="px-3 py-3 text-right">{formatUsd(item.markPrice, 4)}</td>
                          <td className={itemPnl > 0 ? 'px-3 py-3 text-right text-emerald-300' : itemPnl < 0 ? 'px-3 py-3 text-right text-rose-300' : 'px-3 py-3 text-right'}>
                            {formatUsd(itemPnl)}
                          </td>
                          <td className="px-3 py-3 text-right">{formatUsd(item.notional)}</td>
                          <td className="px-3 py-3 text-right">{item.leverage ? `${item.leverage}x` : '--'}</td>
                          <td className="px-3 py-3 text-right">{formatUsd(item.liquidationPrice, 4)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="grid min-h-44 place-items-center border border-dashed border-neutral-800 bg-black p-6 text-center font-bold text-neutral-500">
                No active positions right now.
              </div>
            )}
          </article>

          <article className={`${panel} p-5`}>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className={label}>Assets with non-zero balances</p>
                <h2 className="mt-1 text-3xl font-black tracking-[-0.07em] text-neutral-50">Balances</h2>
              </div>
              <span className="border-2 border-sky-400 bg-sky-400 px-3 py-1 text-xs font-black uppercase tracking-widest text-neutral-950">
                {accountAssets.length} assets
              </span>
            </div>
            {accountAssets.length ? (
              <div className="grid gap-3">
                {accountAssets.map((asset) => (
                  <div className="border-2 border-neutral-800 bg-black p-4" key={asset.asset}>
                    <div className="flex items-center justify-between gap-3">
                      <strong className="text-xl font-black tracking-[-0.05em] text-neutral-50">{asset.asset}</strong>
                      <span className={Number(asset.unrealizedProfit) >= 0 ? 'font-black text-emerald-300' : 'font-black text-rose-300'}>
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
              <div className="grid min-h-44 place-items-center border border-dashed border-neutral-800 bg-black p-6 text-center font-bold text-neutral-500">
                No non-zero assets found, or private API keys are not loaded yet.
              </div>
            )}
          </article>
        </section>

      </section>
    </main>
  );
}
