"""Render one worksheet of an .xlsx file to PDF, cell for cell.

Reads the filled invoice workbook with openpyxl and draws it with ReportLab:
column widths, row heights, merged ranges, fills, borders, fonts, alignment,
wrapping, embedded images and the sheet's print area / fit-to-page setup.
It needs no Microsoft Office and no printer, so the PDF is the Excel invoice
layout on any machine.
"""
from __future__ import annotations

import os
import re
import sys
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter, range_boundaries
from reportlab.lib.pagesizes import A3, A4, A5, LEGAL, LETTER, landscape
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

_PAPER = {1: LETTER, 5: LEGAL, 8: A3, 9: A4, 11: A5}

# Office default theme palette (index → RGB) for theme-coloured fills / fonts.
_THEME = ["FFFFFF", "000000", "E7E6E6", "44546A", "4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47"]
_INDEXED = {8: "000000", 9: "FFFFFF", 10: "FF0000", 11: "00FF00", 12: "0000FF", 13: "FFFF00", 64: "000000"}

_BORDER_WIDTH = {"hair": 0.25, "thin": 0.6, "dotted": 0.6, "dashed": 0.6, "dashDot": 0.6, "medium": 1.4,
                 "mediumDashed": 1.4, "thick": 2.2, "double": 1.6}
_DASH = {"dotted": (0.8, 1.2), "dashed": (3, 2), "dashDot": (3, 1.5), "mediumDashed": (4, 2)}

_FONT_DIRS = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts", Path("/usr/share/fonts/truetype"),
              Path("/Library/Fonts"), Path("/System/Library/Fonts")]
_FONT_FILES = {  # family (lower) → (regular, bold, italic, bold-italic)
    "calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "arial rounded mt bold": ("ARLRDBD.TTF", "ARLRDBD.TTF", "ARLRDBD.TTF", "ARLRDBD.TTF"),
    "times new roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "segoe ui": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "aptos": ("aptos.ttf", "aptos-bold.ttf", "aptos-italic.ttf", "aptos-bold-italic.ttf"),
    "aptos display": ("aptos-display.ttf", "aptos-display-bold.ttf", "aptos-display.ttf", "aptos-display-bold.ttf"),
}
_FALLBACK_ORDER = ("calibri", "arial", "segoe ui")
_registered: dict[str, str | None] = {}


def _find_font_file(filename: str) -> Path | None:
    for base in _FONT_DIRS:
        direct = base / filename
        if direct.is_file():
            return direct
        if base.is_dir() and base.name != "Fonts":
            for found in base.rglob(filename):
                return found
    return None


def _font_name(family: str | None, bold: bool, italic: bool) -> tuple[str, bool]:
    """Return (reportlab font name, has_rupee_glyph)."""
    key = (family or "calibri").strip().lower()
    index = (1 if bold else 0) + (2 if italic else 0)
    index = {0: 0, 1: 1, 2: 2, 3: 3}[index]
    for candidate in (key, *_FALLBACK_ORDER):
        files = _FONT_FILES.get(candidate)
        if not files:
            continue
        reg_name = f"x:{candidate}:{index}"
        if reg_name not in _registered:
            path = _find_font_file(files[index]) or (_find_font_file(files[0]) if index else None)
            if path is None:
                _registered[reg_name] = None
            else:
                try:
                    pdfmetrics.registerFont(TTFont(reg_name, str(path)))
                    _registered[reg_name] = reg_name
                except Exception:
                    _registered[reg_name] = None
        if _registered[reg_name]:
            face = pdfmetrics.getFont(reg_name).face
            return reg_name, 0x20B9 in face.charToGlyph
    base = "Helvetica"
    if bold and italic:
        return "Helvetica-BoldOblique", False
    if bold:
        return "Helvetica-Bold", False
    if italic:
        return "Helvetica-Oblique", False
    return base, False


def _rgb(color: Any, default: str | None = None) -> tuple[float, float, float] | None:
    if color is None:
        return _hex(default) if default else None
    kind = getattr(color, "type", None)
    value: str | None = None
    if kind == "rgb" and isinstance(color.rgb, str):
        value = color.rgb[-6:]
    elif kind == "theme" and color.theme is not None and color.theme < len(_THEME):
        value = _tint(_THEME[color.theme], color.tint or 0)
    elif kind == "indexed" and color.indexed in _INDEXED:
        value = _INDEXED[color.indexed]
    if value is None:
        return _hex(default) if default else None
    return _hex(value)


