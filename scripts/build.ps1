<#
  Builds everything and produces the installer.
      powershell -ExecutionPolicy Bypass -File scripts\build.ps1
  Output: installer\output\SFT-Billing-Setup-v<version>.exe
#>
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Find-Tool($name, $candidates) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    throw "$name not found. Run scripts\setup.ps1 first."
}
$flutter = Find-Tool "flutter" @("D:\Dev\flutter\bin\flutter.bat", "C:\flutter\bin\flutter.bat", "$env:USERPROFILE\flutter\bin\flutter.bat")
$iscc = Find-Tool "ISCC" @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")
$py = "$root\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Python environment missing. Run scripts\setup.ps1 first." }

Write-Host "[1/4] Backend service (PyInstaller)..." -ForegroundColor Cyan
Set-Location "$root\backend"
& $py -m PyInstaller sft-billing-server.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE) { throw "PyInstaller failed" }

Write-Host "[2/4] Flutter app (release)..." -ForegroundColor Cyan
Set-Location "$root\app"
& $flutter build windows --release
if ($LASTEXITCODE) { throw "Flutter build failed" }

Write-Host "[3/4] Staging files..." -ForegroundColor Cyan
Set-Location $root
Remove-Item -Recurse -Force "_stage" -ErrorAction SilentlyContinue
Copy-Item "app\build\windows\x64\runner\Release" "_stage" -Recurse
Copy-Item "backend\dist\sft-billing-server" "_stage\backend" -Recurse

Write-Host "[4/4] Installer (Inno Setup)..." -ForegroundColor Cyan
& $iscc "installer\SFT-Billing.iss"
if ($LASTEXITCODE) { throw "Inno Setup failed" }

$exe = Get-ChildItem "installer\output\*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host "`nDone: $($exe.FullName)" -ForegroundColor Green
