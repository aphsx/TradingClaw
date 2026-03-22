'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell
} from 'recharts';
import {
  TrendingUp, Activity, DollarSign, Target, ShieldAlert,
  RefreshCw, Eye, Zap, Radio, ExternalLink, AlertTriangle
} from 'lucide-react';

function Card({ children, className = '' }: any) {
  return <div className={`bg-[#12121a] border border-[#1e1e2e] rounded-xl p-5 ${className}`}>{children}</div>;
}

function Metric({ label, value, sub, color }: any) {
  return (
    <Card>
      <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color || ''}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </Card>
  );
}

function Badge({ children, color }: any) {
  return (
    <span className="inline-block px-2 py-0.5 rounded text-xs font-semibold"
      style={{ background: `${color}18`, color }}>{children}</span>
  );
}

/** Margin ratio bar — green < 50%, yellow 50-75%, red > 75% */
function MarginBar({ ratio }: { ratio: number }) {
  const pct = Math.min(ratio * 100, 100);
  const color = pct < 50 ? '#22c55e' : pct < 75 ? '#f59e0b' : '#ef4444';
  return (
    <div className="w-full">
      <div className="flex justify-between text-[10px] text-gray-500 mb-1">
        <span>Margin ratio</span>
        <span style={{ color }} className="font-bold">{pct.toFixed(1)}%</span>
      </div>
      <div className="h-1.5 bg-[#1e1e2e] rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
      </div>
      {pct >= 75 && (
        <div className="flex items-center gap-1 mt-1 text-red-400 text-[10px]">
          <AlertTriangle size={10} />
          <span>{pct >= 90 ? 'EMERGENCY — close positions!' : 'Warning: high margin usage'}</span>
        </div>
      )}
    </div>
  );
}