def _hex(value: str) -> tuple[float, float, float]:
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _tint(hex_value: str, tint: float) -> str:
    if not tint:
        return hex_value
    channels = [int(hex_value[i:i + 2], 16) for i in (0, 2, 4)]
    out = [round(c * (1 + tint)) if tint < 0 else round(c + (255 - c) * tint) for c in channels]
    return "".join(f"{max(0, min(255, c)):02X}" for c in out)


def _col_points(width: float | None, default: float = 8.43) -> float:
    chars = default if width is None else width
    return max(0.0, (chars * 7 + 5) * 0.75) if chars else 0.0


def _format_value(cell: Any) -> str:
    value = cell.value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        fmt = (cell.number_format or "General").lower()
        number = float(value)
        decimals = None
        match = re.search(r"0\.(0+)", fmt)
        if match:
            decimals = len(match.group(1))
        elif fmt in ("0", "#,##0"):
            decimals = 0
        if decimals is None:
            text = f"{number:.10g}"
        else:
            text = f"{number:,.{decimals}f}" if "," in fmt else f"{number:.{decimals}f}"
        return text
    if hasattr(value, "strftime"):
        return value.strftime("%d-%m-%Y")
    return str(value)


def _print_bounds(ws: Any) -> tuple[int, int, int, int]:
    area = ws.print_area
    if isinstance(area, (list, tuple)):
        area = area[0] if area else None
    if area:
        ref = str(area).split("!")[-1].replace("$", "")
        min_col, min_row, max_col, max_row = range_boundaries(ref.split(",")[0])
        return min_col, min_row, max_col, max_row
    return 1, 1, ws.max_column, ws.max_row


