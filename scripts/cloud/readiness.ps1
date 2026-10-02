param([string]$BaseUrl = '', [string]$PythonPath = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$localPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $localPython) { $PythonPath = $localPython }
$arguments = @((Join-Path $projectRoot 'deploy\readiness.py'), '--env-file', (Join-Path $projectRoot 'deploy\.env.production'))
if ($BaseUrl) { $arguments += @('--base-url', $BaseUrl) }
& $PythonPath @arguments
if ($LASTEXITCODE -ne 0) { throw 'Deployment prerequisites are incomplete; secret values were not displayed.' }
