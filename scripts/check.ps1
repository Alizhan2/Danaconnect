$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
Push-Location (Join-Path $projectRoot 'apps\api')
try {
    & $projectPython -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'API checks failed.' }
} finally { Pop-Location }
Push-Location (Join-Path $projectRoot 'apps\web')
try {
    npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Type checking failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Web build failed.' }
} finally { Pop-Location }
Push-Location (Join-Path $projectRoot 'apps\admin')
try {
    npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Admin type checking failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Admin build failed.' }
} finally { Pop-Location }
