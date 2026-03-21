import { NextResponse } from 'next/server';
import { query } from '@/lib/db';

export async function GET() {
  try {
    const rows = await query(
      'SELECT timestamp, equity, capital, unrealized, open_positions, drawdown_pct FROM equity_curve ORDER BY timestamp ASC'
    );
    return NextResponse.json(rows);
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
