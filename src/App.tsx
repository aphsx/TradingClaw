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

const frame = "overflow-hidden rounded-lg border-2 border-neutral-800 bg-neutral-950";
const headingCell = "px-4 py-3 text-left text-[0.68rem] font-black uppercase tracking-[0.16em] text-neutral-400";
const valueCell = "px-4 py-3 text-sm font-bold text-neutral-100";

function SummaryCard({ label, value, meta, tone = "blue" }: { label: string; value: string; meta?: string; tone?: "green" | "red" | "blue" | "purple" }) {
  const toneClass = {
    green: "text-emerald-300",
    red: "text-rose-300",
    blue: "text-sky-300",
    purple: "text-violet-300"
  }[tone];

  return (
    <article className="rounded-lg border-2 border-neutral-800 bg-neutral-950 p-5 shadow-[6px_6px_0_rgba(56,189,248,0.22)]">
      <div className="flex items-center gap-3">
        <span className="grid size-7 place-items-center rounded-full border border-neutral-700 text-xs font-black text-neutral-500">$</span>
        <span className="text-[0.68rem] font-black uppercase tracking-[0.18em] text-neutral-400">{label}</span>
      </div>
      <strong className={`mt-5 block text-4xl font-black leading-none tracking-[-0.08em] ${toneClass}`}>{value}</strong>
      {meta ? <small className="mt-3 block text-xs font-bold text-neutral-500">{meta}</small> : null}
    </article>
  );
}

