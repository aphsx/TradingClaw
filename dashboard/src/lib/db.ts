import mysql from 'mysql2/promise';

let pool: mysql.Pool | null = null;

export function getPool() {
  if (!pool) {
    pool = mysql.createPool({
      host: process.env.DB_HOST || 'localhost',
      port: parseInt(process.env.DB_PORT || '3306'),
      database: process.env.DB_NAME || 'regime_trader',
      user: process.env.DB_USER || 'trader',
      password: process.env.DB_PASSWORD || 'trader_pass_2026',
      waitForConnections: true,
      connectionLimit: 10,
    });
  }
  return pool;
}

export async function query(sql: string, params?: any[]) {
  const db = getPool();
  const [rows] = await db.execute(sql, params);
  return rows;
}
