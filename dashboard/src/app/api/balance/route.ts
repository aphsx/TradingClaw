import { NextResponse } from 'next/server';
import crypto from 'crypto';

export const dynamic = 'force-dynamic';

const BASE_URL = 'https://api.binance.com';

function sign(queryString: string, secret: string): string {
  return crypto.createHmac('sha256', secret).update(queryString).digest('hex');
}

async function getServerTimeOffset(): Promise<number> {
  try {
    const res = await fetch(`${BASE_URL}/api/v3/time`, { cache: 'no-store' });
    if (!res.ok) return 0;
    const data = await res.json();
    return Date.now() - data.serverTime;
  } catch {
    return 0;
  }
}

export async function GET() {
  const apiKey = process.env.BINANCE_API_KEY;
  const secretKey = process.env.BINANCE_SECRET_KEY;

  if (!apiKey || !secretKey) {
    return NextResponse.json({ error: 'Binance API keys not configured in .env.local' }, { status: 500 });
  }

  try {
    // Get server time offset to fix timestamp issues
    const offset = await getServerTimeOffset();
    const timestamp = Date.now() - offset;
    const recvWindow = 10000;
    const queryString = `timestamp=${timestamp}&recvWindow=${recvWindow}`;
    const signature = sign(queryString, secretKey);
    const url = `${BASE_URL}/api/v3/account?${queryString}&signature=${signature}`;

    const res = await fetch(url, {
      headers: { 'X-MBX-APIKEY': apiKey },
      cache: 'no-store',
    });

    const data = await res.json();

    if (!res.ok) {
      // Return full Binance error so we can debug
      return NextResponse.json(
        { error: data.msg || 'Binance error', binance_code: data.code, status: res.status },
        { status: res.status }
      );
    }

    // Extract all non-zero balances
    const balances: Record<string, { free: number; locked: number; total: number }> = {};
    for (const b of data.balances ?? []) {
      const free = parseFloat(b.free);
      const locked = parseFloat(b.locked);
      if (free > 0 || locked > 0) {
        balances[b.asset] = { free, locked, total: free + locked };
      }
    }

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
