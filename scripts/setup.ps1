param([string]$PythonPath = '', [switch]$Demo)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    if (-not $PythonPath) {
        $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if (Test-Path -LiteralPath $bundledPython) { $PythonPath = $bundledPython }
        else { $PythonPath = 'python' }
    }
    & $PythonPath -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment; pass -PythonPath with Python 3.12+.' }
}
& $projectPython -m pip install -r (Join-Path $projectRoot 'apps\api\requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
foreach ($service in @('api','web','admin')) {
    $serviceDirectory = Join-Path $projectRoot "apps\$service"
    $configPath = Join-Path $serviceDirectory '.env'
    if (-not (Test-Path -LiteralPath $configPath)) {
        Copy-Item -LiteralPath (Join-Path $serviceDirectory '.env.example') -Destination $configPath
    }
}
foreach ($service in @('web','admin')) {
    Push-Location (Join-Path $projectRoot "apps\$service")
    try {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw "$service dependency installation failed." }
    } finally { Pop-Location }
}
Push-Location (Join-Path $projectRoot 'apps\api')
try {
    & $projectPython -c "from app.config import settings; assert settings.environment == 'development', 'setup.ps1 is for local development only'"
    if ($LASTEXITCODE -ne 0) { throw 'Local setup refuses a non-development API configuration.' }
    & $projectPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
    if ($Demo) {
        & $projectPython -m app.seed
        if ($LASTEXITCODE -ne 0) { throw 'Demo data initialization failed.' }
    }
} finally { Pop-Location }
Write-Output 'Ready. Run scripts/dev.ps1 -Service api, web, admin and worker in separate terminals. Demo fixtures require setup.ps1 -Demo.'
