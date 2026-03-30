import { NextResponse } from 'next/server';
import { getEngineHttpUrl } from '@/lib/engine-url';

export const dynamic = 'force-dynamic';

// POST /api/test-order
// body: { symbol, side, type, quantity }
export async function POST(req: Request) {
  try {
    const body = await req.json();
    const engineUrl = getEngineHttpUrl();
    
    // Instead of doing Binance signatures in JS, delegate to the Python engine
    // which handles CCXT and OKX configurations natively.
    const res = await fetch(`${engineUrl}/test-order`, {
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
