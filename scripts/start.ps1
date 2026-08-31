param(
    [switch]$Server,
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $Root
$AppUrl = "http://127.0.0.1:${Port}/"

function Test-ServerRunning {
    try {
        $response = Invoke-WebRequest -Uri $AppUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Open-AppUi {
    Start-Process $AppUrl
}

if (Test-ServerRunning) {
    Write-Host "YouDownloader is already running. Opening the existing UI: $AppUrl"
    Open-AppUi
    exit 0
}

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    Write-Host "YouDownloader is not installed yet. Starting installation..."
    & (Join-Path $Root "install.bat")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$python = (Resolve-Path ".venv\Scripts\python.exe").Path

Write-Host "Starting YouDownloader."
Write-Host "This terminal stays open while YouDownloader is running."
Write-Host "URL: $AppUrl"

if ($Server) {
    & $python -m backend.main --server --port $Port
} else {
    & $python -m backend.main --port $Port
}
