param([switch]$Enable)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Enable) {
    Write-Output 'Opt-in requires a plan supporting minute cron, CRON_SECRET, and one scheduler. Use -Enable after configuring these.'
    return
}
$configPath = Join-Path $projectRoot 'vercel.json'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$config | Add-Member -NotePropertyName crons -NotePropertyValue @(@{path='/api/v1/internal/jobs';schedule='* * * * *'}) -Force
$encoded = $config | ConvertTo-Json -Depth 30
[IO.File]::WriteAllText($configPath, $encoded + "`n", (New-Object Text.UTF8Encoding($false)))
Write-Output 'Minute cron added locally. No deployment was created. Set CRON_SECRET on the platform; stop the container scheduler before using cron.'
