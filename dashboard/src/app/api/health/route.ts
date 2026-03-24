import { NextResponse } from 'next/server';
import { getEngineHttpUrl } from '@/lib/engine-url';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const engineUrl = getEngineHttpUrl();
    const res = await fetch(`${engineUrl}/health`, {
      cache: 'no-store',
    });
    if (!res.ok) throw new Error('Health probe failed');
    const data = await res.json();
    return NextResponse.json(data);
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
