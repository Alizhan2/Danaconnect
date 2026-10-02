param([string]$BackupDirectory = '')
. (Join-Path $PSScriptRoot 'common.ps1')
if (-not $BackupDirectory) { $BackupDirectory = Join-Path $projectRoot 'deploy\backups' }
$BackupDirectory = [IO.Path]::GetFullPath($BackupDirectory)
New-Item -ItemType Directory -Path $BackupDirectory -Force | Out-Null
$backupName = 'danaconnect-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8) + '.dump'
$backupPath = Join-Path $BackupDirectory $backupName
$containerPath = '/tmp/' + $backupName
try {
    Invoke-Compose -Arguments @('exec','-T','postgres','pg_dump','--username',$databaseUser,'--dbname',$databaseName,'--format','custom','--file',$containerPath)
    # Copy the binary file; PowerShell text redirection would corrupt a pg_dump archive.
    Invoke-Compose -Arguments @('cp',('postgres:' + $containerPath),$backupPath)
    $hash = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText($backupPath + '.sha256', $hash + '  ' + $backupName + "`n", (New-Object Text.UTF8Encoding($false)))
    if ($env:OS -eq 'Windows_NT') {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        foreach ($privatePath in @($backupPath, $backupPath + '.sha256')) {
            & icacls $privatePath /inheritance:r /grant:r "${identity}:(F)" | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Could not restrict backup file permissions.' }
        }
    }
    Write-Output "Backup created: $backupPath"
    Write-Output 'Copy it to encrypted offsite storage. This archive does not contain S3 objects or application encryption keys.'
} finally {
    & docker @composeArguments exec -T postgres rm -f $containerPath
}
