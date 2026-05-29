# Run odds tracker (requires .env with ODDS_API_KEY + Supabase keys, or LOCAL_STORAGE=1)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

if (-not (Test-Path ".env")) {
    Write-Host "ERROR: Create .env from .env.example first." -ForegroundColor Red
    Write-Host "  copy .env.example .env"
    Write-Host "  Then set ODDS_API_KEY and SUPABASE_SERVICE_ROLE_KEY"
    exit 1
}

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    python -m venv .venv
    & (Join-Path $Root ".venv\Scripts\pip.exe") install -r scraper\requirements.txt
}

$cmd = $args[0]
if (-not $cmd) { $cmd = "init" }

& $py -m scraper.main $cmd @args[1..($args.Length)]
