param(
    [string]$LogPath = (Join-Path $PSScriptRoot 'live_stream.log'),
    [string]$StopPath
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($StopPath)) {
    Push-Location (Join-Path $PSScriptRoot '../TheAnalyticsBridge')
    try {
        $StopPath = & pipenv run python -m configuration.simulator
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($StopPath)) {
            throw 'Unable to load ATTACK_SIM_STOP_PATH from bridge configuration.'
        }
    }
    finally {
        Pop-Location
    }
}
$stopFilePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($StopPath)
$logFilePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($LogPath)
$encoding = [System.Text.UTF8Encoding]::new($false)
$attackTypes = 'Brute Force', 'SQL Injection', 'Port Scan', 'Credential Stuffing'
if (Test-Path -LiteralPath $stopFilePath) {
    Remove-Item -LiteralPath $stopFilePath
}

Write-Host 'Starting Cyber Attack Simulation...' -ForegroundColor Red

while (-not (Test-Path -LiteralPath $stopFilePath)) {
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

Write-Host 'Attack simulation stopped.' -ForegroundColor Green