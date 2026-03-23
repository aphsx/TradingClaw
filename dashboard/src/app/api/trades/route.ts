import { NextResponse } from 'next/server';
import { query } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  try {
    const { searchParams } = new URL(req.url);
    const source = searchParams.get('source') || 'LIVE';
    const limitRaw = parseInt(searchParams.get('limit') || '100', 10);
    const limit = Number.isFinite(limitRaw) ? Math.min(Math.max(limitRaw, 1), 500) : 100;

    const rows = await query(
      `SELECT id, source, symbol, direction, strategy, regime, status,
              entry_price, entry_time, quantity,
              entry_order_id, entry_client_oid, entry_fill_price, entry_fill_qty,
              entry_commission, entry_commission_asset, entry_status,
              exit_price, exit_time, exit_reason,
              exit_order_id, exit_client_oid, exit_fill_price, exit_fill_qty,
              exit_commission, exit_commission_asset, exit_status,
              pnl, pnl_pct, total_fees, stop_loss, take_profit, risk_reward,
              created_at
       FROM positions
       WHERE source = ? AND status = 'CLOSED'
       ORDER BY exit_time DESC
       LIMIT ${limit}`,
      [source]
    );

    return NextResponse.json(rows);
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
