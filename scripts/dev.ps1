param([ValidateSet('api','web','admin','worker')][string]$Service = 'web')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$appDirectory = if ($Service -eq 'worker') { 'api' } else { $Service }
Push-Location (Join-Path $projectRoot "apps\$appDirectory")
try {
    if ($Service -in @('api','worker')) {
        $projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Run scripts/setup.ps1 first.' }
        if ($Service -eq 'worker') { & $projectPython -m app.jobs_calendar --interval 60 }
        else { & $projectPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log }
    } else {
        npm.cmd run dev -- --hostname 127.0.0.1
    }
    if ($LASTEXITCODE -ne 0) { throw "$Service exited with an error." }
} finally { Pop-Location }
