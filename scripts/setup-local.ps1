param([switch]$Demo)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$backend = Join-Path $projectRoot 'backend'
$frontend = Join-Path $projectRoot 'frontend'

function Assert-Success([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed. Read the output above, fix it, then run setup again." }
}

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22.12+ or 24 LTS first, then reopen PowerShell.' }
& node -e 'const [a,b] = process.versions.node.split(/\./).map(Number); if (!((a === 20 && b >= 19) || (a === 22 && b >= 12) || a > 22)) process.exit(1)'
Assert-Success 'Check Node.js version (22.12+ or 24 LTS recommended)'

$pythonExe = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv (Join-Path $backend '.venv')
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv (Join-Path $backend '.venv')
    } else { throw 'Install Python 3.12 (including the py launcher) first.' }
    Assert-Success 'Create Python environment'
}
& $pythonExe -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)'
Assert-Success 'Check Python version'
& $pythonExe -m pip install --require-hashes -r (Join-Path $backend 'requirements.lock')
Assert-Success 'Install backend dependencies'

$envPath = Join-Path $backend '.env'
if (-not (Test-Path $envPath)) {
    Write-Host 'Configure your local MySQL. Existing .env files will be preserved.'
    $dbHost = Read-Host 'MySQL host [127.0.0.1]'
    if (-not $dbHost) { $dbHost = '127.0.0.1' }
    $dbPort = Read-Host 'MySQL port [3306]'
    if (-not $dbPort) { $dbPort = '3306' }
    $dbUser = Read-Host 'MySQL user [root]'
    if (-not $dbUser) { $dbUser = 'root' }
    $dbName = Read-Host 'New project database [career_platform]'
    if (-not $dbName) { $dbName = 'career_platform' }
    if ($dbName -notmatch '^[A-Za-z][A-Za-z0-9_]{0,63}$') { throw 'Invalid database name.' }
    if ($dbPort -notmatch '^\d{1,5}$' -or [int]$dbPort -gt 65535 -or [int]$dbPort -lt 1) { throw 'Invalid port.' }
    $secure = Read-Host 'Your local MySQL password (hidden)' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $dbPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    # Double-quoted dotenv value with explicit escaping. Never put this value in Git or logs.
    $escapedPassword = $dbPassword.Replace('\', '\\').Replace('"', '\"').Replace("`r", '\r').Replace("`n", '\n')
    foreach ($value in @($dbHost, $dbUser)) { if ($value -match '[\r\n\x22]') { throw 'Invalid connection setting.' } }
    $text = "DB_DRIVER=mysql`nDB_HOST=$dbHost`nDB_PORT=$dbPort`nDB_USER=$dbUser`nDB_PASSWORD=`"$escapedPassword`"`nDB_NAME=$dbName`n"
    [IO.File]::WriteAllText($envPath, $text, (New-Object Text.UTF8Encoding($false)))
    $dbPassword = $null; $escapedPassword = $null; $text = $null
}

Push-Location $backend
try {
    if ($Demo) { & $pythonExe -m app.cli init-db --demo }
    else { & $pythonExe -m app.cli init-db }
    Assert-Success 'Create database and migrate schema'
} finally { Pop-Location }
Push-Location $frontend
try {
    & npm.cmd ci --no-audit --no-fund
    Assert-Success 'Install frontend dependencies'
    & npm.cmd run build
    Assert-Success 'Build frontend'
} finally { Pop-Location }
Write-Host 'Setup complete. Run scripts\start-local.ps1 next.'
if ($Demo) { Write-Host 'Demo accounts are documented in README.md. Enable the demo-data switch in the UI.' }
