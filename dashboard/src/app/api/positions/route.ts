import { NextResponse } from 'next/server';
import { query, redisGet, redisSmembers } from '@/lib/db';
import { getEngineHttpUrl } from '@/lib/engine-url';

export const dynamic = 'force-dynamic';

export async function GET() {
  const engineUrl = getEngineHttpUrl();
  let open_positions: any[] = [];
  let monitorStatus = null;
  let equity = null;
  let regime = null;
  let lastPrice = null;
  let margin = null;
  let funding = null;
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
    margin = await redisGet('monitor:margin');
    funding = await redisGet('monitor:funding');

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
                stop_loss, take_profit, risk_reward, confidence
         FROM positions
         WHERE status='OPEN' AND source IN ('LIVE','MANUAL_ADOPTED','MANUAL_IMPORTED')
         ORDER BY entry_time DESC`
      );
      open_positions = dbOpen.map((p: any) => ({ ...p, is_bot: true })) || [];
      source = 'mysql';
    } catch (e: any) {
      errors.push(`DB: ${e.message}`);
    }
  }

  // All Binance positions (bot-managed + manual) — always fetch (non-fatal)
  let binancePositions: any[] = [];
  try {
    const engineRes = await fetch(`${engineUrl}/manual-positions`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(4000),
    }).catch(() => null);

    if (engineRes?.ok) {
      const engineData = await engineRes.json();
      // New http_api.py returns binance_positions directly
      binancePositions = engineData.binance_positions || [];
    } else if (engineRes) {
      errors.push(`Engine HTTP: ${engineRes.status} ${engineRes.statusText || 'error'}`);
    } else {
      errors.push('Engine HTTP: manual-positions unreachable');
    }
  } catch (e: any) {
    errors.push(`Engine HTTP: ${e.message}`);
  }

  return NextResponse.json({
    open_positions,
    binance_positions: binancePositions,   // all actual Binance positions (tagged bot_managed)
    source,
    monitor: {
      status: monitorStatus,
      equity,
      regime,
      last_price: lastPrice,
      margin,
      funding,
    },
    _errors: errors.length > 0 ? errors : undefined,
  });
}
