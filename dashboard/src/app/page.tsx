import { query } from '@/lib/db';
import Dashboard from '@/components/Dashboard';

function parseDbJson<T>(value: any, fallback: T): T {
  if (!value) return fallback;
  if (typeof value === 'object') return value as T;
  try {
    return JSON.parse(String(value)) as T;
  } catch {
    return fallback;
  }
}

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
    const latestBtRun = btRun?.[0] || null;
    const btTrades: any = latestBtRun
      ? await query(
          `SELECT *
           FROM positions
           WHERE source='BACKTEST' AND status='CLOSED' AND run_id=?
           ORDER BY exit_time DESC
           LIMIT 500`,
          [latestBtRun.id]
        )
      : [];
    const btExitReasons: any = latestBtRun
      ? await query(
          `SELECT exit_reason as reason,
                  COUNT(*) as trades,
                  ROUND(SUM(COALESCE(gross_pnl, pnl + total_fees)), 2) as gross_pnl,
                  ROUND(SUM(total_fees), 2) as fees,
                  ROUND(SUM(pnl), 2) as net_pnl
           FROM positions
           WHERE source='BACKTEST' AND status='CLOSED' AND run_id=?
           GROUP BY exit_reason
           ORDER BY trades DESC, reason ASC`,
          [latestBtRun.id]
        )
      : [];

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
      btRun: latestBtRun
        ? {
            ...latestBtRun,
            results_json: parseDbJson(latestBtRun.results_json, {}),
            config_json: parseDbJson(latestBtRun.config_json, {}),
            validation_json: parseDbJson(latestBtRun.validation_json, {}),
          }
        : null,
      btTrades: btTrades || [],
      btExitReasons: btExitReasons || [],
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
