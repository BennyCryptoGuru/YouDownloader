param(
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Get-ProcessCommandLineMap {
    $map = @{}
    Get-CimInstance Win32_Process | ForEach-Object {
        $map[[int]$_.ProcessId] = $_
    }
    return $map
}

function Add-Descendants(
    [hashtable]$ProcessMap,
    [System.Collections.Generic.HashSet[int]]$ProcessIds
) {
    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($process in $ProcessMap.Values) {
            $processId = [int]$process.ProcessId
            $parentPid = [int]$process.ParentProcessId
            if ($ProcessIds.Contains($parentPid) -and -not $ProcessIds.Contains($processId)) {
                [void]$ProcessIds.Add($processId)
                $changed = $true
            }
        }
    }
}

function Test-TextContains([string]$Text, [string]$Needle) {
    if (-not $Text -or -not $Needle) {
        return $false
    }
    return $Text.IndexOf($Needle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Add-PortOwner(
    [hashtable]$ProcessMap,
    [System.Collections.Generic.HashSet[int]]$ProcessIds,
    [int]$Port
) {
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    } catch {
        return
    }

    foreach ($connection in $connections) {
        $processId = [int]$connection.OwningProcess
        if (-not $ProcessMap.ContainsKey($processId)) {
            continue
        }
        $process = $ProcessMap[$processId]
        $commandLine = [string]$process.CommandLine
        if (
            (Test-TextContains $commandLine $Root) -or
            (Test-TextContains $commandLine "backend.main") -or
            (Test-TextContains $commandLine "YouDownloader")
        ) {
            [void]$ProcessIds.Add($processId)
        } else {
            Write-Warning "Port $Port is used by PID $processId, but it does not look like YouDownloader. Leaving it running."
        }
    }
}

Write-Host "YouDownloader - stop all project sessions" -ForegroundColor Magenta
Write-Host "Folder: $Root"
Write-Host "Port: $Port"

$processMap = Get-ProcessCommandLineMap
$targetIds = [System.Collections.Generic.HashSet[int]]::new()
$ownPid = $PID

foreach ($process in $processMap.Values) {
    $processId = [int]$process.ProcessId
    if ($processId -eq $ownPid) {
        continue
    }

    $name = [string]$process.Name
    $commandLine = [string]$process.CommandLine
    if (-not $commandLine) {
        continue
    }

    $isProjectProcess = Test-TextContains $commandLine $Root
    $mentionsApp = Test-TextContains $commandLine "YouDownloader"
    $isKnownRuntime = $name -in @(
        "python.exe",
        "pythonw.exe",
        "ffmpeg.exe",
        "ffprobe.exe",
        "node.exe",
        "msedgewebview2.exe"
    )

    if ($isKnownRuntime -and ($isProjectProcess -or $mentionsApp)) {
        [void]$targetIds.Add($processId)
    }
}

Add-PortOwner -ProcessMap $processMap -ProcessIds $targetIds -Port $Port
Add-Descendants -ProcessMap $processMap -ProcessIds $targetIds

$targets = $targetIds |
    Where-Object { $_ -ne $ownPid -and $processMap.ContainsKey($_) } |
    ForEach-Object { $processMap[$_] } |
    Sort-Object @{ Expression = { [int]$_.ParentProcessId }; Descending = $true }, @{ Expression = { [int]$_.ProcessId }; Descending = $true }

if (-not $targets) {
    Write-Host "`nNo YouDownloader sessions were found." -ForegroundColor Green
    exit 0
}

Write-Step "Stopping processes"
$targets | Select-Object ProcessId, ParentProcessId, Name, CommandLine | Format-List

foreach ($process in $targets) {
    $targetProcessId = [int]$process.ProcessId
    try {
        Stop-Process -Id $targetProcessId -Force -ErrorAction Stop
    } catch {
        Write-Warning "Could not stop PID ${targetProcessId}: $($_.Exception.Message)"
    }
}

Start-Sleep -Seconds 1

$remainingMap = Get-ProcessCommandLineMap
$remaining = $targetIds |
    Where-Object { $remainingMap.ContainsKey($_) } |
    ForEach-Object { $remainingMap[$_] }

if ($remaining) {
    Write-Warning "Some processes may still be running:"
    $remaining | Select-Object ProcessId, ParentProcessId, Name, CommandLine | Format-List
    exit 1
}

Write-Host "`nAll YouDownloader sessions were stopped." -ForegroundColor Green
