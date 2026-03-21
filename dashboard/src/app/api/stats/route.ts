import { NextResponse } from 'next/server';
import { query, redisGet } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  try {
    const { searchParams } = new URL(req.url);
    const source = searchParams.get('source') || 'LIVE';

    const summary: any = await query(
      `SELECT COUNT(*) as total,
              SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
              ROUND(SUM(pnl),2) as total_pnl,
              ROUND(SUM(total_fees),2) as total_fees,
              ROUND(AVG(CASE WHEN pnl > 0 THEN pnl END),2) as avg_win,
              ROUND(AVG(CASE WHEN pnl <= 0 THEN pnl END),2) as avg_loss
       FROM positions WHERE status='CLOSED' AND source=?`, [source]
    );

    const openCount: any = await query(
      `SELECT COUNT(*) as count FROM positions WHERE status='OPEN' AND source=?`, [source]
    );

    const stratStats: any = await query(
      `SELECT strategy,
              COUNT(*) as trades,
              SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) as wins,
              ROUND(SUM(pnl),2) as total_pnl,
              ROUND(AVG(pnl),2) as avg_pnl,
              ROUND(SUM(total_fees),2) as total_fees
       FROM positions WHERE status='CLOSED' AND source=?
       GROUP BY strategy`, [source]
    );

    const monitor = await redisGet('monitor:status');
    const equity = await redisGet('monitor:equity');
    const regime = await redisGet('monitor:regime');

    return NextResponse.json({
      source,
      summary: summary?.[0] || {},
      open_count: openCount?.[0]?.count || 0,
      strategy_stats: stratStats || [],
      monitor,
      equity,
      regime,
    });
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
