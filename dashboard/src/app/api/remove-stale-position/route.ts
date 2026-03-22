import { NextResponse } from 'next/server';
import { query } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { position_id } = body;

    if (!position_id) {
      return NextResponse.json({ error: 'position_id required' }, { status: 400 });
    }

    // First check if the position exists
    const existing = await query(
      `SELECT id FROM positions WHERE id = ? AND status = 'OPEN'`,
      [position_id]
    );

    if (!existing || (existing as any[]).length === 0) {
      return NextResponse.json({ 
        success: false, 
        message: 'No position found with that ID' 
      }, { status: 404 });
    }

    // Delete the position from MySQL
    await query(
      `DELETE FROM positions WHERE id = ? AND status = 'OPEN'`,
      [position_id]
    );

    return NextResponse.json({ 
      success: true, 
      message: `Removed stale position #${position_id}` 
    });
  } catch (e: any) {
    return NextResponse.json({ success: false, error: e.message }, { status: 500 });
  }
}
