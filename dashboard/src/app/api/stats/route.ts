import { NextResponse } from 'next/server';
import { query } from '@/lib/db';

export async function GET() {
  try {
    const runs: any = await query(
      'SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT 1'
    );
    const openPos: any = await query(
      "SELECT COUNT(*) as count FROM positions WHERE status='OPEN'"
    );
    const totalTrades: any = await query(
      'SELECT COUNT(*) as total, SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins, SUM(pnl) as total_pnl, SUM(total_fees) as total_fees FROM positions WHERE status=\'CLOSED\''
    );
    const lastEquity: any = await query(
      'SELECT * FROM equity_curve ORDER BY timestamp DESC LIMIT 1'
    );

    return NextResponse.json({
      latest_run: runs[0] || null,
      open_positions: openPos[0]?.count || 0,
      trade_summary: totalTrades[0] || {},
      current_equity: lastEquity[0] || null,
    });
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
