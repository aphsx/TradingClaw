import { NextResponse } from 'next/server';
import { query, redisGet, redisSmembers } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET() {
  let open_positions: any[] = [];
  let monitorStatus = null;
  let equity = null;
  let regime = null;
  let lastPrice = null;
  let source = 'none';
  const errors: string[] = [];

  // Redis positions — non-fatal
  try {
    const ids = await redisSmembers('pos:open_ids');
    const redisPositions: any[] = [];
    for (const id of ids) {
      const data = await redisGet(`pos:open:${id}`);
      if (data) redisPositions.push({ id: Number(id), ...data, _from: 'redis', is_bot: true });
    }

    monitorStatus = await redisGet('monitor:status');
    equity = await redisGet('monitor:equity');
    regime = await redisGet('monitor:regime');
    lastPrice = await redisGet('monitor:last_price');

    if (redisPositions.length > 0) {
      open_positions = redisPositions;
      source = 'redis';
    }
  } catch (e: any) {
    errors.push(`Redis: ${e.message}`);
  }

  // DB positions fallback — non-fatal
  if (open_positions.length === 0) {
    try {
      const dbOpen: any = await query(
        `SELECT id, source, symbol, direction, strategy, regime, status,
                entry_price, entry_time, quantity,
                entry_order_id, entry_fill_price, entry_commission, entry_commission_asset,
                stop_loss, take_profit, risk_reward
         FROM positions WHERE status='OPEN' AND source='LIVE'
         ORDER BY entry_time DESC`
      );
      open_positions = dbOpen.map((p: any) => ({ ...p, is_bot: true })) || [];
      source = 'mysql';
    } catch (e: any) {
      errors.push(`DB: ${e.message}`);
    }
  }

  // Manual positions from Binance — always fetch (non-fatal)
  let manualPositions = null;
  try {
    const apiKey = process.env.BINANCE_API_KEY;
    const secretKey = process.env.BINANCE_SECRET_KEY;
    
    if (apiKey && secretKey) {
      // Fetch from trading engine's monitor endpoint
      const manualRes = await fetch('http://localhost:8080/manual-positions', {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      }).catch(() => null);
      
      if (manualRes?.ok) {
        manualPositions = await manualRes.json();
      }
    }
  } catch (e: any) {
    // Silently fail — manual positions are optional
  }

  return NextResponse.json({
    open_positions,
    manual_positions: manualPositions,
    source,
    monitor: {
      status: monitorStatus,
      equity,
      regime,
      last_price: lastPrice,
    },
    _errors: errors.length > 0 ? errors : undefined,
  });
}
