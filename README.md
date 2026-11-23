# SFT Billing v2

Desktop GST billing for Windows. **Python** (FastAPI + SQLite) holds all the logic; **Flutter** is the UI.
Everything runs on the user's own PC — no server, no cloud.

## Just want to use it?
Download **`SFT-Billing-Setup-v2.0.0.exe`** from the [Releases page](../../releases/latest), run it, and choose:
- **Clean installation** – start fresh with a new user, or
- **Copy from another PC** – load a data file made with *Copy data* on your other PC.

Then create your own username, mobile number and password. (Windows may show a SmartScreen warning because the installer isn't code-signed: *More info → Run anyway*.)

## Want to change the code?
```powershell
git clone https://github.com/prem-25-dev/sft-billing-v2.git
cd sft-billing-v2
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # checks tools, creates venv, fetches packages
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1     # run the app (hot reload: press r)
powershell -ExecutionPolicy Bypass -File scripts\build.ps1   # build the installer
```
You need: **Python 3.11+**, **Flutter** (Windows desktop), **Visual Studio** with *Desktop development with C++*, and **Inno Setup 6** (installer only). `setup.ps1` tells you what's missing and where to get it.
The installer ends up in `installer\output\`.

```
backend/   FastAPI service, SQLAlchemy models, Alembic migrations, invoice PDF/Excel export, tests
app/       Flutter Windows app (starts the service itself and talks to it on 127.0.0.1)
installer/ Inno Setup script (clean install / copy from another PC)
scripts/   setup.ps1, dev.ps1, build.ps1
```

| Where to change | What |
|---|---|
| `app/lib/screens/` | Screens (setup wizard, login, each page) |
| `app/lib/core/theme.dart` | Colours and styling |
| `backend/app/routes/` | API endpoints |
| `backend/app/services/` | Business logic (invoices, payments, transfer) |
| `backend/migrations/versions/` | Database changes (add a new Alembic file for each) |
| `installer/SFT-Billing.iss` | Installer pages and options |

Backend tests: `cd backend; .venv\Scripts\python -m pytest tests`.

## What's in it
- Invoices in the exact Excel layout, previewed inline as PDF; download PDF or Excel
- Clients, products, payments, reports, business profile
- **First launch on a PC:** *Clean installation* or *Copy from another PC*, then create that PC's own user (username, mobile number, password). Forgot password = enter the registered mobile number.
- **Copy data** (sidebar): choose what to copy (clients & products, business profile, invoices & payments) and save one `.sftpack` file. User accounts are never copied.

## Moving to a new PC
1. Old PC: **Copy data** → choose what to copy → *Copy data to a file* → save the `.sftpack`.
2. New PC: run the installer → *Copy from another PC* → pick the file (or choose it inside the app on first launch).
3. Create the new PC's own user. Done.

Scripted install: `SFT-Billing-Setup-v2.0.0.exe /VERYSILENT /RESTORE="C:\path\data.sftpack"`.
Both PCs must run the same app version (the pack records the database schema version).

## Notes
- Password reset by mobile number does **not** send an OTP (the app has no SMS service): anyone at the PC who knows the number can reset the password. Add a real OTP before using it for sensitive data.
- Data lives in `%LOCALAPPDATA%\SFT Billing\` (`sft_billing.db`, `service.log`). A clean install moves any existing data to `SFT Billing.old`; it never deletes it.