def render_sheet_pdf(xlsx_bytes: bytes, sheet_name: str) -> bytes:
    workbook = openpyxl.load_workbook(BytesIO(xlsx_bytes))
    ws = workbook[sheet_name]
    min_col, min_row, max_col, max_row = _print_bounds(ws)

    default_row = ws.sheet_format.defaultRowHeight or 15.0
    default_col = ws.sheet_format.defaultColWidth or ws.sheet_format.baseColWidth or 8.43

    col_w: dict[int, float] = {}
    for c in range(min_col, max_col + 1):
        dim = ws.column_dimensions.get(get_column_letter(c))
        # Grouped dimensions (min..max) are stored on the first letter only.
        width = dim.width if dim is not None and dim.width is not None else None
        if width is None:
            for key, other in ws.column_dimensions.items():
                if other.min and other.max and other.min <= c <= other.max and other.width is not None:
                    width = other.width
                    dim = other
                    break
        hidden = bool(dim.hidden) if dim is not None else False
        col_w[c] = 0.0 if hidden else _col_points(width if width is not None else default_col)
    row_h: dict[int, float] = {}
    for r in range(min_row, max_row + 1):
        dim = ws.row_dimensions.get(r)
        height = dim.height if dim is not None and dim.height is not None else default_row
        row_h[r] = 0.0 if (dim is not None and dim.hidden) else float(height)

    col_x: dict[int, float] = {}
    x = 0.0
    for c in range(min_col, max_col + 1):
        col_x[c] = x
        x += col_w[c]
    total_w = x
    row_y: dict[int, float] = {}
    y = 0.0
    for r in range(min_row, max_row + 1):
        row_y[r] = y
        y += row_h[r]
    total_h = y

    # Page setup
    paper = _PAPER.get(ws.page_setup.paperSize or 9, A4)
    if (ws.page_setup.orientation or "portrait") == "landscape":
        paper = landscape(paper)
    page_w, page_h = paper
    margin = ws.page_margins
    left, right, top, bottom = (m * 72 for m in (margin.left or 0.7, margin.right or 0.7, margin.top or 0.75, margin.bottom or 0.75))
    avail_w, avail_h = page_w - left - right, page_h - top - bottom
    fit = bool(ws.sheet_properties.pageSetUpPr and ws.sheet_properties.pageSetUpPr.fitToPage)
    if fit:
        scale = min(1.0, avail_w / total_w, avail_h / total_h)  # Excel's "fit to" only shrinks
    else:
        scale = (ws.page_setup.scale or 100) / 100
    origin_x = left + (max(0.0, (avail_w - total_w * scale) / 2) if ws.print_options.horizontalCentered else 0.0)
    origin_y = page_h - top  # top of the drawing area

    merged_anchor: dict[tuple[int, int], tuple[int, int, int, int]] = {}
    merged_member: set[tuple[int, int]] = set()
    for rng in ws.merged_cells.ranges:
        a_col, a_row, b_col, b_row = rng.min_col, rng.min_row, rng.max_col, rng.max_row
        merged_anchor[(a_row, a_col)] = (a_row, a_col, b_row, b_col)
        for rr in range(a_row, b_row + 1):
            for cc in range(a_col, b_col + 1):
                if (rr, cc) != (a_row, a_col):
                    merged_member.add((rr, cc))

    def rect(r1: int, c1: int, r2: int, c2: int) -> tuple[float, float, float, float]:
        c1, c2 = max(c1, min_col), min(c2, max_col)
        r1, r2 = max(r1, min_row), min(r2, max_row)
        x0 = col_x[c1]
        x1 = col_x[c2] + col_w[c2]
        y0 = row_y[r1]
        y1 = row_y[r2] + row_h[r2]
        return x0, y0, x1 - x0, y1 - y0  # y measured downward from the top

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=paper)
    pdf.setTitle(sheet_name)
    pdf.saveState()
    pdf.translate(origin_x, origin_y)
    pdf.scale(scale, scale)

    def Y(v: float) -> float:  # downward → canvas up
        return -v

    # 1) fills
    for r in range(min_row, max_row + 1):
        for c in range(min_col, max_col + 1):
            if (r, c) in merged_member:
                continue
            cell = ws.cell(r, c)
            fill = cell.fill
            if fill is None or fill.fill_type != "solid":
                continue
            color = _rgb(fill.fgColor)
            if color is None:
                continue
            r1, c1, r2, c2 = merged_anchor.get((r, c), (r, c, r, c))
            x0, y0, w, h = rect(r1, c1, r2, c2)
            pdf.setFillColorRGB(*color)
            pdf.rect(x0, Y(y0 + h), w, h, stroke=0, fill=1)

    # 2) images
    for image in getattr(ws, "_images", []):
        anchor = image.anchor
        try:
            start = anchor._from
            x0 = col_x.get(start.col + 1, 0.0) + (start.colOff or 0) / 12700
            y0 = row_y.get(start.row + 1, 0.0) + (start.rowOff or 0) / 12700
            if hasattr(anchor, "to") and anchor.to is not None:
                end = anchor.to
                x1 = col_x.get(end.col + 1, total_w) + (end.colOff or 0) / 12700
                y1 = row_y.get(end.row + 1, total_h) + (end.rowOff or 0) / 12700
            else:
                x1 = x0 + image.width * 0.75
                y1 = y0 + image.height * 0.75
            reader = ImageReader(BytesIO(image._data()))
            pdf.drawImage(reader, x0, Y(y1), width=x1 - x0, height=y1 - y0, mask="auto", preserveAspectRatio=False)
        except Exception:
            continue

    # 3) borders (per underlying cell, so merged edges keep their lines)
    def side(cell_border: Any, x_a: float, y_a: float, x_b: float, y_b: float) -> None:
        if cell_border is None or not cell_border.style:
            return
        style = cell_border.style
        pdf.setLineWidth(_BORDER_WIDTH.get(style, 0.6))
        color = _rgb(cell_border.color, "000000") or (0, 0, 0)
        pdf.setStrokeColorRGB(*color)
        pdf.setDash(*_DASH[style]) if style in _DASH else pdf.setDash()
        pdf.line(x_a, Y(y_a), x_b, Y(y_b))

    span_of: dict[tuple[int, int], tuple[int, int, int, int]] = {}
    for (ar, ac), (sr1, sc1, sr2, sc2) in merged_anchor.items():
        for rr in range(sr1, sr2 + 1):
            for cc in range(sc1, sc2 + 1):
                span_of[(rr, cc)] = (sr1, sc1, sr2, sc2)

    for r in range(min_row, max_row + 1):
        for c in range(min_col, max_col + 1):
            cell = ws.cell(r, c)
            border = cell.border
            if border is None:
                continue
            x0, y0, w, h = rect(r, c, r, c)
            if w <= 0 or h <= 0:
                continue
            # Inside a merged range Excel only draws the outer edge.
            sr1, sc1, sr2, sc2 = span_of.get((r, c), (r, c, r, c))
            if r == sr1:
                side(border.top, x0, y0, x0 + w, y0)
            if r == sr2:
                side(border.bottom, x0, y0 + h, x0 + w, y0 + h)
            if c == sc1:
                side(border.left, x0, y0, x0, y0 + h)
            if c == sc2:
                side(border.right, x0 + w, y0, x0 + w, y0 + h)
    pdf.setDash()

    # 4) text
    def is_empty(rr: int, cc: int) -> bool:
        if (rr, cc) in merged_member:
            return False
        return ws.cell(rr, cc).value in (None, "")

    for (r, c), (r1, c1, r2, c2) in [((k[0], k[1]), v) for k, v in merged_anchor.items()] + [
        ((r, c), (r, c, r, c)) for r in range(min_row, max_row + 1) for c in range(min_col, max_col + 1)
        if (r, c) not in merged_anchor and (r, c) not in merged_member
    ]:
        if not (min_row <= r <= max_row and min_col <= c <= max_col):
            continue
        cell = ws.cell(r, c)
        text = _format_value(cell)
        if not text.strip():
            continue
        font = cell.font
        size = float(font.sz or 11)
        face, has_rupee = _font_name(font.name, bool(font.b), bool(font.i))
        if not has_rupee:
            text = text.replace("₹", "Rs.")
        color = _rgb(font.color, "000000") or (0, 0, 0)
        x0, y0, w, h = rect(r1, c1, r2, c2)
        align = cell.alignment
        horizontal = align.horizontal or ("right" if isinstance(cell.value, (int, float, Decimal)) else "left")
        vertical = align.vertical or "bottom"
        wrap = bool(align.wrap_text)
        pad = 2.0 + (float(align.indent or 0) * 6 if horizontal == "left" else 0.0)

        # Excel lets plain text overflow into empty neighbours; clip there.
        clip_x0, clip_x1 = x0, x0 + w
        if not wrap:
            if horizontal in ("left", "general", "justify", "fill"):
                cc = c2 + 1
                while cc <= max_col and is_empty(r1, cc):
                    clip_x1 = col_x[cc] + col_w[cc]
                    cc += 1
            elif horizontal == "right":
                cc = c1 - 1
                while cc >= min_col and is_empty(r1, cc):
                    clip_x0 = col_x[cc]
                    cc -= 1
            else:  # centre: overflow both sides while empty
                lc, rc = c1 - 1, c2 + 1
                while lc >= min_col and is_empty(r1, lc):
                    clip_x0 = col_x[lc]
                    lc -= 1
                while rc <= max_col and is_empty(r1, rc):
                    clip_x1 = col_x[rc] + col_w[rc]
                    rc += 1

        if align.shrink_to_fit and not wrap:
            width_now = pdfmetrics.stringWidth(text, face, size)
            if width_now > w - 2 * pad:
                size = max(4.0, size * (w - 2 * pad) / width_now)

        pdf.saveState()
        clip = pdf.beginPath()
        clip.rect(clip_x0, Y(y0 + h), clip_x1 - clip_x0, h)
        pdf.clipPath(clip, stroke=0, fill=0)
        pdf.setFillColorRGB(*color)
        pdf.setFont(face, size)
        leading = size * 1.2
        lines = simpleSplit(text, face, size, max(1.0, w - 2 * pad)) if wrap else text.split("\n")
        block_h = leading * len(lines)
        if vertical == "top":
            first_base = y0 + 1.5 + size
        elif vertical in ("center", "distributed", "justify"):
            first_base = y0 + (h - block_h) / 2 + size
        else:
            first_base = y0 + h - 1.5 - block_h + size
        for i, line in enumerate(lines):
            base = first_base + i * leading
            text_w = pdfmetrics.stringWidth(line, face, size)
            if horizontal == "center":
                tx = x0 + (w - text_w) / 2
            elif horizontal == "right":
                tx = x0 + w - pad - text_w
            else:
                tx = x0 + pad
            pdf.drawString(tx, Y(base) + size * 0.2, line)
            if font.u:
                pdf.setLineWidth(0.5)
                pdf.setStrokeColorRGB(*color)
                pdf.line(tx, Y(base) - 0.5, tx + text_w, Y(base) - 0.5)
        pdf.restoreState()

    pdf.restoreState()
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
