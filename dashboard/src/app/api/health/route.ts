import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
const ENGINE_HTTP_URL = process.env.TRADING_ENGINE_HTTP_URL || 'http://localhost:8081';

export async function GET() {
  try {
    const res = await fetch(`${ENGINE_HTTP_URL}/health`, {
      cache: 'no-store',
    });
    if (!res.ok) throw new Error('Health probe failed');
    const data = await res.json();
    return NextResponse.json(data);
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
