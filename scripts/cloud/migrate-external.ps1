[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$EnvFile = '',
    [string]$ExpectedCurrent,
    [string]$PythonPath = 'python'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$localPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $localPython) { $PythonPath = $localPython }

# No deployment config, provider, database or credentials are read in plan mode.
$arguments = @((Join-Path $projectRoot 'deploy\migrate_external.py'))
if ($PSBoundParameters.ContainsKey('ExpectedCurrent')) {
    # A literal sentinel also works with native argument passing in PowerShell 5.
    if ([string]::IsNullOrEmpty($ExpectedCurrent)) { $ExpectedCurrent = 'empty' }
    $arguments += @('--expected-current', $ExpectedCurrent)
}
if ($Apply) {
    if ([string]::IsNullOrWhiteSpace($EnvFile) -or -not $PSBoundParameters.ContainsKey('ExpectedCurrent')) {
        throw 'Apply requires -EnvFile and -ExpectedCurrent; use empty for a fresh dedicated PostgreSQL database.'
    }
    $arguments += @('--apply', '--env-file', $EnvFile)
}
& $PythonPath @arguments
if ($LASTEXITCODE -ne 0) {
    throw 'External migration was not confirmed. Review the operator message and database state before retrying.'
}
