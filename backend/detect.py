"""Row detection for images + PDFs (own-product tables)."""
import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False


def _rows_from_y_bands(y_lines: List[float], x0: float, x1: float) -> List[Dict]:
    y_lines = sorted(y_lines)
    rows = []
    for i in range(len(y_lines) - 1):
        y0, y1 = float(y_lines[i]), float(y_lines[i + 1])
        if y1 - y0 < 8:  # skip hairline noise
            continue
        rows.append({
            "index": len(rows),
            "x0": float(x0), "x1": float(x1),
            "y0": y0, "y1": y1,
            "height": float(y1 - y0),
            "text": "",
            "cells": [],
        })
    return rows


def detect_image_rows(image_path: str) -> List[Dict]:
    """Detect table rows in JPG/PNG via horizontal lines + contour fallback."""
    img = cv2.imread(image_path)
    if img is None:
        return []
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Horizontal lines: wide kernel
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, w // 10), 1))
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, h_kernel)
    # Find line y positions
    contours, _ = cv2.findContours(horiz, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    y_lines = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw > w * 0.4 and ch < 10:  # long horizontal rule
            y_lines.append(y + ch / 2)
    y_lines = sorted(y_lines)

    if len(y_lines) >= 2:
        return _rows_from_y_bands(y_lines, 0, w)

    # Fallback: text-line bands via dilated contours
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (w // 6, 3))
    dilated = cv2.dilate(bw, kernel, iterations=1)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    bands = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw > w * 0.3 and 10 < ch < h * 0.4:
            bands.append((y, y + ch))
    bands = sorted(bands)
    # Merge overlaps
    merged = []
    for y0, y1 in bands:
        if merged and y0 < merged[-1][1] + 4:
            merged[-1] = (merged[-1][0], max(merged[-1][1], y1))
        else:
            merged.append((y0, y1))
    rows = []
    for i, (y0, y1) in enumerate(merged):
        rows.append({"index": i, "x0": 0.0, "x1": float(w),
                     "y0": float(y0), "y1": float(y1),
                     "height": float(y1 - y0), "text": "", "cells": []})
    return rows


def detect_pdf_rows(pdf_path: str, page_num: int = 0, dpi: int = 200) -> Dict:
    """Returns {kind: digital|scanned, rows, page_rect, ...}."""
    if not HAS_FITZ:
        raise RuntimeError("PyMuPDF not installed")
    doc = fitz.open(pdf_path)
    if page_num >= len(doc):
        page_num = 0
    page = doc[page_num]
    rect = page.rect
    d = page.get_text("dict")

    # Collect spans with y
    spans = []
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            for s in line.get("spans", []):
                if s.get("text", "").strip():
                    spans.append(s)
    doc.close()

    if len(spans) >= 3:
        # Group by baseline y (tolerance 3pt)
        spans_sorted = sorted(spans, key=lambda s: s["bbox"][1])
        groups: List[List[dict]] = []
        for s in spans_sorted:
            y = s["bbox"][1]
            placed = False
            for g in groups:
                if abs(g[0]["bbox"][1] - y) < 3.5:
                    g.append(s)
                    placed = True
                    break
            if not placed:
                groups.append([s])
        rows = []
        for i, g in enumerate(groups):
            y0 = min(s["bbox"][1] for s in g)
            y1 = max(s["bbox"][3] for s in g)
            # pad to include cell borders
            y0 = max(0, y0 - 3)
            y1 = y1 + 3
            cells = sorted([s["text"] for s in g], key=lambda _: 0)
            # keep left-to-right order
            g_sorted = sorted(g, key=lambda s: s["bbox"][0])
            rows.append({
                "index": i,
                "x0": float(min(s["bbox"][0] for s in g)),
                "x1": float(max(s["bbox"][2] for s in g)),
                "y0": float(y0), "y1": float(y1),
                "height": float(y1 - y0),
                "text": " | ".join(s["text"] for s in g_sorted),
                "cells": [s["text"] for s in g_sorted],
                "fonts": [{"font": s.get("font"), "size": s.get("size"), "color": s.get("color")} for s in g_sorted],
            })
        return {"kind": "digital", "rows": rows,
                "page_width": float(rect.width), "page_height": float(rect.height)}

    # Scanned: render and use image detection (scale back to PDF points)
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    pix = page.get_pixmap(dpi=dpi)
    tmp = f"/tmp/_scan_preview_{page_num}.png"
    pix.save(tmp)
    doc.close()
    scale = 72 / dpi  # px -> pt
    img_rows = detect_image_rows(tmp)
    rows = []
    for r in img_rows:
        rows.append({**r, "y0": r["y0"] * scale, "y1": r["y1"] * scale,
                     "x0": r["x0"] * scale, "x1": r["x1"] * scale,
                     "height": r["height"] * scale})
    return {"kind": "scanned", "rows": rows,
            "page_width": float(rect.width), "page_height": float(rect.height)}
