import { NextResponse } from 'next/server';
import { query } from '@/lib/db';

export async function GET() {
  try {
    const latest: any = await query(
      'SELECT * FROM regimes ORDER BY timestamp DESC LIMIT 1'
    );
    const distribution: any = await query(
      'SELECT regime_name, COUNT(*) as count FROM regimes GROUP BY regime_name'
    );
    const recent: any = await query(
      'SELECT timestamp, regime_name, confidence, adx, atr_pct FROM regimes ORDER BY timestamp DESC LIMIT 50'
    );
    return NextResponse.json({
      current: latest[0] || null,
      distribution,
      recent,
    });
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
