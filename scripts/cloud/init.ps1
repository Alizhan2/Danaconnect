param([string]$PythonPath = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$localPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $localPython) { $PythonPath = $localPython }
& $PythonPath (Join-Path $projectRoot 'deploy\generate_config.py') --output (Join-Path $projectRoot 'deploy\.env.production')
if ($LASTEXITCODE -ne 0) { throw 'Configuration initialization failed. Existing files are never overwritten.' }
