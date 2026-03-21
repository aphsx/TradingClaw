import { NextResponse } from 'next/server';
import crypto from 'crypto';

export const dynamic = 'force-dynamic';

const BASE_URL = 'https://api.binance.com';

function sign(params: Record<string, string | number>, secret: string): string {
  const query = new URLSearchParams(params as any).toString();
  const sig = crypto.createHmac('sha256', secret).update(query).digest('hex');
  return `${query}&signature=${sig}`;
}

export async function GET() {
  const apiKey = process.env.BINANCE_API_KEY;
  const secretKey = process.env.BINANCE_SECRET_KEY;

  if (!apiKey || !secretKey) {
    return NextResponse.json({ error: 'Binance API keys not configured' }, { status: 500 });
  }

  try {
    const params = { timestamp: Date.now(), recvWindow: 10000 };
    const signed = sign(params, secretKey);

    const res = await fetch(`${BASE_URL}/api/v3/account?${signed}`, {
      headers: { 'X-MBX-APIKEY': apiKey },
      cache: 'no-store',
    });

    if (!res.ok) {
      const err = await res.json();
      return NextResponse.json({ error: err.msg || 'Binance error' }, { status: res.status });
    }

    const data = await res.json();

    // Extract all non-zero balances
    const balances: Record<string, { free: number; locked: number; total: number }> = {};
    for (const b of data.balances ?? []) {
      const free = parseFloat(b.free);
      const locked = parseFloat(b.locked);
      if (free > 0 || locked > 0) {
        balances[b.asset] = { free, locked, total: free + locked };
      }
    }

    // USDT is the main quote currency
    const usdt = balances['USDT'] ?? { free: 0, locked: 0, total: 0 };

    return NextResponse.json({
      usdt_free: usdt.free,
      usdt_locked: usdt.locked,
      usdt_total: usdt.total,
      balances,
      can_trade: data.canTrade ?? false,
      account_type: data.accountType ?? '',
    });
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