function SectionFrame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className={frame}>
      <div className="border-b-2 border-neutral-800 px-4 py-3">
        <h2 className="text-sm font-black uppercase tracking-[0.18em] text-neutral-100">{title}</h2>
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
    <div className="border-2 border-neutral-800 bg-black p-4">
      <span className="text-[0.68rem] font-black uppercase tracking-[0.16em] text-neutral-500">{label}</span>
      <strong className={`mt-3 block text-2xl font-black tracking-[-0.06em] ${toneClass}`}>{value}</strong>
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
  const losingPositions = activePositions.filter((position) => Number(position.unRealizedProfit) < 0);
  const accountAssets = account?.assets?.filter((asset) => Number(asset.walletBalance) !== 0 || Number(asset.marginBalance) !== 0) ?? [];
  const totalPnl = Number(account?.totalUnrealizedProfit ?? activePositions.reduce((sum, position) => sum + Number(position.unRealizedProfit), 0));
  const totalNotional = activePositions.reduce((sum, position) => sum + Math.abs(Number(position.notional ?? 0)), 0);
  const updatedAt = data ? new Date(data.updatedAt).toLocaleTimeString() : "Connecting";

  return (
    <main className="min-h-screen bg-black bg-[radial-gradient(circle_at_10%_0%,rgba(14,165,233,0.18),transparent_26rem),radial-gradient(circle_at_90%_4%,rgba(168,85,247,0.14),transparent_24rem)] text-neutral-100">
      <div className="border-b-2 border-neutral-800 bg-neutral-950 px-4 py-3">
        <div className="mx-auto flex max-w-[1540px] flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[0.68rem] font-black uppercase tracking-[0.18em] text-sky-300">Current Portfolio Dashboard</p>
            <h1 className="mt-1 text-3xl font-black tracking-[-0.08em] text-neutral-50">TradingClaw</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-neutral-700 px-3 py-2 text-xs font-black uppercase tracking-widest text-neutral-400">
              {state.error ? "Feed issue" : `Last sync ${updatedAt}`}
            </span>
            <span className="rounded-full border border-neutral-700 px-3 py-2 text-xs font-black uppercase tracking-widest text-neutral-400">
              {data?.private.configured ? "Private API loaded" : "Public only"}
            </span>
            <button
              className="rounded-full border-2 border-neutral-800 bg-sky-400 px-4 py-2 text-xs font-black uppercase tracking-widest text-neutral-950 disabled:cursor-wait disabled:opacity-60"
              type="button"
              onClick={loadDashboard}
              disabled={state.loading}
            >
              {state.loading ? "Syncing" : "Refresh"}
            </button>
          </div>
        </div>
      </div>

      <div className="mx-auto grid max-w-[1540px] gap-5 px-4 py-5 sm:px-6 lg:px-8">
        {state.error ? <div className="rounded-lg border-2 border-neutral-800 bg-rose-950/70 p-4 font-bold text-rose-100">Binance API: {state.error}</div> : null}
        {data && !data.private.configured ? (
          <div className="rounded-lg border-2 border-neutral-800 bg-sky-950/70 p-4 text-sm font-bold text-sky-100">
            Add <code>BINANCE_API_KEY</code> and <code>BINANCE_API_SECRET</code> in <code>.env.local</code> to show wallet balance, private positions, and account risk.
          </div>
        ) : null}

        <section className="grid gap-5 md:grid-cols-3">
          <SummaryCard label="Wallet Balance" value={formatUsd(account?.totalWalletBalance)} meta="Current account wallet" tone="green" />
          <SummaryCard label="Unrealized PnL" value={formatUsd(totalPnl)} meta={`${losingPositions.length} losing positions`} tone={totalPnl >= 0 ? "green" : "red"} />
          <SummaryCard label="Active Positions" value={String(activePositions.length)} meta={`Exposure ${formatUsd(totalNotional)}`} tone="purple" />
        </section>

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

        <SectionFrame title="Current BNB Position">
          <div className="grid gap-4 p-4 lg:grid-cols-[0.72fr_1fr]">
            <div className="border-2 border-neutral-800 bg-black p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <span className="text-[0.68rem] font-black uppercase tracking-[0.16em] text-neutral-500">Symbol</span>
                  <strong className="mt-3 block text-4xl font-black tracking-[-0.08em] text-neutral-50">{data?.symbol ?? "BNBUSDT"}</strong>
                </div>
                <span className={hasBnbPosition ? (bnbPositionAmount > 0 ? "border-2 border-emerald-400 bg-emerald-400 px-3 py-1 text-xs font-black uppercase tracking-widest text-neutral-950" : "border-2 border-rose-400 bg-rose-400 px-3 py-1 text-xs font-black uppercase tracking-widest text-neutral-950") : "border-2 border-neutral-800 bg-neutral-900 px-3 py-1 text-xs font-black uppercase tracking-widest text-neutral-300"}>
                  {hasBnbPosition ? (bnbPositionAmount > 0 ? "Long" : "Short") : "Flat"}
                </span>
              </div>
              <strong className="mt-8 block text-5xl font-black leading-none tracking-[-0.08em] text-neutral-50">
                {hasBnbPosition ? `${formatNumber(Math.abs(bnbPositionAmount), 4)} BNB` : "--"}
              </strong>
              <small className={Number(bnbPosition?.unRealizedProfit ?? 0) >= 0 ? "mt-4 block text-xl font-black text-emerald-300" : "mt-4 block text-xl font-black text-rose-300"}>
                UPnL {formatUsd(bnbPosition?.unRealizedProfit)}
              </small>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <DetailTile label="Entry" value={formatUsd(bnbPosition?.entryPrice, 4)} />
              <DetailTile label="Mark" value={formatUsd(bnbPosition?.markPrice ?? data?.market.premiumIndex.markPrice, 4)} tone="blue" />
              <DetailTile label="Leverage" value={bnbPosition?.leverage ? `${bnbPosition.leverage}x` : "--"} />
              <DetailTile label="Liquidation" value={hasBnbPosition ? formatUsd(bnbPosition?.liquidationPrice, 4) : "--"} tone="red" />
            </div>
          </div>
        </SectionFrame>

        <SectionFrame title="Active Positions">
          {activePositions.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] border-collapse">
                <thead>
                  <tr className="border-b border-neutral-800 bg-black">
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
                      <tr className="border-b border-neutral-900" key={item.symbol}>
                        <td className={valueCell}>{item.symbol}</td>
                        <td className={`${valueCell} ${size > 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{size > 0 ? 'Long' : 'Short'}</td>
                        <td className={valueCell}>{formatNumber(Math.abs(size), 4)}</td>
                        <td className={valueCell}>{formatUsd(item.entryPrice, 4)}</td>
                        <td className={valueCell}>{formatUsd(item.markPrice, 4)}</td>
                        <td className={`${valueCell} ${itemPnl >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{formatUsd(itemPnl)}</td>
                        <td className={valueCell}>{formatUsd(item.notional)}</td>
                        <td className={valueCell}>{item.leverage ? `${item.leverage}x` : '--'}</td>
                        <td className={valueCell}>{formatUsd(item.liquidationPrice, 4)}</td>
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
                  <article className="border-2 border-rose-400/50 bg-rose-950/20 p-4" key={item.symbol}>
                    <div className="flex items-center justify-between gap-3">
                      <strong className="text-xl font-black tracking-[-0.05em] text-neutral-50">{item.symbol}</strong>
                      <span className={size > 0 ? "text-sm font-black text-emerald-300" : "text-sm font-black text-rose-300"}>
                        {size > 0 ? "Long" : "Short"}
                      </span>
                    </div>
                    <strong className="mt-4 block text-3xl font-black tracking-[-0.07em] text-rose-300">{formatUsd(item.unRealizedProfit)}</strong>
                    <p className="mt-3 text-sm font-bold text-neutral-500">
                      Size {formatNumber(Math.abs(size), 4)} / Entry {formatUsd(item.entryPrice, 4)} / Mark {formatUsd(item.markPrice, 4)}
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
                  <article className="border-2 border-neutral-800 bg-black p-4" key={asset.asset}>
                    <div className="flex items-center justify-between gap-3">
                      <strong className="text-xl font-black tracking-[-0.05em] text-neutral-50">{asset.asset}</strong>
                      <span className={assetPnl >= 0 ? "text-sm font-black text-emerald-300" : "text-sm font-black text-rose-300"}>
                        PnL {formatNumber(asset.unrealizedProfit, 6)}
                      </span>
                    </div>
                    <div className="mt-4 grid gap-2 text-sm font-bold text-neutral-500">
                      <span>Wallet {formatNumber(asset.walletBalance, 6)}</span>
                      <span>Margin {formatNumber(asset.marginBalance, 6)}</span>
                      <span className="text-sky-300">Available {formatNumber(asset.availableBalance, 6)}</span>
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
