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

async function getServerTime(): Promise<number> {
  const endpoint = IS_FUTURES ? '/fapi/v1/time' : '/api/v3/time';
  const res = await fetch(`${BASE_URL}${endpoint}`, { cache: 'no-store' });
  const data = await res.json();
  return data.serverTime;
}

// POST /api/test-order
// body: { symbol, side, type, quantity }
export async function POST(req: Request) {
  const apiKey = process.env.BINANCE_API_KEY;
  const secretKey = process.env.BINANCE_SECRET_KEY;

  if (!apiKey || !secretKey) {
    return NextResponse.json({ error: 'Binance API keys not configured' }, { status: 500 });
  }

  try {
    const body = await req.json();
    const symbol   = body.symbol   || 'BTCUSDT';
    const side     = body.side     || 'BUY';
    const type     = body.type     || 'MARKET';
    const quantity = body.quantity || '0.001';

    const timestamp = await getServerTime();
    const recvWindow = 10000;

    const params = [
      `symbol=${symbol}`,
      `side=${side}`,
      `type=${type}`,
      `quantity=${quantity}`,
      `timestamp=${timestamp}`,
      `recvWindow=${recvWindow}`,
    ].join('&');

    const signature = sign(params, secretKey);
    const endpoint = IS_FUTURES ? '/fapi/v1/order' : '/api/v3/order';
    const url = `${BASE_URL}${endpoint}?${params}&signature=${signature}`;

    const res = await fetch(url, {
      method: 'POST',
      headers: { 'X-MBX-APIKEY': apiKey },
      cache: 'no-store',
    });

    const data = await res.json();

    if (!res.ok) {
      return NextResponse.json(
        { error: data.msg || 'Binance error', binance_code: data.code },
        { status: res.status }
      );
    }

    return NextResponse.json({ success: true, order: data });
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
