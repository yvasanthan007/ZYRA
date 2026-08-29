<#
.SYNOPSIS
    Installs a portable copy of Nmap for Zyra (no administrator rights needed).

.DESCRIPTION
    Downloads the official Nmap Windows installer from nmap.org and extracts
    the binaries with 7-Zip into a local folder. This makes Nmap usable by
    Zyra's NmapScanner without a system-wide install or a PATH change.

    Default install location:  %LOCALAPPDATA%\Zyra\tools\nmap
    Use -RepoBundle to install into <repo>\tools\nmap instead.

    After running this script, Zyra's NmapScanner auto-detects the portable copy:
       - ZYRA_NMAP_PATH env var        (explicit override)
       - <repo>\tools\nmap\nmap.exe    (bundled copy)
       - %LOCALAPPDATA%\Zyra\tools\nmap\nmap.exe

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\setup_nmap.ps1

.NOTES
    Requires 7-Zip (https://www.7-zip.org) and an internet connection.
#>
param(
    [string]$Version = "7.991",
    [switch]$RepoBundle
)

$ErrorActionPreference = "Stop"

function Find-7Zip {
    $exe = (Get-Command 7z -ErrorAction SilentlyContinue).Source
    if ($exe) { return $exe }
    foreach ($candidate in @(
        "$env:ProgramFiles\7-Zip\7z.exe",
        "${env:ProgramFiles(x86)}\7-Zip\7z.exe",
        "$env:LOCALAPPDATA\Programs\7-Zip\7z.exe"
    )) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

$7z = Find-7Zip
if (-not $7z) {
    Write-Error "7-Zip was not found. Install it from https://www.7-zip.org or add 7z.exe to your PATH."
}

$installRoot = if ($RepoBundle) {
    Join-Path $PSScriptRoot "nmap"
} else {
    Join-Path $env:LOCALAPPDATA "Zyra\tools\nmap"
}
$null = New-Item -ItemType Directory -Force -Path $installRoot

$installer = Join-Path $env:TEMP "nmap-$Version-setup.exe"
$url = "https://nmap.org/dist/nmap-$Version-setup.exe"

if (-not (Test-Path $installer)) {
    Write-Host "Downloading $url ..."
    curl.exe -L --retry 3 -o $installer $url
    if ($LASTEXITCODE -ne 0) { throw "Download failed (exit code $LASTEXITCODE)." }
}

Write-Host "Extracting Nmap to $installRoot ..."
& $7z x "-o$installRoot" -y $installer | Out-Null

# NSIS installers keep their payload under $PLUGINSDIR / $INSTDIR; promote the
# actual binaries to the install root so nmap.exe is found right away.
$plugDir = Join-Path $installRoot '$PLUGINSDIR'
if (Test-Path (Join-Path $plugDir "nmap.exe")) {
    Get-ChildItem $plugDir -File | Move-Item -Destination $installRoot -Force
    Remove-Item $plugDir -Recurse -Force
}
foreach ($inner in @("$installRoot\bin", "$installRoot\Nmap")) {
    if (Test-Path (Join-Path $inner "nmap.exe")) {
        Get-ChildItem $inner -File | Move-Item -Destination $installRoot -Force
        Remove-Item $inner -Recurse -Force
    }
}

$nmapExe = Join-Path $installRoot "nmap.exe"
if (-not (Test-Path $nmapExe)) {
    $found = Get-ChildItem $installRoot -Recurse -Filter "nmap.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($found) { $nmapExe = $found.FullName }
}
if (-not (Test-Path $nmapExe)) {
    Write-Error "Extraction failed: nmap.exe was not found under $installRoot"
}

Write-Host ""
Write-Host "Portable Nmap path: $nmapExe"
& $nmapExe --version | Select-Object -First 1
Write-Host ""
Write-Host "ZYRA's scanner will auto-detect this installation. To override, set:"
Write-Host "    [Environment]::SetEnvironmentVariable('ZYRA_NMAP_PATH', '$nmapExe', 'User')"