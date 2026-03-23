import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
const ENGINE_HTTP_URL = process.env.TRADING_ENGINE_HTTP_URL || 'http://localhost:8081';

// POST /api/test-order
// body: { symbol, side, type, quantity }
export async function POST(req: Request) {
  try {
    const body = await req.json();
    
    // Instead of doing Binance signatures in JS, delegate to the Python engine
    // which handles CCXT and OKX configurations natively.
    const res = await fetch(`${ENGINE_HTTP_URL}/test-order`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
    });

    const data = await res.json();

    if (!res.ok) {
      return NextResponse.json(
        { error: data.error || 'Engine error' },
        { status: res.status }
      );
    }

    return NextResponse.json({ success: true, order: data.order });
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
