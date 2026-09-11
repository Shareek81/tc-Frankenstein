param(
    [string]$LogPath = (Join-Path $PSScriptRoot 'live_stream.log')
)

$ErrorActionPreference = 'Stop'
$logFilePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($LogPath)
$encoding = [System.Text.UTF8Encoding]::new($false)
$attackTypes = 'Brute Force', 'SQL Injection', 'Port Scan', 'Credential Stuffing'

Write-Host 'Starting Cyber Attack Simulation...' -ForegroundColor Red

while ($true) {
    $randomAttack = $attackTypes | Get-Random
    $severity = Get-Random -Minimum 1 -Maximum 10

    $logEntry = @{
        time = Get-Date -Format 'HH:mm:ss'
        type = $randomAttack
        severity = $severity
        origin = "103.25.12.$(Get-Random -Minimum 1 -Maximum 255)"
    }

    $json = $logEntry | ConvertTo-Json -Compress
    [System.IO.File]::AppendAllText($logFilePath, $json + [Environment]::NewLine, $encoding)
    Write-Host "Generated Threat: $randomAttack (Severity: $severity)" -ForegroundColor Yellow
    Start-Sleep -Seconds (Get-Random -Minimum 1 -Maximum 3)
}