$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$configPath = Join-Path $projectRoot 'deploy\.env.production'
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Create deploy/.env.production first.' }
$composeArguments = @('compose','--env-file',$configPath,'-f',(Join-Path $projectRoot 'compose.prod.yml'))
$databaseUser = 'danaconnect'
$databaseName = 'danaconnect'
foreach ($line in (Get-Content -LiteralPath $configPath)) {
    if ($line -match '^POSTGRES_USER=(.+)$') { $databaseUser = $Matches[1].Trim().Trim('"',"'") }
    if ($line -match '^POSTGRES_DB=(.+)$') { $databaseName = $Matches[1].Trim().Trim('"',"'") }
}
if ($databaseUser -notmatch '^[A-Za-z_][A-Za-z0-9_]{0,62}$' -or $databaseName -notmatch '^[A-Za-z_][A-Za-z0-9_]{0,62}$') {
    throw 'Use simple PostgreSQL user/database identifiers in deployment configuration.'
}
function Invoke-Compose {
    param([Parameter(Mandatory=$true)][string[]]$Arguments)
    & docker @composeArguments @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose command failed. No secret configuration was printed.' }
}
