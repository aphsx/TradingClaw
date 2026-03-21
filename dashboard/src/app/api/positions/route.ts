import { NextResponse } from 'next/server';
import { query, redisGet, redisSmembers } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    // 1. Try Redis first (real-time, includes unrealized PnL)
    const ids = await redisSmembers('pos:open_ids');
    const redisPositions: any[] = [];

    for (const id of ids) {
      const data = await redisGet(`pos:open:${id}`);
      if (data) {
        redisPositions.push({ id: Number(id), ...data, _from: 'redis' });
      }
    }

    // 2. Also get from MySQL (source of truth)
    const dbOpen: any = await query(
      `SELECT id, source, symbol, direction, strategy, regime, status,
              entry_price, entry_time, quantity,
              entry_order_id, entry_fill_price, entry_commission, entry_commission_asset,
              stop_loss, take_profit, risk_reward
       FROM positions WHERE status='OPEN' AND source='LIVE'
       ORDER BY entry_time DESC`
    );

    // 3. Get monitor status from Redis
    const monitorStatus = await redisGet('monitor:status');
    const equity = await redisGet('monitor:equity');
    const regime = await redisGet('monitor:regime');
    const lastPrice = await redisGet('monitor:last_price');

    return NextResponse.json({
      open_positions: redisPositions.length > 0 ? redisPositions : dbOpen,
      source: redisPositions.length > 0 ? 'redis' : 'mysql',
      monitor: {
        status: monitorStatus,
        equity,
        regime,
        last_price: lastPrice,
      },
    });
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
