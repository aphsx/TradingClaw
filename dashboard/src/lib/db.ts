import mysql from 'mysql2/promise';
import fs from 'fs';

let pool: mysql.Pool | null = null;

const RUNNING_IN_DOCKER = fs.existsSync('/.dockerenv');

const rawDbHost = process.env.DB_HOST || 'db';
const rawRedisHost = process.env.REDIS_HOST || 'redis';

const DB_HOST = RUNNING_IN_DOCKER && rawDbHost === 'localhost' ? 'db' : rawDbHost;
const DB_PORT = parseInt(process.env.DB_PORT || '3306');
const REDIS_HOST = RUNNING_IN_DOCKER && rawRedisHost === 'localhost' ? 'redis' : rawRedisHost;
const REDIS_PORT = parseInt(process.env.REDIS_PORT || '6379');

function formatError(e: any): string {
  if (!e) return 'Unknown error';

  const nested = Array.isArray(e.errors)
    ? e.errors
        .map((x: any) => x?.message || x?.code)
        .filter(Boolean)
        .join(' | ')
    : '';

  const parts = [e.message, e.code, e.sqlMessage, nested].filter(Boolean);
  return parts.length > 0 ? parts.join(' | ') : String(e);
}

export function getPool() {
  if (!pool) {
    pool = mysql.createPool({
      host: DB_HOST,
      port: DB_PORT,
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
  try {
    const db = getPool();
    const [rows] = await db.execute(sql, params);
    return rows;
  } catch (e: any) {
    throw new Error(`${formatError(e)} @ ${DB_HOST}:${DB_PORT}`);
  }
}

// ─── Redis helper ───
import Redis from 'ioredis';

let redis: Redis | null = null;

export function getRedis() {
  if (!redis) {
    redis = new Redis({
      host: REDIS_HOST,
      port: REDIS_PORT,
      maxRetriesPerRequest: 3,
      lazyConnect: true,
    });

    // Suppress noisy unhandled error event logs from transient Redis reconnects.
    redis.on('error', () => {});
  }
  return redis;
}

export async function redisGet(key: string) {
  try {
    const r = getRedis();
    if (r.status === 'wait') {
      await r.connect().catch(() => {});
    }
    const val = await r.get(key);
    return val ? JSON.parse(val) : null;
  } catch {
    return null;
  }
}

export async function redisSmembers(key: string) {
  try {
    const r = getRedis();
    if (r.status === 'wait') {
      await r.connect().catch(() => {});
    }
    return await r.smembers(key);
  } catch {
    return [];
  }
}
