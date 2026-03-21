import { NextResponse } from 'next/server';
import { query, redisGet } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const source = searchParams.get('source') || 'LIVE';

  let summary = {};
  let open_count = 0;
  let strategy_stats: any[] = [];
  let monitor = null;
  let equity = null;
  let regime = null;
  const errors: string[] = [];

  // DB queries — non-fatal if DB unavailable
  try {
    const rows: any = await query(
      `SELECT COUNT(*) as total,
              SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
              ROUND(SUM(pnl),2) as total_pnl,
              ROUND(SUM(total_fees),2) as total_fees,
              ROUND(AVG(CASE WHEN pnl > 0 THEN pnl END),2) as avg_win,
              ROUND(AVG(CASE WHEN pnl <= 0 THEN pnl END),2) as avg_loss
       FROM positions WHERE status='CLOSED' AND source=?`, [source]
    );
    summary = rows?.[0] || {};

    const openRows: any = await query(
      `SELECT COUNT(*) as count FROM positions WHERE status='OPEN' AND source=?`, [source]
    );
    open_count = openRows?.[0]?.count || 0;

    const stratRows: any = await query(
      `SELECT strategy,
              COUNT(*) as trades,
              SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) as wins,
              ROUND(SUM(pnl),2) as total_pnl,
              ROUND(AVG(pnl),2) as avg_pnl,
              ROUND(SUM(total_fees),2) as total_fees
       FROM positions WHERE status='CLOSED' AND source=?
       GROUP BY strategy`, [source]
    );
    strategy_stats = stratRows || [];
  } catch (e: any) {
    errors.push(`DB: ${e.message}`);
  }

  // Redis — non-fatal if unavailable
  try {
    monitor = await redisGet('monitor:status');
    equity = await redisGet('monitor:equity');
    regime = await redisGet('monitor:regime');
  } catch (e: any) {
    errors.push(`Redis: ${e.message}`);
  }

  return NextResponse.json({
    source,
    summary,
    open_count,
    strategy_stats,
    monitor,
    equity,
    regime,
    _errors: errors.length > 0 ? errors : undefined,
  });
}
