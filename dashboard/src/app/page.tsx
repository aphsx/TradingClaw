import { query } from '@/lib/db';
import Dashboard from '@/components/Dashboard';

async function getData() {
  try {
    const runs: any = await query('SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT 1');
    const trades: any = await query('SELECT * FROM positions WHERE status=\'CLOSED\' ORDER BY entry_time DESC LIMIT 200');
    const openPos: any = await query('SELECT * FROM positions WHERE status=\'OPEN\' ORDER BY entry_time DESC');
    const equityCurve: any = await query('SELECT timestamp, equity, drawdown_pct FROM equity_curve ORDER BY timestamp ASC');
    const regimes: any = await query('SELECT timestamp, regime_name, confidence FROM regimes ORDER BY timestamp DESC LIMIT 200');
    const regimeDist: any = await query('SELECT regime_name, COUNT(*) as count FROM regimes GROUP BY regime_name');
    const latestRegime: any = await query('SELECT * FROM regimes ORDER BY timestamp DESC LIMIT 1');
    const strategyStats: any = await query(`
      SELECT strategy,
        COUNT(*) as trades,
        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
        ROUND(SUM(pnl), 2) as total_pnl,
        ROUND(AVG(pnl), 2) as avg_pnl
      FROM positions WHERE status='CLOSED'
      GROUP BY strategy
    `);

    return {
      run: runs[0] || null,
      trades,
      openPositions: openPos,
      equityCurve: equityCurve.map((e: any) => ({
        ...e,
        timestamp: new Date(e.timestamp).toISOString(),
        equity: Number(e.equity),
        drawdown_pct: Number(e.drawdown_pct),
      })),
      regimes: regimes.reverse(),
      regimeDist,
      latestRegime: latestRegime[0] || null,
      strategyStats,
    };
  } catch (e) {
    return null;
  }
}

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export default async function Home() {
  const data = await getData();

  if (!data || !data.run) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold mb-4">Regime Trader Dashboard</h1>
          <p className="text-gray-400 mb-6">No backtest data yet.</p>
          <div className="bg-[#12121a] border border-[#1e1e2e] rounded-xl p-6 max-w-md mx-auto text-left text-sm text-gray-300">
            <p className="mb-2">Run a backtest first:</p>
            <code className="block bg-black/40 p-3 rounded-lg text-green-400">
              docker compose up
            </code>
          </div>
        </div>
      </div>
    );
  }

  return <Dashboard data={data} />;
}
