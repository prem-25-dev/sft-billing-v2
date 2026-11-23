# SFT Billing v2

Desktop GST billing for Windows. **Python** (FastAPI + SQLite) holds all the logic; **Flutter** is the UI.
Everything runs on the user's own PC — no server, no cloud.

```
backend/   FastAPI service, SQLAlchemy models, Alembic migrations, invoice PDF/Excel export
app/       Flutter Windows app (starts the service itself, talks to it on 127.0.0.1)
installer/ Inno Setup script (clean install / copy from another PC)
```

## What's in it
- Invoices in the exact Excel layout, previewed inline as PDF; download PDF or Excel
- Clients, products, payments, reports, business profile
- **First launch on a PC:** choose *Clean installation* or *Copy from another PC*, then create that PC's own user (username, mobile number, password). Forgot password = enter the registered mobile number.
- **Copy data** (sidebar): pick what to copy (clients & products, business profile, invoices & payments) and save one `.sftpack` file. User accounts are never copied.

## Moving to a new PC
1. Old PC: **Copy data** → choose what to copy → *Copy data to a file* → save the `.sftpack`.
2. New PC: run `SFT-Billing-Setup-vX.exe` → *Copy from another PC* → pick the file (or choose it inside the app on first launch).
3. Create the new PC's own user. Done.

Scripted install: `SFT-Billing-Setup-v2.0.0.exe /VERYSILENT /RESTORE="C:\path\data.sftpack"`.
Both PCs must run the same app version (the pack records the database schema version).

## Build
Requirements: Python 3.13, Flutter (Windows desktop + Visual Studio C++ tools), Inno Setup 6.

```powershell
# 1. backend service
cd backend
python -m venv .venv; .venv\Scripts\pip install -r requirements.txt pyinstaller
.venv\Scripts\python -m PyInstaller sft-billing-server.spec --noconfirm --distpath dist --workpath build

# 2. Flutter app
cd ..\app
flutter build windows --release

# 3. stage and package
cd ..
Copy-Item app\build\windows\x64\runner\Release _stage -Recurse
Copy-Item backend\dist\sft-billing-server _stage\backend -Recurse
ISCC installer\SFT-Billing.iss          # -> installer\output\SFT-Billing-Setup-v2.0.0.exe
```

## Develop
```powershell
cd backend; $env:SFT_BILLING_DATABASE_URL="sqlite:///dev.db"; $env:SFT_BILLING_MIGRATION_DATABASE_URL=$env:SFT_BILLING_DATABASE_URL; $env:SFT_BILLING_AUTO_INIT="1"
.venv\Scripts\python -m uvicorn app.main:app --port 8011
cd ..\app; $env:SFT_BACKEND_URL="http://127.0.0.1:8011"; flutter run -d windows
```
Tests: `cd backend; .venv\Scripts\python -m pytest tests`.

## Data location
`%LOCALAPPDATA%\SFT Billing\` — `sft_billing.db`, `service.log`. A clean install moves any existing data to `SFT Billing.old` (never deletes it).
