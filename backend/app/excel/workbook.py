"""Low-level workbook I/O: create, open, save, backup.

Nothing here knows about clients/invoices/payments as domain concepts —
that lives in app/services/*.py. This module only knows how to get a
correctly-shaped openpyxl Workbook on disk and how to save it safely.
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.excel.constants import ALL_SHEETS, HEADERS_BY_SHEET

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _resolve_application_data_dir(
    is_frozen: bool | None = None,
    local_appdata: str | None = None,
) -> Path:
    if is_frozen is None:
        is_frozen = getattr(sys, "frozen", False)
    if not is_frozen:
        return BASE_DIR

    if local_appdata is None:
        local_appdata = os.environ.get("LOCALAPPDATA")
    appdata = local_appdata
    if not appdata:
        raise RuntimeError("LOCALAPPDATA is required for persistent application data.")
    return Path(appdata).expanduser() / "SFT Billing"


APP_DATA_DIR = _resolve_application_data_dir()
DATA_DIR = APP_DATA_DIR / "data"
BACKUPS_DIR = APP_DATA_DIR / "backups"
WORKBOOK_PATH = DATA_DIR / "SFT_Billing.xlsx"

# All Excel reads/writes happen through this module, and every write is
# guarded by this lock — openpyxl has no concept of concurrent access, and
# a FastAPI dev server can service overlapping requests, so we serialize
# every workbook read+modify+save cycle to avoid a lost update or a
# corrupted file from two requests writing at once.
_lock = threading.RLock()


@contextmanager
def workbook_lock():
    with _lock:
        yield

HEADER_FILL = PatternFill(start_color="1F5A44", end_color="1F5A44", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def _style_header_row(ws: Worksheet, header_count: int) -> None:
    for col in range(1, header_count + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 20


def _autofit_columns(ws: Worksheet, header_count: int, width: int = 20) -> None:
    for col in range(1, header_count + 1):
        ws.column_dimensions[get_column_letter(col)].width = width


def create_new_workbook() -> Workbook:
    """Builds a brand-new workbook with all six sheets and styled headers, but writes no rows."""
    wb = Workbook()
    # Workbook() starts with one default sheet named "Sheet" — remove it
    # once the real sheets exist so it's never left behind confusingly.
    default_sheet_name = wb.sheetnames[0]

    for sheet_name in ALL_SHEETS:
        ws = wb.create_sheet(sheet_name)
        headers = HEADERS_BY_SHEET[sheet_name]
        ws.append(headers)
        _style_header_row(ws, len(headers))
        _autofit_columns(ws, len(headers))

    if default_sheet_name in wb.sheetnames:
        del wb[default_sheet_name]

    return wb


def ensure_workbook_exists() -> None:
    """Creates SFT_Billing.xlsx (with all sheets/headers) if it isn't already on disk."""
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        if not WORKBOOK_PATH.exists():
            wb = create_new_workbook()
            wb.save(WORKBOOK_PATH)


def _ensure_headers_present(ws: Worksheet, headers: list[str]) -> bool:
    """Append newly introduced headers without moving existing workbook columns."""
    existing = {
        ws.cell(row=1, column=column).value
        for column in range(1, ws.max_column + 1)
        if ws.cell(row=1, column=column).value
    }
    changed = False
    next_column = ws.max_column + 1
    for header in headers:
        if header in existing:
            continue
        ws.cell(row=1, column=next_column, value=header)
        existing.add(header)
        next_column += 1
        changed = True

    if changed:
        _style_header_row(ws, ws.max_column)
        _autofit_columns(ws, ws.max_column)
    return changed


def ensure_sheets_present(wb: Workbook) -> bool:
    """Add missing sheets and append new headers without moving existing data.

    This is also the workbook migration boundary for optional payment-proof
    metadata.  Existing Payments rows remain in place; missing proof headers
    are appended in the order declared by ``PAYMENTS_HEADERS`` and are blank
    until a later same-row enrichment succeeds.
    """
    changed = False
    for sheet_name in ALL_SHEETS:
        if sheet_name not in wb.sheetnames:
            ws = wb.create_sheet(sheet_name)
            headers = HEADERS_BY_SHEET[sheet_name]
            ws.append(headers)
            _style_header_row(ws, len(headers))
            _autofit_columns(ws, len(headers))
            changed = True

    for sheet_name in ALL_SHEETS:
        changed = _ensure_headers_present(wb[sheet_name], HEADERS_BY_SHEET[sheet_name]) or changed
    return changed


def load_workbook_safely() -> Workbook:
    """Opens the workbook, healing any missing sheet before handing it back."""
    ensure_workbook_exists()
    with _lock:
        try:
            wb = load_workbook(WORKBOOK_PATH)
        except Exception as exc:  # corrupted/locked file, etc.
            raise WorkbookAccessError(
                f"Could not open {WORKBOOK_PATH.name}. Close it in Excel if it's open, "
                f"or check it isn't corrupted. Original error: {exc}"
            ) from exc
        if ensure_sheets_present(wb):
            wb.save(WORKBOOK_PATH)
        return wb


def backup_workbook() -> Path | None:
    """Copies the current workbook into backups/ before a write, timestamped. No-op if the file doesn't exist yet."""
    with _lock:
        if not WORKBOOK_PATH.exists():
            return None
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUPS_DIR / f"SFT_Billing_{timestamp}.xlsx"
        shutil.copy2(WORKBOOK_PATH, backup_path)
        _prune_old_backups(keep=30)
        return backup_path


def _prune_old_backups(keep: int) -> None:
    backups = sorted(BACKUPS_DIR.glob("SFT_Billing_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in backups[keep:]:
        stale.unlink(missing_ok=True)


def save_workbook(wb: Workbook) -> None:
    """Backs up the current on-disk file, then saves. Raises WorkbookAccessError on failure (e.g. file open in Excel)."""
    with _lock:
        try:
            backup_workbook()
            wb.save(WORKBOOK_PATH)
        except PermissionError as exc:
            raise WorkbookAccessError(
                f"{WORKBOOK_PATH.name} is open in another program (likely Excel). "
                "Close it and try again."
            ) from exc
        except Exception as exc:
            raise WorkbookAccessError(f"Failed to save {WORKBOOK_PATH.name}: {exc}") from exc


class WorkbookAccessError(RuntimeError):
    """Raised when the workbook can't be read or written — locked, missing, or corrupted."""
