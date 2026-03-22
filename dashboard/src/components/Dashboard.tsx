'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { io } from 'socket.io-client';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell
} from 'recharts';
import {
  TrendingUp, Activity, DollarSign, Target, ShieldAlert,
  RefreshCw, Eye, Zap, Radio, ExternalLink, AlertTriangle, X, Bot, Wifi, WifiOff, Download
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

/** Format a UTC timestamp for display in Bangkok time (UTC+7) */
function fmtTime(ts: string | number | undefined): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString('th-TH', {
      timeZone: 'Asia/Bangkok',
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
      hour12: false,
    });
  } catch { return String(ts); }
}

export default function Dashboard({ data }: { data: any }) {
  const [tab, setTab] = useState<'live' | 'positions' | 'futures' | 'backtest'>('live');
  const [liveData, setLiveData] = useState<any>(null);
  const [balanceData, setBalanceData] = useState<any>(null);
  const [balanceError, setBalanceError] = useState<string | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [socketConnected, setSocketConnected] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null); // pos id being closed/adopted

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
        // expired=true → API key expired, show actionable message
        const msg = balRes.expired
          ? '⚠️ API Key หมดอายุ — ไปที่ testnet.binancefuture.com → API Management → สร้าง key ใหม่ แล้วอัพเดท .env'
          : `${balRes.error}${balRes.binance_code ? ` (${balRes.binance_code})` : ''}`;
        setBalanceError(msg);
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

  // ── Socket.IO — real-time price / position updates ──────────────────────
  useEffect(() => {
    const SOCKET_URL = process.env.NEXT_PUBLIC_SOCKET_URL || 'http://localhost:8080';
    const socket = io(SOCKET_URL, {
      transports: ['websocket', 'polling'],
      reconnectionAttempts: 5,       // stop spamming after 5 tries
      reconnectionDelay: 3000,       // 3s between retries
      reconnectionDelayMax: 15000,   // cap at 15s
      timeout: 5000,
    });
    socket.on('connect',       () => setSocketConnected(true));
    socket.on('disconnect',    () => setSocketConnected(false));
    socket.on('connect_error', () => setSocketConnected(false));

    // Live position updates (open / update / close)
    socket.on('position_update', (msg: any) => {
      const { event, data: d } = msg;
      setLiveData((prev: any) => {
        if (!prev?.positions) return prev;
        let positions: any[] = prev.positions.open_positions || [];
        if (event === 'open')   positions = [...positions, d];
        if (event === 'close')  positions = positions.filter((p: any) => p.id !== d.id);
        if (event === 'update') positions = positions.map((p: any) => p.id === d.id ? { ...p, ...d } : p);
        return { ...prev, positions: { ...prev.positions, open_positions: positions } };
      });
    });

    // Equity / PnL snapshot
    socket.on('equity_update', (msg: any) => {
      setLiveData((prev: any) => {
        if (!prev?.positions) return prev;
        return { ...prev, positions: { ...prev.positions, monitor: { ...prev.positions.monitor, equity: msg.data } } };
      });
    });

    // Regime change
    socket.on('regime_update', (msg: any) => {
      setLiveData((prev: any) => {
        if (!prev?.positions) return prev;
        return { ...prev, positions: { ...prev.positions, monitor: { ...prev.positions.monitor, regime: msg.data } } };
      });
    });

    return () => { socket.disconnect(); };
  }, []);

  const refresh = async () => {
    setRefreshing(true);
    await fetchLive();
    setTimeout(() => setRefreshing(false), 600);
  };

  // ── Close a position via market order ─────────────────────────────────────
  const closePosition = async (pos: any) => {
    const label = `${pos.direction} ${pos.symbol || 'BTCUSDT'}`;
    if (!window.confirm(`ปิด ${label} @ market?\n(ปริมาณ ${Number(pos.quantity).toFixed(5)})`)) return;
    const key = String(pos.id ?? pos.symbol);
    setActionLoading(key);
    try {
      const res = await fetch('/api/close-position', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol:      pos.symbol || 'BTCUSDT',
          direction:   pos.direction,
          quantity:    pos.quantity,
          position_id: pos.id,
        }),
      });
      const d = await res.json();
      if (d.success) { await fetchLive(); }
      else alert('ปิดไม่สำเร็จ: ' + (d.error || 'unknown error'));
    } catch (e: any) { alert('Error: ' + e.message); }
    finally { setActionLoading(null); }
  };

  // ── Adopt a manual Binance position into bot management ───────────────────
  const adoptPosition = async (pos: any) => {
    const entry = pos.entry_price || pos.mark_price;
    const key   = `${pos.symbol}-${pos.direction}`;
    setActionLoading(key);
    try {
      const res = await fetch('/api/adopt-position', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol:      pos.symbol,
          direction:   pos.direction,
          quantity:    pos.quantity,
          entry_price: entry,
        }),
      });
      const d = await res.json();
      if (d.success) {
        alert(`✅ Bot จะดูแล ${pos.direction} ${pos.symbol}\nSL: $${d.stop_loss?.toLocaleString()}  TP1: $${d.take_profit?.toLocaleString()}`);
        await fetchLive();
      } else alert('Adopt ไม่สำเร็จ: ' + (d.error || 'unknown error'));
    } catch (e: any) { alert('Error: ' + e.message); }
    finally { setActionLoading(null); }
  };
  // ── Sync all Binance positions to bot ──────────────────────────────────────
  const syncBinance = async () => {
    if (!window.confirm('Import all unmanaged Binance positions to bot?\nBot will set default SL/TP for each position.')) return;
    setActionLoading('sync');
    try {
      const res = await fetch('/api/sync-binance');
      const d = await res.json();
      if (d.count > 0) {
        alert(`✅ Imported ${d.count} position(s):\n${d.imported.map((p: any) => `${p.direction} ${p.symbol} qty=${p.quantity}`).join('\n')}`);
        await fetchLive();
      } else {
        alert('ℹ️ No unmanaged positions found');
      }
    } catch (e: any) { alert('Error: ' + e.message); }
    finally { setActionLoading(null); }
  };


  const trades = data?.liveTrades || [];
  const totalTrades = trades.length;
  const wins = trades.filter((t: any) => Number(t.pnl) > 0).length;
  const winRate = totalTrades > 0 ? ((wins / totalTrades) * 100).toFixed(1) : '—';
  const totalPnl = trades.reduce((s: number, t: any) => s + Number(t.pnl), 0);
  const totalFees = trades.reduce((s: number, t: any) => s + Number(t.total_fees || 0), 0);

  const monitor = liveData?.positions?.monitor || {};
  const regime = monitor.regime || {};
  const openPositions: any[] = liveData?.positions?.open_positions || data?.openPositions || [];
  const engineStatus = monitor.status?.status || 'unknown';

  // All actual Binance futures positions (tagged with bot_managed)
  const binancePositions: any[] = liveData?.positions?.binance_positions || [];
  // Positions opened manually (not yet managed by the bot)
  const botKeys = new Set(openPositions.map((p: any) => `${p.symbol}-${p.direction}`));
  const unmanaged = binancePositions.filter((p: any) => !p.bot_managed && !botKeys.has(`${p.symbol}-${p.direction}`));

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
    'Trending-Up': '#22c55e',
    'Trending-Down': '#ef4444',
    'Ranging': '#3b82f6',
    'Volatile': '#f59e0b',
    'Trending': '#22c55e',  // legacy fallback
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

          {/* Socket.IO indicator */}
          <div className={`flex items-center gap-2 bg-[#12121a] border rounded-lg px-3 py-2 ${socketConnected ? 'border-green-900/40' : 'border-[#1e1e2e]'}`}
            title={socketConnected ? 'Real-time connected' : 'Real-time disconnected'}>
            {socketConnected
              ? <Wifi size={13} className="text-green-400" />
              : <WifiOff size={13} className="text-gray-600" />}
            <span className={`text-xs ${socketConnected ? 'text-green-400' : 'text-gray-600'}`}>
              {socketConnected ? 'Live' : 'Polling'}
            </span>
          </div>

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

          
          <button 
            onClick={syncBinance} 
            disabled={actionLoading === 'sync'}
            className={`p-2 rounded-lg bg-[#12121a] border border-[#1e1e2e] hover:bg-[#1a1a24] ${actionLoading === 'sync' ? 'opacity-50 cursor-not-allowed' : ''}`}
            title="Sync Binance Positions"
          >
            <Download size={16} />
          </button>

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
                        <th className="text-right pb-3 pr-3" title="Real fill price from CCXT fetchMyTrades">Entry Fill</th>
                        <th className="text-right pb-3 pr-3" title="Real exit fill price from CCXT fetchMyTrades">Exit Fill</th>
                        <th className="text-right pb-3 pr-3">Qty</th>
                        <th className="text-right pb-3 pr-3">PnL</th>
                        <th className="text-right pb-3 pr-3" title="Entry fee + Exit fee (USDT)">Fees</th>
                        <th className="text-left pb-3 pr-3">Reason</th>
                        <th className="text-left pb-3 text-[10px]" title="Entry Order ID / Exit Order ID">Order IDs</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trades.map((t: any) => {
                        const entryFee = Number(t.entry_commission || 0);
                        const exitFee  = Number(t.exit_commission  || 0);
                        const totalFee = Number(t.total_fees || entryFee + exitFee);
                        const feeAsset = t.entry_commission_asset || t.exit_commission_asset || 'USDT';
                        return (
                        <tr key={t.id} className="border-t border-[#1e1e2e] hover:bg-[#1a1a24]">
                          <td className="py-2 pr-3 text-gray-400 text-xs">{fmtTime(t.entry_time)}</td>
                          <td className="py-2 pr-3">
                            <Badge color={t.direction === 'LONG' ? '#22c55e' : '#ef4444'}>{t.direction}</Badge>
                          </td>
                          <td className="py-2 pr-3 text-gray-300 text-xs">{t.strategy?.replace(/_/g, ' ')}</td>
                          {/* Real fill prices from CCXT fetchMyTrades */}
                          <td className="py-2 pr-3 text-right font-mono text-xs">
                            <span title={t.entry_fill_price ? `Real fill: $${Number(t.entry_fill_price).toLocaleString()}` : 'No fill data'}>
                              ${Number(t.entry_fill_price || t.entry_price).toLocaleString()}
                              {t.entry_fill_price && t.entry_fill_price !== t.entry_price && (
                                <span className="text-amber-400/60 ml-1 text-[10px]">≠sig</span>
                              )}
                            </span>
                          </td>
                          <td className="py-2 pr-3 text-right font-mono text-xs">
                            ${Number(t.exit_fill_price || t.exit_price).toLocaleString()}
                          </td>
                          <td className="py-2 pr-3 text-right text-gray-400 text-xs">{Number(t.quantity).toFixed(5)}</td>
                          <td className={`py-2 pr-3 text-right font-medium ${Number(t.pnl) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            ${Number(t.pnl).toFixed(2)}
                          </td>
                          {/* Total fees (entry + exit commission from CCXT) */}
                          <td className="py-2 pr-3 text-right text-amber-400/70 text-xs"
                              title={`Entry: ${entryFee.toFixed(6)} ${feeAsset} | Exit: ${exitFee.toFixed(6)} ${feeAsset}`}>
                            {totalFee > 0 ? `${totalFee.toFixed(4)} ${feeAsset}` : '—'}
                          </td>
                          <td className="py-2 pr-3">
                            <span className={`text-xs ${t.exit_reason === 'Take Profit' ? 'text-green-400' : t.exit_reason === 'Stop Loss' ? 'text-red-400' : 'text-gray-400'}`}>
                              {t.exit_reason || '—'}
                            </span>
                          </td>
                          {/* Order IDs from CCXT */}
                          <td className="py-2 text-[10px] text-gray-600 font-mono">
                            {t.entry_order_id && (
                              <div title="Entry Order ID">↑ {String(t.entry_order_id).slice(-8)}</div>
                            )}
                            {t.exit_order_id && (
                              <div title="Exit Order ID">↓ {String(t.exit_order_id).slice(-8)}</div>
                            )}
                          </td>
                        </tr>
                        );
                      })}
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
        <>
        <Card className="mb-4">
          <div className="flex items-center justify-between mb-4">
            <div className="text-sm font-semibold">
              Bot positions
              <span className="ml-2 text-gray-500 font-normal text-xs">(จัดการโดย bot)</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-gray-500">
              {socketConnected
                ? <><Wifi size={11} className="text-green-400" /><span className="text-green-400">Real-time</span></>
                : <><Eye size={12} /><span>Auto-refresh 10s</span></>}
              {monitor.last_price && (
                <span className="ml-2 font-mono">BTC ${Number(monitor.last_price).toLocaleString()}</span>
              )}
            </div>
          </div>

          {openPositions.length === 0 ? (
            <div className="text-center py-10 text-gray-500">
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
                    <th className="text-right pb-3 pr-4">TP1 / TP2</th>
                    <th className="text-center pb-3 pr-4">TP Status</th>
                    <th className="text-right pb-3 pr-4">Score</th>
                    <th className="text-right pb-3 pr-4">Qty</th>
                    <th className="text-left pb-3 pr-4">Since</th>
                    <th className="text-center pb-3">Close</th>
                  </tr>
                </thead>
                <tbody>
                  {openPositions.map((p: any, i: number) => {
                    const upnl = Number(p.unrealized_pnl || 0);
                    const pnlPct = Number(p.pnl_pct || 0);
                    const score = p.composite_score != null ? Number(p.composite_score) : null;
                    const scoreColor = score === null ? '#666' : score >= 0.6 ? '#22c55e' : score >= 0.4 ? '#86efac' : score <= -0.6 ? '#ef4444' : score <= -0.4 ? '#f87171' : '#9ca3af';
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
                        <td className="py-3 pr-4 text-right">
                          <div className="text-green-400/70">${Number(p.take_profit).toLocaleString()}</div>
                          {p.take_profit_2 ? (
                            <div className="text-green-400/40 text-[10px] mt-0.5">${Number(p.take_profit_2).toLocaleString()}</div>
                          ) : null}
                        </td>
                        <td className="py-3 pr-4 text-center">
                          <div className="flex items-center justify-center gap-1">
                            <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${p.tp1_hit ? 'bg-green-500/20 text-green-400' : 'bg-gray-700/30 text-gray-600'}`}>TP1</span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${p.tp2_hit ? 'bg-green-500/20 text-green-400' : 'bg-gray-700/30 text-gray-600'}`}>TP2</span>
                          </div>
                        </td>
                        <td className="py-3 pr-4 text-right font-mono text-xs" style={{ color: scoreColor }}>
                          {score !== null ? (score >= 0 ? '+' : '') + score.toFixed(2) : '—'}
                        </td>
                        <td className="py-3 pr-4 text-right text-gray-400">{Number(p.quantity).toFixed(5)}</td>
                        <td className="py-3 pr-4 text-gray-500 text-xs">{fmtTime(p.entry_time)}</td>
                        <td className="py-3 text-center">
                          <button
                            onClick={() => closePosition(p)}
                            disabled={actionLoading === String(p.id)}
                            className="p-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/25 text-red-400 transition disabled:opacity-40"
                            title="ปิด position นี้ @ market">
                            <X size={13} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* ── Unmanaged (manual) Binance positions ── */}
        {unmanaged.length > 0 && (
          <Card>
            <div className="flex items-center gap-2 mb-4">
              <Bot size={15} className="text-amber-400" />
              <span className="text-sm font-semibold">Position บน Binance ที่ bot ยังไม่จัดการ</span>
              <span className="text-xs text-amber-400/70 ml-1">({unmanaged.length})</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm whitespace-nowrap">
                <thead>
                  <tr className="text-gray-500 text-xs uppercase tracking-wider">
                    <th className="text-left pb-3 pr-4">Symbol / Dir</th>
                    <th className="text-right pb-3 pr-4">Entry</th>
                    <th className="text-right pb-3 pr-4">Mark</th>
                    <th className="text-right pb-3 pr-4">Unrealized</th>
                    <th className="text-right pb-3 pr-4">Leverage</th>
                    <th className="text-right pb-3 pr-4">Qty</th>
                    <th className="text-center pb-3 pr-4">ให้ Bot จัดการ</th>
                    <th className="text-center pb-3">ปิด</th>
                  </tr>
                </thead>
                <tbody>
                  {unmanaged.map((p: any, i: number) => {
                    const upnl = Number(p.unrealized_pnl || 0);
                    const aKey = `${p.symbol}-${p.direction}`;
                    return (
                      <tr key={i} className="border-t border-[#1e1e2e] hover:bg-[#1a1a24]">
                        <td className="py-3 pr-4">
                          <div className="flex items-center gap-2">
                            <Badge color={p.direction === 'LONG' ? '#22c55e' : '#ef4444'}>{p.direction}</Badge>
                            <span className="text-gray-400 text-xs">{p.symbol}</span>
                          </div>
                        </td>
                        <td className="py-3 pr-4 text-right">${Number(p.entry_price).toLocaleString()}</td>
                        <td className="py-3 pr-4 text-right font-medium">${Number(p.mark_price || 0).toLocaleString()}</td>
                        <td className={`py-3 pr-4 text-right font-bold ${upnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}
                        </td>
                        <td className="py-3 pr-4 text-right text-gray-400">{p.leverage}x</td>
                        <td className="py-3 pr-4 text-right text-gray-400">{Number(p.quantity).toFixed(5)}</td>
                        <td className="py-3 pr-4 text-center">
                          <button
                            onClick={() => adoptPosition(p)}
                            disabled={actionLoading === aKey}
                            className="flex items-center gap-1.5 mx-auto px-3 py-1.5 rounded-lg bg-amber-500/15 hover:bg-amber-500/30 text-amber-400 text-xs font-semibold transition disabled:opacity-40">
                            <Bot size={12} />
                            {actionLoading === aKey ? 'กำลัง...' : 'ให้ Bot จัดการ'}
                          </button>
                        </td>
                        <td className="py-3 text-center">
                          <button
                            onClick={() => closePosition({ ...p, id: undefined })}
                            disabled={actionLoading === aKey}
                            className="p-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/25 text-red-400 transition disabled:opacity-40"
                            title="ปิด @ market">
                            <X size={13} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        )}
        </>
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

                  const fScore = p.composite_score != null ? Number(p.composite_score) : null;
                  const fScoreColor = fScore === null ? '#666' : fScore >= 0.6 ? '#22c55e' : fScore >= 0.4 ? '#86efac' : fScore <= -0.6 ? '#ef4444' : fScore <= -0.4 ? '#f87171' : '#9ca3af';
                  const tp2Val = p.take_profit_2 ? Number(p.take_profit_2) : null;
                  return (
                    <div key={i} className="bg-[#0e0e18] rounded-lg p-4">
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <Badge color={isLong ? '#22c55e' : '#ef4444'}>{p.direction}</Badge>
                          <span className="font-semibold text-sm">{p.symbol || 'BTCUSDT'}</span>
                          <span className="text-xs text-gray-500">{p.strategy?.replace(/_/g, ' ')}</span>
                          {/* TP1 / TP2 hit badges */}
                          <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${p.tp1_hit ? 'bg-green-500/20 text-green-400' : 'bg-gray-700/30 text-gray-600'}`}>TP1</span>
                          <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${p.tp2_hit ? 'bg-green-500/20 text-green-400' : 'bg-gray-700/30 text-gray-600'}`}>TP2</span>
                        </div>
                        <div className="flex items-center gap-3">
                          {fScore !== null && (
                            <div className="text-right">
                              <div className="text-[10px] text-gray-500 mb-0.5">Signal Score</div>
                              <div className="font-mono text-sm font-bold" style={{ color: fScoreColor }}>
                                {fScore >= 0 ? '+' : ''}{fScore.toFixed(2)}
                              </div>
                            </div>
                          )}
                          <div className={`font-bold ${upnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}
                          </div>
                        </div>
                      </div>
                      {/* Close button */}
                      <div className="mt-3 flex justify-end">
                        <button
                          onClick={() => closePosition(p)}
                          disabled={actionLoading === String(p.id)}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/25 text-red-400 text-xs font-semibold transition disabled:opacity-40">
                          <X size={12} />
                          {actionLoading === String(p.id) ? 'กำลังปิด...' : 'ปิด Position @ Market'}
                        </button>
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-6 gap-3 text-xs mt-3">
                        <div>
                          <div className="text-gray-500 mb-0.5">Entry</div>
                          <div className="font-mono">${entry.toLocaleString()}</div>
                        </div>
                        <div>
                          <div className="text-gray-500 mb-0.5">Stop Loss</div>
                          <div className="font-mono text-red-400">${sl.toLocaleString()} <span className="text-gray-600">({slDistance.toFixed(1)}%)</span></div>
                        </div>
                        <div>
                          <div className="text-gray-500 mb-0.5">TP1 (33%)</div>
                          <div className="font-mono text-green-400">${tp.toLocaleString()}</div>
                        </div>
                        {tp2Val && (
                          <div>
                            <div className="text-gray-500 mb-0.5">TP2 (33%)</div>
                            <div className="font-mono text-green-300">${tp2Val.toLocaleString()}</div>
                          </div>
                        )}
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
                      <td className="py-2 pr-3 text-gray-400 text-xs">{fmtTime(t.entry_time)}</td>
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
        v5 · Binance USDM Futures · HMM Regime · Multi-Factor Signals · Partial TP · Portfolio Heat
      </div>
    </div>
  );
}
