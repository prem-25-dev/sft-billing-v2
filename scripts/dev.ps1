<#
  Run the app for development: starts the Python service with a throw-away
  database and launches the Flutter UI against it.
      powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
  Flutter hot reload works in the terminal this opens (press r).
#>
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$flutter = (Get-Command flutter -ErrorAction SilentlyContinue).Source
if (-not $flutter) { foreach ($c in "D:\Dev\flutter\bin\flutter.bat", "C:\flutter\bin\flutter.bat", "$env:USERPROFILE\flutter\bin\flutter.bat") { if (Test-Path $c) { $flutter = $c; break } } }
if (-not $flutter) { throw "Flutter not found. Run scripts\setup.ps1 first." }

$db = "$root\backend\data\dev.db"
New-Item -ItemType Directory -Force "$root\backend\data" | Out-Null
$env:SFT_BILLING_DATABASE_URL = "sqlite:///" + ($db -replace '\\', '/')
$env:SFT_BILLING_MIGRATION_DATABASE_URL = $env:SFT_BILLING_DATABASE_URL
$env:SFT_BILLING_AUTO_INIT = "1"
$port = 8011

Write-Host "Starting service on http://127.0.0.1:$port (database: $db)" -ForegroundColor Cyan
$svc = Start-Process "$root\backend\.venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "app.main:app", "--port", $port -WorkingDirectory "$root\backend" -PassThru -WindowStyle Minimized
try {
    $env:SFT_BACKEND_URL = "http://127.0.0.1:$port"
    Set-Location "$root\app"
    & $flutter run -d windows
} finally {
    Stop-Process -Id $svc.Id -Force -ErrorAction SilentlyContinue
}
