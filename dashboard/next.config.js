/** @type {import('next').NextConfig} */
const path = require('path')
const fs   = require('fs')

// ─── Env loading strategy ─────────────────────────────────────────────────────
//
//  Mode          | Source                        | Loaded by
//  ──────────────┼───────────────────────────────┼──────────────────────────────
//  Docker        | docker-compose environment:   | OS process.env (runtime)
//                | docker-compose build.args     | ARG/ENV in Dockerfile (build)
//  Local dev     | dashboard/.env.local          | Next.js built-in auto-loader
//                | TradingClaw/.env (via dotenv) | try-catch below
//  CI            | Shell env vars                | OS process.env
//
// Rule: NEVER crash — all three try-catches are intentional no-ops.
// ─────────────────────────────────────────────────────────────────────────────

// 1. Try to load root .env via dotenv (local dev only, dotenv package optional)
try {
  require('dotenv').config({ path: path.resolve(__dirname, '../.env') })
} catch (_) {
  // dotenv not installed — Next.js auto-loads .env.local; Docker injects via env
}

// 2. Auto-sync .env.local from root .env (local dev only, no-op in Docker)
//    Skips when root .env doesn't exist (e.g. inside Docker container).
try {
  const rootEnv  = path.resolve(__dirname, '../.env')
  const localEnv = path.resolve(__dirname, '.env.local')

  if (fs.existsSync(rootEnv)) {
    const rootMtime  = fs.statSync(rootEnv).mtimeMs
    const localMtime = fs.existsSync(localEnv) ? fs.statSync(localEnv).mtimeMs : 0

    if (rootMtime > localMtime) {
      const lines = fs.readFileSync(rootEnv, 'utf8')
        .split('\n')
        .filter(l => l.trim() && !l.trim().startsWith('#'))
      const header = '# Auto-synced from TradingClaw/.env — do not edit manually\n'
      fs.writeFileSync(localEnv, header + lines.join('\n') + '\n')
      console.log('[ENV] [next.config] .env.local synced from root .env')
    }
  }
} catch (_) {
  // Non-fatal — expected in Docker where ../. env doesn't exist
}

// 3. Expose env vars to Next.js server-side routes.
//    - In Docker: process.env is already populated by the `environment:` block.
//    - In dev: process.env is populated by dotenv above OR by .env.local auto-load.
//    - Filter out undefined so we never override a valid runtime value with "undefined".
const SERVER_ENV_KEYS = [
  'DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'DB_PASSWORD',
  'REDIS_HOST', 'REDIS_PORT',
  'EXCHANGE',
  'OKX_API_KEY', 'OKX_SECRET_KEY', 'OKX_PASSPHRASE',
  'BYBIT_API_KEY', 'BYBIT_SECRET_KEY',
  'USE_FUTURES', 'USE_TESTNET',
  'NEXT_PUBLIC_SOCKET_URL',
]

const nextConfig = {
  // output: 'standalone' is optional — uncomment for smaller Docker images
  // output: 'standalone',

  env: Object.fromEntries(
    SERVER_ENV_KEYS
      .filter(k => process.env[k] !== undefined && process.env[k] !== '')
      .map(k => [k, process.env[k]])
  ),
}

module.exports = nextConfig
