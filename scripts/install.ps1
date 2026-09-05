$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $Root

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Get-PythonExecutable {
    $commands = @(
        @{ Command = "py"; Arguments = @("-3") },
        @{ Command = "python"; Arguments = @() },
        @{ Command = "python3"; Arguments = @() }
    )

    foreach ($candidate in $commands) {
        if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) {
            continue
        }
        try {
            $path = & $candidate.Command @($candidate.Arguments) -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $path -and (Test-Path -LiteralPath $path.Trim())) {
                return $path.Trim()
            }
        } catch {
            continue
        }
    }
    return $null
}

function Install-WithWinget([string]$Id, [string]$Name, [switch]$Required) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        if ($Required) {
            throw "Windows Package Manager (winget) is missing. Install App Installer from Microsoft Store and run install.bat again."
        }
        Write-Warning "winget is missing, skipping optional installation: $Name"
        return $false
    }

    Write-Step "Installing $Name"
    & winget.exe install --id $Id --exact --source winget --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        if ($Required) {
            throw "Installing package $Name with winget failed (code $LASTEXITCODE)."
        }
        Write-Warning "Installing optional package $Name failed (code $LASTEXITCODE)."
        return $false
    }
    return $true
}

function Remove-VenvSafely {
    $root = (Resolve-Path ".").Path
    $venv = Join-Path $root ".venv"
    if (-not (Test-Path -LiteralPath $venv)) {
        return
    }
    $resolved = (Resolve-Path -LiteralPath $venv).Path
    if (-not $resolved.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to delete .venv outside the YouDownloader folder: $resolved"
    }
    Write-Step "Removing transferred or damaged .venv environment"
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

function Test-VenvUsable {
    if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
        return $false
    }
    try {
        $output = & ".venv\Scripts\python.exe" -c "import sys; print(sys.executable)" 2>$null
        return ($LASTEXITCODE -eq 0 -and $output)
    } catch {
        return $false
    }
}

function Test-CommandAvailable([string]$Command) {
    return [bool](Get-Command $Command -ErrorAction SilentlyContinue)
}

function Test-BundledFfmpeg {
    return (
        (Test-Path -LiteralPath "resources\bin\ffmpeg.exe") -and
        (Test-Path -LiteralPath "resources\bin\ffprobe.exe")
    )
}

function Test-SystemFfmpeg {
    return ((Test-CommandAvailable "ffmpeg.exe") -and (Test-CommandAvailable "ffprobe.exe"))
}

function Test-WebView2Runtime {
    $paths = @(
        "${env:ProgramFiles(x86)}\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe",
        "$env:ProgramFiles\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe",
        "$env:LOCALAPPDATA\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe"
    )
    foreach ($path in $paths) {
        if (Get-ChildItem -Path $path -ErrorAction SilentlyContinue | Select-Object -First 1) {
            return $true
        }
    }
    return $false
}

function New-DesktopShortcut {
    $startScript = Join-Path $Root "start.bat"
    if (-not (Test-Path -LiteralPath $startScript)) {
        throw "start.bat was not found: $startScript"
    }

    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath("Desktop")
    if (-not $desktop) {
        $desktop = $shell.SpecialFolders.Item("Desktop")
    }
    if (-not $desktop -or -not (Test-Path -LiteralPath $desktop)) {
        throw "Desktop folder could not be found."
    }

    $shortcutPath = Join-Path $desktop "YouDownloader.lnk"
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $startScript
    $shortcut.WorkingDirectory = $Root
    $shortcut.Description = "Start YouDownloader"
    $shortcut.Save()

    Write-Host "Desktop shortcut: $shortcutPath" -ForegroundColor Green
}

Write-Host "YouDownloader - dependency installation" -ForegroundColor Magenta
Write-Host "Folder: $Root"

$python = Get-PythonExecutable
if (-not $python) {
    Install-WithWinget "Python.Python.3.13" "Python 3.13" -Required
    $python = Get-PythonExecutable
}
if (-not $python) {
    throw "Python could not be found even after installation. Restart Windows and run install.bat again."
}

$versionText = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$versionParts = $versionText.Split(".")
if ([int]$versionParts[0] -lt 3 -or ([int]$versionParts[0] -eq 3 -and [int]$versionParts[1] -lt 11)) {
    throw "YouDownloader requires Python 3.11 or newer. Found: $versionText"
}
Write-Host "Python: $python ($versionText)" -ForegroundColor Green

if ((Test-Path -LiteralPath ".venv") -and -not (Test-VenvUsable)) {
    Remove-VenvSafely
}

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    Write-Step "Creating isolated Python environment .venv"
    & $python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Creating .venv failed." }
}

$venvPython = (Resolve-Path ".venv\Scripts\python.exe").Path
& $venvPython -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Step "Adding pip to .venv"
    & $venvPython -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw "Installing pip through ensurepip failed." }
}

Write-Step "Updating pip"
& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Updating pip failed." }

Write-Step "Installing Python dependencies"
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Installing requirements.txt failed." }

if (-not (Test-CommandAvailable "node.exe")) {
    Install-WithWinget "OpenJS.NodeJS.LTS" "Node.js LTS" | Out-Null
}
if (Test-CommandAvailable "node.exe") {
    $nodePath = (Get-Command "node.exe").Source
    Write-Host "Node.js: $nodePath" -ForegroundColor Green
} else {
    Write-Warning "Node.js was not found. yt-dlp can still run, but YouTube extraction may be less reliable."
}

if (-not (Test-BundledFfmpeg) -and -not (Test-SystemFfmpeg)) {
    Install-WithWinget "Gyan.FFmpeg" "FFmpeg" | Out-Null
}
if (Test-BundledFfmpeg) {
    Write-Host "FFmpeg: resources\bin\ffmpeg.exe" -ForegroundColor Green
} elseif (Test-SystemFfmpeg) {
    Write-Host "FFmpeg: available on PATH" -ForegroundColor Green
} else {
    Write-Warning "FFmpeg/FFprobe were not found. MP3 conversion and some MP4 merges may fail until FFmpeg is installed or copied to resources\bin."
}

if (-not (Test-WebView2Runtime)) {
    Install-WithWinget "Microsoft.EdgeWebView2Runtime" "Microsoft Edge WebView2 Runtime" | Out-Null
}
if (Test-WebView2Runtime) {
    Write-Host "WebView2 Runtime: available" -ForegroundColor Green
} else {
    Write-Warning "WebView2 Runtime was not detected. start.bat can still fall back to browser/server mode if pywebview cannot open a desktop window."
}

New-Item -ItemType Directory -Force -Path "data", "cache", "config", "logs", "resources\bin" | Out-Null

Write-Step "Creating desktop shortcut"
New-DesktopShortcut

Write-Step "Verifying installation"
& $venvPython -c "import aiosqlite, fastapi, httpx, psutil, uvicorn, webview, yt_dlp; print('Python dependencies are OK.')"
if ($LASTEXITCODE -ne 0) { throw "Python dependency check failed." }

Write-Host "`nYouDownloader installation completed successfully." -ForegroundColor Green
Write-Host "Run start.bat to open the app."
