# Opens migration file path and prints Supabase SQL Editor link
$migration = Join-Path $PSScriptRoot "..\supabase\migrations\20260529100000_odds_arbitrage_tracking.sql"
Write-Host "Migration file:" (Resolve-Path $migration)
Write-Host ""
Write-Host "1. Open SQL Editor:"
Write-Host "   https://supabase.com/dashboard/project/bjmqwerbslpdbfrkedqj/sql/new"
Write-Host ""
Write-Host "2. Paste the full migration SQL and Run."
Write-Host ""
Write-Host "Or with Supabase CLI (after: npx supabase login && npx supabase link):"
Write-Host "   npx supabase db push"
