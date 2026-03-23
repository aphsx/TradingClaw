import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

const ENGINE_HTTP_URL =
  process.env.TRADING_ENGINE_HTTP_URL ||
  process.env.NEXT_PUBLIC_ENGINE_HTTP_URL ||
  'http://trading-engine:8081';

export async function POST(req: Request) {
  try {
    const body = await req.json();

    const res = await fetch(`${ENGINE_HTTP_URL}/adopt-position`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(8000),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.ok ? 200 : 500 });
  } catch (e: any) {
    return NextResponse.json({ success: false, error: e.message }, { status: 500 });
  }
}
