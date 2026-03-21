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

// ─── Redis helper ───
import Redis from 'ioredis';

let redis: Redis | null = null;

export function getRedis() {
  if (!redis) {
    redis = new Redis({
      host: process.env.REDIS_HOST || 'localhost',
      port: parseInt(process.env.REDIS_PORT || '6379'),
      maxRetriesPerRequest: 3,
      lazyConnect: true,
    });
  }
  return redis;
}

export async function redisGet(key: string) {
  try {
    const r = getRedis();
    await r.connect().catch(() => {});
    const val = await r.get(key);
    return val ? JSON.parse(val) : null;
  } catch {
    return null;
  }
}

export async function redisSmembers(key: string) {
  try {
    const r = getRedis();
    await r.connect().catch(() => {});
    return await r.smembers(key);
  } catch {
    return [];
  }
}
