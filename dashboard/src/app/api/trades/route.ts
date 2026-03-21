import { NextResponse } from 'next/server';
import { query } from '@/lib/db';

export async function GET(req: Request) {
  try {
    const { searchParams } = new URL(req.url);
    const status = searchParams.get('status') || 'all';
    const limit = parseInt(searchParams.get('limit') || '100');

    let sql = 'SELECT * FROM positions';
    const params: any[] = [];

    if (status !== 'all') {
      sql += ' WHERE status = ?';
      params.push(status.toUpperCase());
    }
    sql += ' ORDER BY entry_time DESC LIMIT ?';
    params.push(limit);

    const rows = await query(sql, params);
    return NextResponse.json(rows);
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
