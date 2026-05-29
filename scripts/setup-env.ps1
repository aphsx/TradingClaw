param(
    [Parameter(Mandatory = $true)]
    [string]$OddsApiKey,
    [string]$SupabaseServiceKey = "",
    [switch]$LocalOnly
)

$Root = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $Root ".env"
$local = if ($LocalOnly -or -not $SupabaseServiceKey) { "LOCAL_STORAGE=1`n" } else { "" }

@"
SUPABASE_URL=https://bjmqwerbslpdbfrkedqj.supabase.co
SUPABASE_SERVICE_ROLE_KEY=$SupabaseServiceKey
ODDS_API_KEY=$OddsApiKey
${local}TRACKING_WINDOW_DAYS=7
FOOTBALL_MATCH_COUNT=10
ESPORTS_MATCH_COUNT=10
"@ | Set-Content -Path $envPath -Encoding utf8

Write-Host "Wrote $envPath"
