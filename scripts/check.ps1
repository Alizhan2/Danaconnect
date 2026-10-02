$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
& $projectPython (Join-Path $PSScriptRoot 'api-tests.py')
if ($LASTEXITCODE -ne 0) { throw 'API checks failed.' }
node (Join-Path $PSScriptRoot 'frontend-tests.mjs')
if ($LASTEXITCODE -ne 0) { throw 'Frontend checks failed.' }
foreach ($suite in @('date-format-tests.mjs', 'download-tests.mjs', 'mobile-navigation-tests.mjs')) {
    node (Join-Path $PSScriptRoot $suite)
    if ($LASTEXITCODE -ne 0) { throw "$suite failed." }
}
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
