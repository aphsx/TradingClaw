import { NextResponse } from 'next/server';
import { getEngineHttpUrl } from '@/lib/engine-url';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const engineUrl = getEngineHttpUrl();
    const res = await fetch(`${engineUrl}/balance`, {
      cache: 'no-store',
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch (e: any) {
    return NextResponse.json(
      { error: 'Failed to fetch balance from trading engine', reason: 'network_or_runtime_error', detail: e.message },
      { status: 500 }
    );
  }
}
