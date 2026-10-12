$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$backend = Join-Path $projectRoot 'backend'
$frontend = Join-Path $projectRoot 'frontend'
$pythonExe = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe) -or -not (Test-Path (Join-Path $frontend 'node_modules'))) { throw 'Run scripts\setup-local.ps1 first.' }
foreach ($port in @(8000,5173)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "Port $port is already in use. Close the existing service or use manual startup from docs/WINDOWS.md." }
}
$apiProcess = $null
$webProcess = $null
try {
    $apiProcess = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $backend -PassThru -NoNewWindow
    $ready = $false
    for ($i=0; $i -lt 60; $i++) {
        if ($apiProcess.HasExited) { throw 'Backend exited. Check MySQL service, .env and migrations.' }
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'Backend readiness failed. Database is not ready.' }
    $webProcess = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/d','/c','npm run dev') -WorkingDirectory $frontend -PassThru -NoNewWindow
    $webReady = $false
    for ($i=0; $i -lt 30; $i++) {
        if ($webProcess.HasExited) { throw 'Frontend exited. Read the startup output.' }
        try {
            $response = Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $webReady = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $webReady) { throw 'Frontend readiness failed.' }
    Write-Host 'Local app: http://127.0.0.1:5173/ (leave this window open)'
    Start-Process 'http://127.0.0.1:5173/'
    Read-Host 'Press Enter to stop these two services' | Out-Null
} finally {
    # Stop only the processes this script launched, including the npm child tree.
    if ($webProcess -and -not $webProcess.HasExited) { & taskkill.exe /PID $webProcess.Id /T /F | Out-Null }
    if ($apiProcess -and -not $apiProcess.HasExited) { Stop-Process -Id $apiProcess.Id }
}