export default function Dashboard({ data }: { data: any }) {
  const [tab, setTab] = useState<'live' | 'positions' | 'futures' | 'backtest'>('live');
  const [liveData, setLiveData] = useState<any>(null);
  const [balanceData, setBalanceData] = useState<any>(null);
  const [balanceError, setBalanceError] = useState<string | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchLive = useCallback(async () => {
    try {
      const [posRes, statsRes] = await Promise.all([
        fetch('/api/positions').then(r => r.json()),
        fetch('/api/stats?source=LIVE').then(r => r.json()),
      ]);
      const errs = [...(posRes._errors || []), ...(statsRes._errors || [])];
      setBackendError(errs.length > 0 ? errs[0] : null);
      setLiveData({ positions: posRes, stats: statsRes });
    } catch (e: any) {
      setBackendError(e.message);
    }

    try {
      const balRes = await fetch('/api/balance').then(r => r.json());
      if (balRes.error) {
        setBalanceError(`${balRes.error}${balRes.binance_code ? ` (code ${balRes.binance_code})` : ''}`);
      } else {
        setBalanceData(balRes);
        setBalanceError(null);
      }
    } catch (e: any) {
      setBalanceError(e.message);
    }
  }, []);

  useEffect(() => {
    fetchLive();
    const interval = setInterval(fetchLive, 10000);
    return () => clearInterval(interval);
  }, [fetchLive]);

  const refresh = async () => {
    setRefreshing(true);
    await fetchLive();
    setTimeout(() => setRefreshing(false), 600);
  };

  const trades = data?.liveTrades || [];
  const totalTrades = trades.length;
  const wins = trades.filter((t: any) => Number(t.pnl) > 0).length;
  const winRate = totalTrades > 0 ? ((wins / totalTrades) * 100).toFixed(1) : '—';
  const totalPnl = trades.reduce((s: number, t: any) => s + Number(t.pnl), 0);
  const totalFees = trades.reduce((s: number, t: any) => s + Number(t.total_fees || 0), 0);

  const monitor = liveData?.positions?.monitor || {};
  const regime = monitor.regime || {};
  const openPositions = liveData?.positions?.open_positions || data?.openPositions || [];
  const engineStatus = monitor.status?.status || 'unknown';

  // Redis margin + funding data
  const marginData = monitor.margin || {};
  const fundingData = monitor.funding || {};

  // Balance from Binance API
  const redisEquity = monitor.equity || {};
  const usdtFree = balanceData?.usdt_free ?? null;
  const usdtLocked = balanceData?.usdt_locked ?? null;
  const usdtTotal = balanceData?.usdt_total ?? redisEquity.equity ?? null;
  const unrealizedPnl = balanceData?.unrealized_pnl ?? redisEquity.unrealized ?? null;
  const marginRatio = balanceData?.margin_ratio ?? (marginData.margin_ratio ?? null);
  const marginBalance = balanceData?.margin_balance ?? null;

  const REGIME_COLORS: Record<string, string> = {
    Trending: '#22c55e', Ranging: '#3b82f6', Volatile: '#f59e0b'
  };

  const pnlData = trades.map((t: any, i: number) => ({
    idx: i + 1, pnl: Number(Number(t.pnl).toFixed(2)),
  }));

  // Funding rate helpers
  const fundingRates: Record<string, number> = {};
  if (fundingData && typeof fundingData === 'object') {
    // fundingData may be an object like {rate: ..., symbol: ...} or a per-symbol map
    if (typeof fundingData.rate === 'number') {
      fundingRates[fundingData.symbol || 'BTCUSDT'] = fundingData.rate;
    } else {
      Object.entries(fundingData).forEach(([sym, v]: [string, any]) => {
        if (typeof v?.rate === 'number') fundingRates[sym] = v.rate;
      });
    }
  }

  return (
    <div className="min-h-screen p-6 max-w-[1440px] mx-auto">
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">Futures Trading System</h1>
          <p className="text-sm text-gray-500">Binance USDM Futures · Testnet · Real-time</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap justify-end">

          {/* Balance card */}
          <div className={`flex items-center gap-3 bg-[#12121a] border rounded-lg px-4 py-2 ${balanceError ? 'border-red-900/50' : 'border-[#1e1e2e]'}`}>
            <DollarSign size={14} className={balanceError ? 'text-red-500 shrink-0' : 'text-green-400 shrink-0'} />
            <div>
              <div className="text-[10px] uppercase tracking-wider text-gray-500 leading-none mb-0.5">USDT Balance</div>
              {balanceError ? (
                <div className="text-xs text-red-400 leading-none max-w-[200px] truncate" title={balanceError}>
                  {balanceError}
                </div>
              ) : usdtTotal !== null ? (
                <div className="text-base font-bold text-green-400 leading-none">
                  ${usdtTotal.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
              ) : (
                <div className="text-gray-600 text-xs leading-none">connecting…</div>
              )}
            </div>
            {!balanceError && usdtFree !== null && (
              <div className="border-l border-[#1e1e2e] pl-3">
                <div className="text-[10px] uppercase tracking-wider text-gray-500 leading-none mb-0.5">Available</div>
                <div className="text-sm font-semibold text-gray-300 leading-none">
                  ${usdtFree.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
              </div>
            )}
            {!balanceError && unrealizedPnl !== null && (
              <div className="border-l border-[#1e1e2e] pl-3">
                <div className="text-[10px] uppercase tracking-wider text-gray-500 leading-none mb-0.5">Unrealized PnL</div>
                <div className={`text-sm font-semibold leading-none ${unrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {unrealizedPnl >= 0 ? '+' : ''}${unrealizedPnl.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
              </div>
            )}
            {/* Margin ratio mini-indicator */}
            {!balanceError && marginRatio !== null && (
              <div className="border-l border-[#1e1e2e] pl-3 min-w-[90px]">
                <MarginBar ratio={marginRatio} />
              </div>
            )}
          </div>

          {backendError && (
            <div className="flex items-center gap-2 bg-[#12121a] border border-red-900/50 rounded-lg px-3 py-2" title={backendError}>
              <div className="w-2 h-2 rounded-full bg-red-500" />
              <span className="text-xs text-red-400">DB offline</span>
            </div>
          )}

          <div className="flex items-center gap-2 bg-[#12121a] border border-[#1e1e2e] rounded-lg px-3 py-2">
            <div className={`w-2 h-2 rounded-full ${
              engineStatus === 'running' ? 'bg-green-400 animate-pulse' :
              engineStatus === 'error' ? 'bg-red-400' : 'bg-gray-500'
            }`} />
            <span className="text-xs text-gray-400">{engineStatus}</span>
          </div>

          {regime.regime && (
            <div className="flex items-center gap-2 bg-[#12121a] border border-[#1e1e2e] rounded-lg px-3 py-2">
              <div className="w-2 h-2 rounded-full" style={{ background: REGIME_COLORS[regime.regime] || '#666' }} />
              <span className="text-sm font-medium">{regime.regime}</span>
              <span className="text-xs text-gray-500">{regime.confidence ? `${(regime.confidence * 100).toFixed(0)}%` : ''}</span>
            </div>
          )}

          <button onClick={refresh} className={`p-2 rounded-lg bg-[#12121a] border border-[#1e1e2e] hover:bg-[#1a1a24] ${refreshing ? 'animate-spin' : ''}`}>
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {/* ── Tabs ── */}
      <div className="flex gap-1 mb-6 bg-[#12121a] border border-[#1e1e2e] rounded-lg p-1 w-fit">
        {[
          { key: 'live', label: `Live trades (${totalTrades})` },
          { key: 'positions', label: `Open (${openPositions.length})` },
          { key: 'futures', label: '⚡ Futures info' },
          { key: 'backtest', label: 'Backtest' },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key as any)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === t.key ? 'bg-[#1e1e2e] text-white' : 'text-gray-500 hover:text-gray-300'
            }`}>{t.label}</button>
        ))}
      </div>

      {/* ═══ LIVE TAB ═══ */}
      {tab === 'live' && (
        <>
          {totalTrades === 0 ? (
            <Card className="text-center py-16">
              <Radio size={48} className="mx-auto mb-4 text-gray-600" />
              <h2 className="text-lg font-semibold mb-2">No live trades yet</h2>
              <p className="text-gray-500 text-sm max-w-md mx-auto">
                Engine is {engineStatus === 'running' ? 'running — waiting for a signal' : 'not running'}. Trades appear here once the bot opens real Binance positions.
              </p>
            </Card>
          ) : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <Metric label="Net PnL" value={`$${totalPnl.toFixed(2)}`}
                  color={totalPnl >= 0 ? 'text-green-400' : 'text-red-400'} />
                <Metric label="Win Rate" value={`${winRate}%`} sub={`${wins}W / ${totalTrades - wins}L`} />
                <Metric label="Total Fees" value={`$${totalFees.toFixed(2)}`} color="text-amber-400"
                  sub="From Binance fills" />
                <Metric label="Closed Trades" value={totalTrades} />
              </div>

              {pnlData.length > 0 && (
                <Card className="mb-6">
                  <div className="text-sm font-semibold mb-4">PnL per trade</div>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={pnlData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
                      <XAxis dataKey="idx" stroke="#333" tick={{ fill: '#666', fontSize: 10 }} />
                      <YAxis stroke="#333" tick={{ fill: '#666', fontSize: 11 }} tickFormatter={v => `$${v}`} />
                      <Tooltip contentStyle={{ background: '#12121a', border: '1px solid #1e1e2e', borderRadius: 8 }} />
                      <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
                        {pnlData.map((e: any, i: number) => (
                          <Cell key={i} fill={e.pnl >= 0 ? '#22c55e' : '#ef4444'} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </Card>
              )}

              <Card>
                <div className="text-sm font-semibold mb-4">Trade log</div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm whitespace-nowrap">
                    <thead>
                      <tr className="text-gray-500 text-xs uppercase tracking-wider">
                        <th className="text-left pb-3 pr-3">Time</th>
                        <th className="text-left pb-3 pr-3">Dir</th>
                        <th className="text-left pb-3 pr-3">Strategy</th>
                        <th className="text-right pb-3 pr-3">Fill</th>
                        <th className="text-right pb-3 pr-3">Exit</th>
                        <th className="text-right pb-3 pr-3">Qty</th>
                        <th className="text-right pb-3 pr-3">PnL</th>
                        <th className="text-right pb-3 pr-3">Fee</th>
                        <th className="text-left pb-3">Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trades.map((t: any) => (
                        <tr key={t.id} className="border-t border-[#1e1e2e] hover:bg-[#1a1a24]">
                          <td className="py-2 pr-3 text-gray-400 text-xs">
                            {t.entry_time ? new Date(t.entry_time).toLocaleDateString('en', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                          </td>
                          <td className="py-2 pr-3">
                            <Badge color={t.direction === 'LONG' ? '#22c55e' : '#ef4444'}>{t.direction}</Badge>
                          </td>
                          <td className="py-2 pr-3 text-gray-300 text-xs">{t.strategy?.replace(/_/g, ' ')}</td>
                          <td className="py-2 pr-3 text-right">${Number(t.entry_fill_price || t.entry_price).toLocaleString()}</td>
                          <td className="py-2 pr-3 text-right">${Number(t.exit_fill_price || t.exit_price).toLocaleString()}</td>
                          <td className="py-2 pr-3 text-right text-gray-400">{Number(t.quantity).toFixed(5)}</td>
                          <td className={`py-2 pr-3 text-right font-medium ${Number(t.pnl) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            ${Number(t.pnl).toFixed(2)}
                          </td>
                          <td className="py-2 pr-3 text-right text-amber-400/70 text-xs">
                            {t.entry_commission ? `${Number(t.entry_commission).toFixed(6)} ${t.entry_commission_asset || ''}` : '—'}
                          </td>
                          <td className="py-2">
                            <span className={`text-xs ${t.exit_reason === 'Take Profit' ? 'text-green-400' : t.exit_reason === 'Stop Loss' ? 'text-red-400' : 'text-gray-400'}`}>
                              {t.exit_reason || '—'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </>
          )}
        </>
      )}

      {/* ═══ OPEN POSITIONS TAB ═══ */}
      {tab === 'positions' && (
        <Card>
          <div className="flex items-center justify-between mb-4">
            <div className="text-sm font-semibold">Open positions (live)</div>
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <Eye size={12} />
              Auto-refresh 10s
              {monitor.last_price && (
                <span className="ml-2 font-mono">BTC ${Number(monitor.last_price).toLocaleString()}</span>
              )}
            </div>
          </div>

          {openPositions.length === 0 ? (
            <div className="text-center py-16 text-gray-500">
              <Activity size={40} className="mx-auto mb-3 opacity-30" />
              <p>No open positions</p>
              <p className="text-xs mt-1">
                {engineStatus === 'running' ? 'Engine running — waiting for entry signal' : 'Start the engine to trade'}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm whitespace-nowrap">
                <thead>
                  <tr className="text-gray-500 text-xs uppercase tracking-wider">
                    <th className="text-left pb-3 pr-4">Symbol / Dir</th>
                    <th className="text-left pb-3 pr-4">Strategy</th>
                    <th className="text-right pb-3 pr-4">Entry</th>
                    <th className="text-right pb-3 pr-4">Current</th>
                    <th className="text-right pb-3 pr-4">Unrealized</th>
                    <th className="text-right pb-3 pr-4">SL</th>
                    <th className="text-right pb-3 pr-4">TP</th>
                    <th className="text-right pb-3 pr-4">Qty</th>
                    <th className="text-left pb-3">Since</th>
                  </tr>
                </thead>
                <tbody>
                  {openPositions.map((p: any, i: number) => {
                    const upnl = Number(p.unrealized_pnl || 0);
                    const pnlPct = Number(p.pnl_pct || 0);
                    return (
                      <tr key={i} className="border-t border-[#1e1e2e] hover:bg-[#1a1a24]">
                        <td className="py-3 pr-4">
                          <div className="flex items-center gap-2">
                            <Badge color={p.direction === 'LONG' ? '#22c55e' : '#ef4444'}>{p.direction}</Badge>
                            <span className="text-gray-400 text-xs">{p.symbol || 'BTCUSDT'}</span>
                          </div>
                        </td>
                        <td className="py-3 pr-4 text-gray-300 text-xs">{p.strategy?.replace(/_/g, ' ')}</td>
                        <td className="py-3 pr-4 text-right">
                          ${Number(p.entry_fill_price || p.entry_price).toLocaleString()}
                        </td>
                        <td className="py-3 pr-4 text-right font-medium">
                          ${Number(p.current_price || 0).toLocaleString()}
                        </td>
                        <td className={`py-3 pr-4 text-right font-bold ${upnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}
                          <span className="text-xs opacity-60 ml-1">({pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(1)}%)</span>
                        </td>
                        <td className="py-3 pr-4 text-right text-red-400/70">${Number(p.stop_loss).toLocaleString()}</td>
                        <td className="py-3 pr-4 text-right text-green-400/70">${Number(p.take_profit).toLocaleString()}</td>
                        <td className="py-3 pr-4 text-right text-gray-400">{Number(p.quantity).toFixed(5)}</td>
                        <td className="py-3 text-gray-500 text-xs">
                          {p.entry_time ? new Date(p.entry_time).toLocaleDateString('en', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {/* ═══ FUTURES INFO TAB ═══ */}
      {tab === 'futures' && (
        <div className="space-y-6">
          {/* Account margin overview */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card>
              <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-2">Wallet Balance</div>
              <div className="text-2xl font-bold text-green-400">
                {usdtTotal !== null ? `$${usdtTotal.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
              </div>
              <div className="text-xs text-gray-500 mt-1">USDT · Futures account</div>
            </Card>
            <Card>
              <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-2">Margin Balance</div>
              <div className="text-2xl font-bold text-blue-400">
                {marginBalance !== null ? `$${marginBalance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
              </div>
              <div className="text-xs text-gray-500 mt-1">Wallet + unrealized PnL</div>
            </Card>
            <Card>
              <div className="text-[11px] uppercase tracking-wider text-gray-500 mb-2">Unrealized PnL</div>
              <div className={`text-2xl font-bold ${unrealizedPnl === null ? 'text-gray-500' : unrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {unrealizedPnl !== null
                  ? `${unrealizedPnl >= 0 ? '+' : ''}$${unrealizedPnl.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                  : '—'}
              </div>
              <div className="text-xs text-gray-500 mt-1">Across all open positions</div>
            </Card>
          </div>

          {/* Margin ratio bar (big) */}
          {marginRatio !== null && (
            <Card>
              <div className="text-sm font-semibold mb-4">Margin health</div>
              <div className="max-w-lg">
                <MarginBar ratio={marginRatio} />
                <div className="grid grid-cols-3 mt-3 text-center text-xs text-gray-500">
                  <div><span className="text-green-400">●</span> Safe (&lt;50%)</div>
                  <div><span className="text-amber-400">●</span> Warning (50–75%)</div>
                  <div><span className="text-red-400">●</span> Emergency (&gt;75%)</div>
                </div>
              </div>
              {marginData?.total_wallet_balance && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5 pt-4 border-t border-[#1e1e2e]">
                  {[
                    { label: 'Wallet', value: `$${Number(marginData.total_wallet_balance).toFixed(2)}` },
                    { label: 'Initial margin', value: `$${Number(marginData.total_initial_margin || 0).toFixed(2)}` },
                    { label: 'Maint. margin', value: `$${Number(marginData.total_maintain_margin || 0).toFixed(2)}` },
                    { label: 'Available', value: `$${Number(marginData.available_balance || 0).toFixed(2)}` },
                  ].map(item => (
                    <div key={item.label}>
                      <div className="text-[10px] uppercase text-gray-500 mb-0.5">{item.label}</div>
                      <div className="text-sm font-semibold text-gray-200">{item.value}</div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}

          {/* Funding rates */}
          <Card>
            <div className="text-sm font-semibold mb-4">Funding rates (8h)</div>
            {Object.keys(fundingRates).length === 0 ? (
              <p className="text-gray-500 text-sm">No funding data — engine must be running</p>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {Object.entries(fundingRates).map(([sym, rate]) => {
                  const annualized = rate * 3 * 365 * 100;
                  const color = Math.abs(rate) > 0.001 ? '#f59e0b' : '#22c55e';
                  return (
                    <div key={sym} className="bg-[#0e0e18] rounded-lg p-3">
                      <div className="text-xs text-gray-500 mb-1">{sym}</div>
                      <div className="text-lg font-bold font-mono" style={{ color }}>
                        {(rate * 100).toFixed(4)}%
                      </div>
                      <div className="text-[10px] text-gray-600 mt-0.5">
                        ≈{annualized.toFixed(1)}% annual
                      </div>
                      {Math.abs(rate) > 0.001 && (
                        <div className="text-[10px] text-amber-400 mt-0.5">⚠ high funding</div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          {/* Open positions with liquidation info */}
          {openPositions.length > 0 && (
            <Card>
              <div className="text-sm font-semibold mb-4">Position details (Futures)</div>
              <div className="space-y-3">
                {openPositions.map((p: any, i: number) => {
                  const entry = Number(p.entry_fill_price || p.entry_price);
                  const sl = Number(p.stop_loss);
                  const tp = Number(p.take_profit);
                  const qty = Number(p.quantity);
                  const upnl = Number(p.unrealized_pnl || 0);
                  const isLong = p.direction === 'LONG';

                  // Estimated liquidation for isolated 5x:
                  // Long: liq ≈ entry * (1 - 1/leverage + maint_margin_rate)
                  // Short: liq ≈ entry * (1 + 1/leverage - maint_margin_rate)
                  const leverage = 5;
                  const mmRate = 0.004; // 0.4% maint margin for most contracts
                  const liqPrice = isLong
                    ? entry * (1 - 1 / leverage + mmRate)
                    : entry * (1 + 1 / leverage - mmRate);
                  const slDistance = isLong ? ((sl - entry) / entry * 100) : ((entry - sl) / entry * 100);
                  const liqDistance = isLong ? ((liqPrice - entry) / entry * 100) : ((entry - liqPrice) / entry * 100);

                  return (
                    <div key={i} className="bg-[#0e0e18] rounded-lg p-4">
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <Badge color={isLong ? '#22c55e' : '#ef4444'}>{p.direction}</Badge>
                          <span className="font-semibold text-sm">{p.symbol || 'BTCUSDT'}</span>
                          <span className="text-xs text-gray-500">{p.strategy?.replace(/_/g, ' ')}</span>
                        </div>
                        <div className={`font-bold ${upnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}
                        </div>
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
                        <div>
                          <div className="text-gray-500 mb-0.5">Entry</div>
                          <div className="font-mono">${entry.toLocaleString()}</div>
                        </div>
                        <div>
                          <div className="text-gray-500 mb-0.5">Stop Loss</div>
                          <div className="font-mono text-red-400">${sl.toLocaleString()} <span className="text-gray-600">({slDistance.toFixed(1)}%)</span></div>
                        </div>
                        <div>
                          <div className="text-gray-500 mb-0.5">Take Profit</div>
                          <div className="font-mono text-green-400">${tp.toLocaleString()}</div>
                        </div>
                        <div>
                          <div className="text-gray-500 mb-0.5">Est. Liquidation</div>
                          <div className="font-mono text-orange-400">${liqPrice.toLocaleString('en-US', { maximumFractionDigits: 0 })} <span className="text-gray-600">({liqDistance.toFixed(1)}%)</span></div>
                        </div>
                        <div>
                          <div className="text-gray-500 mb-0.5">Qty / Notional</div>
                          <div className="font-mono">{qty.toFixed(5)} <span className="text-gray-600">(${(qty * entry).toFixed(0)})</span></div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* ═══ BACKTEST TAB ═══ */}
      {tab === 'backtest' && (
        <Card>
          <div className="text-sm font-semibold mb-4">Backtest history (simulated)</div>
          {data?.btTrades?.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm whitespace-nowrap">
                <thead>
                  <tr className="text-gray-500 text-xs uppercase tracking-wider">
                    <th className="text-left pb-3 pr-3">Time</th>
                    <th className="text-left pb-3 pr-3">Dir</th>
                    <th className="text-left pb-3 pr-3">Strategy</th>
                    <th className="text-right pb-3 pr-3">Entry</th>
                    <th className="text-right pb-3 pr-3">Exit</th>
                    <th className="text-right pb-3 pr-3">PnL</th>
                    <th className="text-left pb-3">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {data.btTrades.map((t: any) => (
                    <tr key={t.id} className="border-t border-[#1e1e2e] hover:bg-[#1a1a24]">
                      <td className="py-2 pr-3 text-gray-400 text-xs">
                        {t.entry_time ? new Date(t.entry_time).toLocaleDateString() : ''}
                      </td>
                      <td className="py-2 pr-3">
                        <Badge color={t.direction === 'LONG' ? '#22c55e' : '#ef4444'}>{t.direction}</Badge>
                      </td>
                      <td className="py-2 pr-3 text-gray-300 text-xs">{t.strategy}</td>
                      <td className="py-2 pr-3 text-right">${Number(t.entry_price).toLocaleString()}</td>
                      <td className="py-2 pr-3 text-right">${Number(t.exit_price).toLocaleString()}</td>
                      <td className={`py-2 pr-3 text-right ${Number(t.pnl) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        ${Number(t.pnl).toFixed(2)}
                      </td>
                      <td className="py-2 text-xs text-gray-400">{t.exit_reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-12 text-gray-500">
              <p>No backtest runs yet</p>
              <p className="text-xs mt-1">Run with TRADING_MODE=backtest to generate</p>
            </div>
          )}
        </Card>
      )}

      <div className="mt-8 text-center text-xs text-gray-600">
        v4 · Binance USDM Futures · ML Filter · Correlation Manager · Kelly Sizing
      </div>
    </div>
  );
}
