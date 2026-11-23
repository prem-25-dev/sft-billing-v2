<#
  One-time setup on a new developer PC: checks the tools, creates the Python
  environment, and fetches Flutter packages.   Run from the repo root:
      powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Find-Tool($name, $candidates) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    return $null
}

$missing = @()

$python = Find-Tool "python" @()
if (-not $python) { $missing += "Python 3.11+  ->  https://www.python.org/downloads/ (tick 'Add python.exe to PATH')" }

$flutter = Find-Tool "flutter" @("D:\Dev\flutter\bin\flutter.bat", "C:\flutter\bin\flutter.bat", "$env:USERPROFILE\flutter\bin\flutter.bat")
if (-not $flutter) { $missing += "Flutter SDK  ->  https://docs.flutter.dev/get-started/install/windows/desktop  (or: git clone -b stable https://github.com/flutter/flutter.git C:\flutter  and add C:\flutter\bin to PATH)" }

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) { $missing += "Visual Studio with the 'Desktop development with C++' workload  ->  https://visualstudio.microsoft.com/downloads/" }

$iscc = Find-Tool "ISCC" @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")
if (-not $iscc) { $missing += "Inno Setup 6  ->  https://jrsoftware.org/isdl.php  (only needed to build the installer)" }

if ($missing.Count -gt 0) {
    Write-Host "`nInstall these first, then run this script again:`n" -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host "  - $_" }
    exit 1
}

Write-Host "Tools found. Creating Python environment..." -ForegroundColor Cyan
Set-Location "$root\backend"
if (-not (Test-Path ".venv")) { & $python -m venv .venv }
& .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt pyinstaller pytest

Write-Host "Fetching Flutter packages..." -ForegroundColor Cyan
Set-Location "$root\app"
& $flutter config --enable-windows-desktop | Out-Null
& $flutter pub get

Write-Host "`nSetup complete.  Next:" -ForegroundColor Green
Write-Host "   scripts\build.ps1   builds the installer  (installer\output\SFT-Billing-Setup-*.exe)"
Write-Host "   scripts\dev.ps1     runs the app for development"
