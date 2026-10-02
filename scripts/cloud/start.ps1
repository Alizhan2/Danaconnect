[CmdletBinding()]
param([switch]$Launch)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
& (Join-Path $PSScriptRoot 'readiness.ps1')
$composeArguments = @('compose', '--env-file', (Join-Path $projectRoot 'deploy\.env.production'), '-f', (Join-Path $projectRoot 'compose.prod.yml'))
# -q validates interpolation without dumping secret values to the terminal.
& docker @composeArguments config -q
if ($LASTEXITCODE -ne 0) { throw 'Compose configuration is invalid.' }
if (-not $Launch) { Write-Output 'Configuration validated. Use -Launch on the intended Docker host to build and start the release.'; return }
& docker @composeArguments build api web admin
if ($LASTEXITCODE -ne 0) { throw 'Image build failed.' }
& docker @composeArguments up -d
if ($LASTEXITCODE -ne 0) { throw 'Release startup failed; inspect service logs on the host.' }
& docker @composeArguments ps
