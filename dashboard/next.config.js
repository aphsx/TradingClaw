/** @type {import('next').NextConfig} */
const path = require('path')

// Load root .env (TradingClaw/.env) — single source of truth for local dev.
// In Docker, env vars are injected directly so this is a no-op.
require('dotenv').config({ path: path.resolve(__dirname, '../.env') })

const nextConfig = {
  output: 'standalone',
  // Expose root .env vars to Next.js (server-side API routes + NEXT_PUBLIC_ client vars)
  env: {
    DB_HOST:     process.env.DB_HOST,
    DB_PORT:     process.env.DB_PORT,
    DB_NAME:     process.env.DB_NAME,
    DB_USER:     process.env.DB_USER,
    DB_PASSWORD: process.env.DB_PASSWORD,
    REDIS_HOST:  process.env.REDIS_HOST,
    REDIS_PORT:  process.env.REDIS_PORT,
    BINANCE_API_KEY:    process.env.BINANCE_API_KEY,
    BINANCE_SECRET_KEY: process.env.BINANCE_SECRET_KEY,
    USE_TESTNET:  process.env.USE_TESTNET,
    USE_FUTURES:  process.env.USE_FUTURES,
    NEXT_PUBLIC_SOCKET_URL: process.env.NEXT_PUBLIC_SOCKET_URL,
  },
}

module.exports = nextConfig
