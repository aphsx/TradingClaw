import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const res = await fetch('http://localhost:8080/sync-binance', {
      signal: AbortSignal.timeout(8000),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.ok ? 200 : 500 });
  } catch (e: any) {
    return NextResponse.json({ success: false, error: e.message }, { status: 500 });
  }
}
