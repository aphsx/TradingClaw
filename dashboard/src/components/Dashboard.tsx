'use client';

import { useState } from 'react';
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell
} from 'recharts';
import {
  TrendingUp, TrendingDown, Activity, DollarSign,
  Target, ShieldAlert, BarChart3, Zap, RefreshCw
} from 'lucide-react';

const REGIME_COLORS: Record<string, string> = {
  Trending: '#22c55e',
  Ranging: '#3b82f6',
  Volatile: '#f59e0b',
};

const DIRECTION_COLORS: Record<string, string> = {
  LONG: '#22c55e',
  SHORT: '#ef4444',
};

function MetricCard({ label, value, sub, icon: Icon, color }: any) {
  return (
    <div className="bg-[#12121a] border border-[#1e1e2e] rounded-xl p-5">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] uppercase tracking-wider text-gray-500">{label}</span>
        {Icon && <Icon size={16} className="text-gray-600" />}
      </div>
      <div className={`text-2xl font-bold ${color || 'text-white'}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  );
}

export default function Dashboard({ data }: { data: any }) {
  const [tab, setTab] = useState<'overview' | 'trades' | 'positions'>('overview');
  const run = data.run;
  const results = run?.results_json ? (typeof run.results_json === 'string' ? JSON.parse(run.results_json) : run.results_json) : {};
  const trading = results?.trading || {};
  const config = results?.config || {};

  const totalTrades = data.trades?.length || 0;
  const wins = data.trades?.filter((t: any) => Number(t.pnl) > 0).length || 0;
  const winRate = totalTrades > 0 ? ((wins / totalTrades) * 100).toFixed(1) : '0';
  const totalPnl = data.trades?.reduce((s: number, t: any) => s + Number(t.pnl), 0) || 0;
  const totalFees = data.trades?.reduce((s: number, t: any) => s + Number(t.total_fees), 0) || 0;
  const maxDD = trading.max_drawdown || '0%';
  const profitFactor = trading.profit_factor || 0;
  const sharpe = trading.sharpe_approx || 0;
  const finalCap = Number(run?.final_capital || 10000);
  const initCap = Number(run?.initial_capital || 10000);
  const returnPct = ((finalCap - initCap) / initCap * 100).toFixed(2);

  // PnL data for bar chart
  const pnlData = data.trades?.map((t: any, i: number) => ({
    idx: i + 1,
    pnl: Number(Number(t.pnl).toFixed(2)),
    strategy: t.strategy,
  })) || [];

  // Regime pie data
  const regimePie = data.regimeDist?.map((r: any) => ({
    name: r.regime_name,
    value: Number(r.count),
    color: REGIME_COLORS[r.regime_name] || '#666',
  })) || [];

  return (
    <div className="min-h-screen p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Regime Detection Trading System</h1>
          <p className="text-sm text-gray-500">
            {run?.symbol} · {run?.timeframe} · Backtest #{run?.id}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {data.latestRegime && (
            <div className="flex items-center gap-2 bg-[#12121a] border border-[#1e1e2e] rounded-lg px-4 py-2">
              <div
                className="w-2 h-2 rounded-full animate-pulse"
                style={{ background: REGIME_COLORS[data.latestRegime.regime_name] }}
              />
              <span className="text-sm font-medium">{data.latestRegime.regime_name}</span>
              <span className="text-xs text-gray-500">
                {(Number(data.latestRegime.confidence) * 100).toFixed(0)}%
              </span>
            </div>
          )}
          <button
            onClick={() => window.location.reload()}
            className="p-2 rounded-lg bg-[#12121a] border border-[#1e1e2e] hover:bg-[#1a1a24] transition"
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-[#12121a] border border-[#1e1e2e] rounded-lg p-1 w-fit">
        {(['overview', 'trades', 'positions'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition capitalize ${
              tab === t ? 'bg-[#1e1e2e] text-white' : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            {t === 'positions' ? `Open (${data.openPositions?.length || 0})` : t}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <>
          {/* Key Metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <MetricCard label="Net Return" value={`${returnPct}%`}
              sub={`$${totalPnl.toFixed(2)} on $${initCap.toLocaleString()}`}
              icon={TrendingUp} color={totalPnl >= 0 ? 'text-green-400' : 'text-red-400'} />
            <MetricCard label="Win Rate" value={`${winRate}%`}
              sub={`${wins}W / ${totalTrades - wins}L of ${totalTrades}`}
              icon={Target} />
            <MetricCard label="Profit Factor" value={profitFactor}
              icon={BarChart3} color={profitFactor >= 1 ? 'text-green-400' : 'text-red-400'} />
            <MetricCard label="Max Drawdown" value={maxDD}
              sub={`Limit: ${config.max_drawdown_limit || '15%'}`}
              icon={ShieldAlert} color="text-red-400" />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <MetricCard label="Total Fees" value={`$${totalFees.toFixed(2)}`}
              icon={DollarSign} color="text-amber-400" />
            <MetricCard label="Sharpe Ratio" value={sharpe}
              icon={Activity} color={sharpe > 0 ? 'text-green-400' : 'text-red-400'} />
            <MetricCard label="Avg Duration" value={`${trading.avg_trade_duration_hours || 0}h`}
              icon={Zap} color="text-blue-400" />
            <MetricCard label="Final Capital" value={`$${finalCap.toLocaleString()}`}
              icon={DollarSign} color={totalPnl >= 0 ? 'text-green-400' : 'text-red-400'} />
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
            {/* Equity Curve */}
            <div className="bg-[#12121a] border border-[#1e1e2e] rounded-xl p-5">
              <h3 className="text-sm font-semibold mb-4">Equity curve</h3>
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={data.equityCurve}>
                  <defs>
                    <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
                  <XAxis dataKey="timestamp" hide />
                  <YAxis stroke="#333" tick={{ fill: '#666', fontSize: 11 }}
                    tickFormatter={(v) => `$${(v / 1000).toFixed(1)}k`} />
                  <Tooltip
                    contentStyle={{ background: '#12121a', border: '1px solid #1e1e2e', borderRadius: 8 }}
                    labelStyle={{ color: '#666' }}
                    formatter={(v: number) => [`$${v.toFixed(2)}`, 'Equity']}
                  />
                  <Area type="monotone" dataKey="equity" stroke="#8b5cf6" fill="url(#eqGrad)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            {/* PnL per Trade */}
            <div className="bg-[#12121a] border border-[#1e1e2e] rounded-xl p-5">
              <h3 className="text-sm font-semibold mb-4">PnL per trade</h3>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={pnlData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
                  <XAxis dataKey="idx" stroke="#333" tick={{ fill: '#666', fontSize: 10 }} />
                  <YAxis stroke="#333" tick={{ fill: '#666', fontSize: 11 }}
                    tickFormatter={(v) => `$${v}`} />
                  <Tooltip
                    contentStyle={{ background: '#12121a', border: '1px solid #1e1e2e', borderRadius: 8 }}
                    formatter={(v: number, _: any, p: any) => [
                      `$${v.toFixed(2)}`,
                      p.payload.strategy,
                    ]}
                  />
                  <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
                    {pnlData.map((entry: any, i: number) => (
                      <Cell key={i} fill={entry.pnl >= 0 ? '#22c55e' : '#ef4444'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Bottom Row: Regime + Strategy */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
            {/* Regime Distribution */}
            <div className="bg-[#12121a] border border-[#1e1e2e] rounded-xl p-5">
              <h3 className="text-sm font-semibold mb-4">Regime distribution</h3>
              <div className="flex items-center gap-6">
                <ResponsiveContainer width={140} height={140}>
                  <PieChart>
                    <Pie data={regimePie} cx="50%" cy="50%" innerRadius={40} outerRadius={65}
                      dataKey="value" stroke="none">
                      {regimePie.map((entry: any, i: number) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex-1 space-y-3">
                  {regimePie.map((r: any) => {
                    const total = regimePie.reduce((s: number, x: any) => s + x.value, 0);
                    const pct = total > 0 ? ((r.value / total) * 100).toFixed(1) : '0';
                    return (
                      <div key={r.name} className="flex items-center gap-3">
                        <div className="w-3 h-3 rounded-full" style={{ background: r.color }} />
                        <span className="text-sm flex-1">{r.name}</span>
                        <span className="text-sm text-gray-400">{r.value} bars</span>
                        <span className="text-sm font-medium">{pct}%</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Strategy Breakdown */}
            <div className="bg-[#12121a] border border-[#1e1e2e] rounded-xl p-5">
              <h3 className="text-sm font-semibold mb-4">Strategy breakdown</h3>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs uppercase tracking-wider">
                    <th className="text-left pb-3">Strategy</th>
                    <th className="text-right pb-3">Trades</th>
                    <th className="text-right pb-3">Win Rate</th>
                    <th className="text-right pb-3">PnL</th>
                    <th className="text-right pb-3">Avg</th>
                  </tr>
                </thead>
                <tbody>
                  {data.strategyStats?.map((s: any) => {
                    const wr = s.trades > 0 ? ((s.wins / s.trades) * 100).toFixed(1) : '0';
                    const color = s.strategy.includes('Trend') ? 'text-green-400'
                      : s.strategy.includes('Range') ? 'text-blue-400' : 'text-amber-400';
                    return (
                      <tr key={s.strategy} className="border-t border-[#1e1e2e]">
                        <td className={`py-3 font-medium ${color}`}>{s.strategy.replace(/_/g, ' ')}</td>
                        <td className="text-right py-3 text-gray-300">{s.trades}</td>
                        <td className="text-right py-3 text-gray-300">{wr}%</td>
                        <td className={`text-right py-3 font-medium ${Number(s.total_pnl) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          ${Number(s.total_pnl).toFixed(2)}
                        </td>
                        <td className={`text-right py-3 ${Number(s.avg_pnl) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          ${Number(s.avg_pnl).toFixed(2)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {tab === 'trades' && (
        <div className="bg-[#12121a] border border-[#1e1e2e] rounded-xl p-5 overflow-x-auto">
          <h3 className="text-sm font-semibold mb-4">Trade log ({totalTrades} trades)</h3>
          <table className="w-full text-sm whitespace-nowrap">
            <thead>
              <tr className="text-gray-500 text-xs uppercase tracking-wider">
                <th className="text-left pb-3 pr-4">Time</th>
                <th className="text-left pb-3 pr-4">Direction</th>
                <th className="text-left pb-3 pr-4">Strategy</th>
                <th className="text-right pb-3 pr-4">Entry</th>
                <th className="text-right pb-3 pr-4">Exit</th>
                <th className="text-right pb-3 pr-4">Qty</th>
                <th className="text-right pb-3 pr-4">PnL</th>
                <th className="text-right pb-3 pr-4">Fees</th>
                <th className="text-left pb-3">Exit Reason</th>
              </tr>
            </thead>
            <tbody>
              {data.trades?.map((t: any, i: number) => (
                <tr key={i} className="border-t border-[#1e1e2e] hover:bg-[#1a1a24] transition">
                  <td className="py-2.5 pr-4 text-gray-400">
                    {new Date(t.entry_time).toLocaleDateString('en', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </td>
                  <td className="py-2.5 pr-4">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${
                      t.direction === 'LONG' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                    }`}>{t.direction}</span>
                  </td>
                  <td className="py-2.5 pr-4 text-gray-300">{t.strategy?.replace(/_/g, ' ')}</td>
                  <td className="py-2.5 pr-4 text-right text-gray-300">${Number(t.entry_price).toLocaleString()}</td>
                  <td className="py-2.5 pr-4 text-right text-gray-300">${Number(t.exit_price).toLocaleString()}</td>
                  <td className="py-2.5 pr-4 text-right text-gray-400">{Number(t.quantity).toFixed(5)}</td>
                  <td className={`py-2.5 pr-4 text-right font-medium ${Number(t.pnl) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ${Number(t.pnl).toFixed(2)}
                  </td>
                  <td className="py-2.5 pr-4 text-right text-amber-400/70">${Number(t.total_fees).toFixed(2)}</td>
                  <td className="py-2.5">
                    <span className={`text-xs ${
                      t.exit_reason === 'Take Profit' ? 'text-green-400' :
                      t.exit_reason === 'Stop Loss' ? 'text-red-400' : 'text-gray-400'
                    }`}>{t.exit_reason}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'positions' && (
        <div className="bg-[#12121a] border border-[#1e1e2e] rounded-xl p-5">
          <h3 className="text-sm font-semibold mb-4">
            Open positions ({data.openPositions?.length || 0})
          </h3>
          {data.openPositions?.length > 0 ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs uppercase tracking-wider">
                  <th className="text-left pb-3">Symbol</th>
                  <th className="text-left pb-3">Direction</th>
                  <th className="text-left pb-3">Strategy</th>
                  <th className="text-right pb-3">Entry</th>
                  <th className="text-right pb-3">SL</th>
                  <th className="text-right pb-3">TP</th>
                  <th className="text-right pb-3">Qty</th>
                  <th className="text-right pb-3">Since</th>
                </tr>
              </thead>
              <tbody>
                {data.openPositions.map((p: any, i: number) => (
                  <tr key={i} className="border-t border-[#1e1e2e]">
                    <td className="py-3 font-medium">{p.symbol}</td>
                    <td className="py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                        p.direction === 'LONG' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                      }`}>{p.direction}</span>
                    </td>
                    <td className="py-3 text-gray-300">{p.strategy?.replace(/_/g, ' ')}</td>
                    <td className="py-3 text-right">${Number(p.entry_price).toLocaleString()}</td>
                    <td className="py-3 text-right text-red-400">${Number(p.stop_loss).toLocaleString()}</td>
                    <td className="py-3 text-right text-green-400">${Number(p.take_profit).toLocaleString()}</td>
                    <td className="py-3 text-right text-gray-400">{Number(p.quantity).toFixed(5)}</td>
                    <td className="py-3 text-right text-gray-500">
                      {new Date(p.entry_time).toLocaleDateString('en', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="text-center py-12 text-gray-500">
              <Activity size={40} className="mx-auto mb-3 opacity-30" />
              <p>No open positions</p>
              <p className="text-xs mt-1">Positions will appear here during live trading</p>
            </div>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="mt-8 text-center text-xs text-gray-600">
        Regime Detection Trading System v2 · Docker + Next.js + MySQL · For educational purposes only
      </div>
    </div>
  );
}
