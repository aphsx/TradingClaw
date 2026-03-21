import { NextResponse } from 'next/server';
import crypto from 'crypto';

export const dynamic = 'force-dynamic';

const IS_TESTNET = process.env.USE_TESTNET === 'true';
const IS_FUTURES = process.env.USE_FUTURES === 'true';

const BASE_URL = IS_FUTURES
  ? (IS_TESTNET ? 'https://testnet.binancefuture.com' : 'https://fapi.binance.com')
  : (IS_TESTNET ? 'https://testnet.binance.vision'    : 'https://api.binance.com');

function sign(queryString: string, secret: string): string {
  return crypto.createHmac('sha256', secret).update(queryString).digest('hex');
}

// Get Binance server time to avoid clock skew (-1021 error)
async function getServerTime(): Promise<number> {
  const endpoint = IS_FUTURES ? '/fapi/v1/time' : '/api/v3/time';
  const res = await fetch(`${BASE_URL}${endpoint}`, { cache: 'no-store' });
  const data = await res.json();
  return data.serverTime;
}

export async function GET() {
  const apiKey = process.env.BINANCE_API_KEY;
  const secretKey = process.env.BINANCE_SECRET_KEY;

  if (!apiKey || !secretKey) {
    return NextResponse.json({ error: 'Binance API keys not configured in .env.local' }, { status: 500 });
  }

  try {
    const timestamp = await getServerTime();
    const recvWindow = 10000;
    const queryString = `timestamp=${timestamp}&recvWindow=${recvWindow}`;
    const signature = sign(queryString, secretKey);

    const endpoint = IS_FUTURES ? '/fapi/v2/balance' : '/api/v3/account';
    const url = `${BASE_URL}${endpoint}?${queryString}&signature=${signature}`;

    const res = await fetch(url, {
      headers: { 'X-MBX-APIKEY': apiKey },
      cache: 'no-store',
    });

    const data = await res.json();

    if (!res.ok) {
      return NextResponse.json(
        { error: data.msg || 'Binance error', binance_code: data.code, status: res.status },
        { status: res.status }
      );
    }

    if (IS_FUTURES) {
      const balances: Record<string, any> = {};
      for (const b of data) {
        const total = parseFloat(b.balance);
        if (total > 0) {
          balances[b.asset] = {
            free: parseFloat(b.availableBalance),
            locked: total - parseFloat(b.availableBalance),
            total,
          };
        }
      }
      const usdt = balances['USDT'] ?? { free: 0, locked: 0, total: 0 };
      return NextResponse.json({
        usdt_free: usdt.free,
        usdt_locked: usdt.locked,
        usdt_total: usdt.total,
        balances,
        account_type: 'FUTURES',
      });
    } else {
      const balances: Record<string, any> = {};
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
        account_type: data.accountType ?? 'SPOT',
      });
    }
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
