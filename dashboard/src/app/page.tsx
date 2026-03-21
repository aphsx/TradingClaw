import { query } from '@/lib/db';
import Dashboard from '@/components/Dashboard';

async function getData() {
  try {
    // LIVE trades (only shows actual trades, never backtest)
    const liveTrades: any = await query(
      `SELECT * FROM positions WHERE source='LIVE' AND status='CLOSED' ORDER BY exit_time DESC LIMIT 200`
    );
    const openPos: any = await query(
      `SELECT * FROM positions WHERE source='LIVE' AND status='OPEN' ORDER BY entry_time DESC`
    );
    const liveCount: any = await query(
      `SELECT COUNT(*) as c FROM positions WHERE source='LIVE'`
    );

    // Backtest trades (separate)
    const btRun: any = await query(
      `SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT 1`
    );
    const btTrades: any = await query(
      `SELECT * FROM positions WHERE source='BACKTEST' AND status='CLOSED' ORDER BY exit_time DESC LIMIT 200`
    );

    // Strategy stats (live only)
    const stratStats: any = await query(
      `SELECT strategy, COUNT(*) as trades,
              SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) as wins,
              ROUND(SUM(pnl),2) as total_pnl,
              ROUND(AVG(pnl),2) as avg_pnl,
              ROUND(SUM(total_fees),2) as fees
       FROM positions WHERE source='LIVE' AND status='CLOSED' GROUP BY strategy`
    );

    return {
      liveTrades: liveTrades || [],
      openPositions: openPos || [],
      liveTradeCount: liveCount?.[0]?.c || 0,
      btRun: btRun?.[0] || null,
      btTrades: btTrades || [],
      strategyStats: stratStats || [],
    };
  } catch (e) {
    console.error('getData error:', e);
    return null;
  }
}

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export default async function Home() {
  const data = await getData();
  return <Dashboard data={data} />;
}
