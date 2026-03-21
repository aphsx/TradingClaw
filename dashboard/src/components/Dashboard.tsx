'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell
} from 'recharts';
import {
  TrendingUp, Activity, DollarSign, Target, ShieldAlert,
  RefreshCw, Eye, Zap, Radio, ExternalLink
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

export default function Dashboard({ data }: { data: any }) {
  const [tab, setTab] = useState<'live' | 'positions' | 'backtest'>('live');
  const [liveData, setLiveData] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Auto-refresh positions every 10s
  const fetchLive = useCallback(async () => {
    try {
      const [posRes, statsRes] = await Promise.all([
        fetch('/api/positions').then(r => r.json()),
        fetch('/api/stats?source=LIVE').then(r => r.json()),
      ]);
      setLiveData({ positions: posRes, stats: statsRes });
    } catch {}
  }, []);

  useEffect(() => {
    fetchLive();
    const interval = setInterval(fetchLive, 10000);
    return () => clearInterval(interval);
  }, [fetchLive]);

  const refresh = async () => {
    setRefreshing(true);
    await fetchLive();
    setTimeout(() => setRefreshing(false), 500);
  };

  // Live stats from DB (closed trades)
  const trades = data?.liveTrades || [];
  const totalTrades = trades.length;
  const wins = trades.filter((t: any) => Number(t.pnl) > 0).length;
  const winRate = totalTrades > 0 ? ((wins / totalTrades) * 100).toFixed(1) : '—';
  const totalPnl = trades.reduce((s: number, t: any) => s + Number(t.pnl), 0);
  const totalFees = trades.reduce((s: number, t: any) => s + Number(t.total_fees || 0), 0);

  // Live monitor state
  const monitor = liveData?.positions?.monitor || {};
  const regime = monitor.regime || {};
  const openPositions = liveData?.positions?.open_positions || data?.openPositions || [];
  const engineStatus = monitor.status?.status || 'unknown';

  const REGIME_COLORS: Record<string, string> = {
    Trending: '#22c55e', Ranging: '#3b82f6', Volatile: '#f59e0b'
  };

  const pnlData = trades.map((t: any, i: number) => ({
    idx: i + 1, pnl: Number(Number(t.pnl).toFixed(2)),
  }));

  return (
    <div className="min-h-screen p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Regime Detection Trading System</h1>
          <p className="text-sm text-gray-500">BTCUSDT · Binance · Real-time Monitor</p>
        </div>
        <div className="flex items-center gap-3">
          {/* Engine status */}
          <div className="flex items-center gap-2 bg-[#12121a] border border-[#1e1e2e] rounded-lg px-3 py-2">
            <div className={`w-2 h-2 rounded-full ${
              engineStatus === 'running' ? 'bg-green-400 animate-pulse' :
              engineStatus === 'error' ? 'bg-red-400' : 'bg-gray-500'
            }`} />
            <span className="text-xs text-gray-400">{engineStatus}</span>
          </div>

          {/* Current regime */}
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

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-[#12121a] border border-[#1e1e2e] rounded-lg p-1 w-fit">
        {[
          { key: 'live', label: `Live trades (${totalTrades})` },
          { key: 'positions', label: `Open positions (${openPositions.length})` },
          { key: 'backtest', label: 'Backtest history' },
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
                The engine is {engineStatus === 'running' ? 'running and monitoring for signals' : 'not running yet'}.
                Trades will appear here when the system opens real positions on Binance.
              </p>
            </Card>
          ) : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <Metric label="Net PnL" value={`$${totalPnl.toFixed(2)}`}
                  color={totalPnl >= 0 ? 'text-green-400' : 'text-red-400'} />
                <Metric label="Win Rate" value={`${winRate}%`} sub={`${wins}W / ${totalTrades - wins}L`} />
                <Metric label="Total Fees (actual)" value={`$${totalFees.toFixed(2)}`} color="text-amber-400"
                  sub="From Binance" />
                <Metric label="Trades" value={totalTrades} />
              </div>

              {/* PnL chart */}
              {pnlData.length > 0 && (
                <Card className="mb-6">
                  <div className="text-sm font-semibold mb-4">PnL per trade (real)</div>
                  <ResponsiveContainer width="100%" height={220}>
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

              {/* Trade log with Binance details */}
              <Card>
                <div className="text-sm font-semibold mb-4">Trade log (real Binance orders)</div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm whitespace-nowrap">
                    <thead>
                      <tr className="text-gray-500 text-xs uppercase tracking-wider">
                        <th className="text-left pb-3 pr-3">Time</th>
                        <th className="text-left pb-3 pr-3">Dir</th>
                        <th className="text-left pb-3 pr-3">Strategy</th>
                        <th className="text-right pb-3 pr-3">Fill price</th>
                        <th className="text-right pb-3 pr-3">Exit price</th>
                        <th className="text-right pb-3 pr-3">Qty</th>
                        <th className="text-right pb-3 pr-3">PnL</th>
                        <th className="text-right pb-3 pr-3">Fee (actual)</th>
                        <th className="text-left pb-3 pr-3">Exit</th>
                        <th className="text-left pb-3">Order ID</th>
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
                            {t.entry_commission ? `${Number(t.entry_commission).toFixed(6)}` : '—'}
                            {t.entry_commission_asset ? ` ${t.entry_commission_asset}` : ''}
                            {t.exit_commission ? ` + ${Number(t.exit_commission).toFixed(6)}` : ''}
                          </td>
                          <td className="py-2 pr-3">
                            <span className={`text-xs ${t.exit_reason === 'Take Profit' ? 'text-green-400' : t.exit_reason === 'Stop Loss' ? 'text-red-400' : 'text-gray-400'}`}>
                              {t.exit_reason || '—'}
                            </span>
                          </td>
                          <td className="py-2 text-gray-600 text-xs font-mono">
                            {t.entry_order_id ? `#${t.entry_order_id}` : '—'}
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
            <div className="text-sm font-semibold">Open positions (real-time)</div>
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <Eye size={12} />
              Auto-refresh 10s
              {monitor.last_price && (
                <span className="ml-2">BTC: ${Number(monitor.last_price).toLocaleString()}</span>
              )}
            </div>
          </div>

          {openPositions.length === 0 ? (
            <div className="text-center py-16 text-gray-500">
              <Activity size={40} className="mx-auto mb-3 opacity-30" />
              <p>No open positions</p>
              <p className="text-xs mt-1">
                {engineStatus === 'running' ? 'Engine is running, waiting for signals...' : 'Start the engine to begin trading'}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm whitespace-nowrap">
                <thead>
                  <tr className="text-gray-500 text-xs uppercase tracking-wider">
                    <th className="text-left pb-3">Dir</th>
                    <th className="text-left pb-3">Strategy</th>
                    <th className="text-right pb-3">Entry (fill)</th>
                    <th className="text-right pb-3">Current</th>
                    <th className="text-right pb-3">Unrealized</th>
                    <th className="text-right pb-3">SL</th>
                    <th className="text-right pb-3">TP</th>
                    <th className="text-right pb-3">Qty</th>
                    <th className="text-right pb-3">Entry fee</th>
                    <th className="text-left pb-3">Since</th>
                  </tr>
                </thead>
                <tbody>
                  {openPositions.map((p: any, i: number) => {
                    const upnl = Number(p.unrealized_pnl || 0);
                    const pnlPct = Number(p.pnl_pct || 0);
                    return (
                      <tr key={i} className="border-t border-[#1e1e2e]">
                        <td className="py-3">
                          <Badge color={p.direction === 'LONG' ? '#22c55e' : '#ef4444'}>{p.direction}</Badge>
                        </td>
                        <td className="py-3 text-gray-300 text-xs">{p.strategy?.replace(/_/g, ' ')}</td>
                        <td className="py-3 text-right">
                          ${Number(p.entry_fill_price || p.entry_price).toLocaleString()}
                        </td>
                        <td className="py-3 text-right font-medium">
                          ${Number(p.current_price || 0).toLocaleString()}
                        </td>
                        <td className={`py-3 text-right font-bold ${upnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          ${upnl.toFixed(2)} <span className="text-xs opacity-70">({pnlPct.toFixed(1)}%)</span>
                        </td>
                        <td className="py-3 text-right text-red-400/60">${Number(p.stop_loss).toLocaleString()}</td>
                        <td className="py-3 text-right text-green-400/60">${Number(p.take_profit).toLocaleString()}</td>
                        <td className="py-3 text-right text-gray-400">{Number(p.quantity).toFixed(5)}</td>
                        <td className="py-3 text-right text-xs text-amber-400/50">
                          {p.entry_commission ? `${Number(p.entry_commission).toFixed(6)} ${p.entry_commission_asset || ''}` : '—'}
                        </td>
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

      {/* ═══ BACKTEST TAB ═══ */}
      {tab === 'backtest' && (
        <Card>
          <div className="text-sm font-semibold mb-4">Backtest history (simulated, not real trades)</div>
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
                    <tr key={t.id} className="border-t border-[#1e1e2e]">
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
        v3 · Docker + MySQL + Redis + Binance API · ข้อมูลเทรดจริงจาก Binance เท่านั้น
      </div>
    </div>
  );
}
