param(
    [Parameter(Mandatory=$true)][string]$BackupFile,
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z_][A-Za-z0-9_]{0,62}$')][string]$TargetDatabase,
    [switch]$Restore
)
. (Join-Path $PSScriptRoot 'common.ps1')
$resolvedBackup = (Resolve-Path -LiteralPath $BackupFile).Path
if ($TargetDatabase -in @($databaseName,'postgres','template0','template1')) { throw 'Restore requires a new separate database, never the live/default database.' }
$checksumPath = $resolvedBackup + '.sha256'
if (-not (Test-Path -LiteralPath $checksumPath)) { throw 'Expected the matching .sha256 file.' }
$expectedHash = ((Get-Content -LiteralPath $checksumPath -Raw).Trim() -split '\s+')[0]
if ($expectedHash -notmatch '^[a-fA-F0-9]{64}$' -or (Get-FileHash -LiteralPath $resolvedBackup -Algorithm SHA256).Hash -ne $expectedHash) {
    throw 'Backup checksum does not match.'
}
if (-not $Restore) { Write-Output "Checksum matches. Use -Restore to create and restore a new database named $TargetDatabase. The live database is never replaced."; return }
$runningDatabase = & docker @composeArguments exec -T postgres printenv POSTGRES_DB
if ($LASTEXITCODE -ne 0) { throw 'Could not read running database name.' }
if ($TargetDatabase -eq $runningDatabase.Trim()) { throw 'Target is the actual running live database; refusing restoration.' }
$containerPath = '/tmp/restore-' + [Guid]::NewGuid().ToString('N') + '.dump'
try {
    Invoke-Compose -Arguments @('cp',$resolvedBackup,('postgres:' + $containerPath))
    Invoke-Compose -Arguments @('exec','-T','postgres','pg_restore','--list',$containerPath) | Out-Null
    # Existing target names cause createdb to fail; no drop/overwrite is performed.
    Invoke-Compose -Arguments @('exec','-T','postgres','createdb','--username',$databaseUser,$TargetDatabase)
    Invoke-Compose -Arguments @('exec','-T','postgres','pg_restore','--username',$databaseUser,'--dbname',$TargetDatabase,'--no-owner','--no-acl','--exit-on-error',$containerPath)
    Write-Output "Restored into $TargetDatabase. A failed restore may leave a partial separate database for operator inspection. Promotion is a separate reviewed operation."
} finally {
    & docker @composeArguments exec -T postgres rm -f $containerPath
}
