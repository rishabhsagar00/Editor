"""Row insertion: pixel path (JPG/PNG/scanned) + vector path (digital PDF)."""
import cv2
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

try:
    import fitz
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False


def _load_font(size: int):
    # Use own-product font if provided, else default sans (DejaVu/Arial-like)
    for p in ["/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            if Path(p).exists():
                return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def insert_image_row(image_path: str, out_path: str, rows: list,
                     after_index: int, template_index: int, new_values: list) -> dict:
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("cannot read image")
    H, W = img.shape[:2]
    if not rows:
        raise ValueError("no rows detected")
    after_index = max(-1, min(after_index, len(rows) - 1))
    template_index = max(0, min(template_index, len(rows) - 1))

    t = rows[template_index]
    ty0, ty1 = int(round(t["y0"])), int(round(t["y1"]))
    # clamp template to image (coords may be in preview scale -> rescale)
    # If rows came from a scaled preview, rescale by H / preview_h heuristic:
    # caller must pass rows in image pixels; we trust them here.
    ty0 = max(0, min(ty0, H - 2)); ty1 = max(ty0 + 5, min(ty1, H))
    th = ty1 - ty0

    insert_y = int(round(rows[after_index]["y1"])) if after_index >= 0 else int(round(rows[0]["y0"]))
    insert_y = max(0, min(insert_y, H))

    template = img[ty0:ty1, 0:W].copy()

    # Clean old text: sample background (median of border area) and fill inner area
    # Keep 2px top/bottom borders from template, clear middle
    cleaned = template.copy()
    bg = np.median(template[3:-3, 5:-5].reshape(-1, 3), axis=0) if th > 8 else np.median(template.reshape(-1, 3), axis=0)
    border = 2
    cleaned[border:th - border, 1:W - 1] = bg

    # Shift bottom down
    new_H = H + th
    canvas = np.full((new_H, W, 3), 255, dtype=np.uint8)
    canvas[0:insert_y] = img[0:insert_y]
    canvas[insert_y:insert_y + th] = cleaned
    canvas[insert_y + th:] = img[insert_y:H]

    # Typeset new values: split width evenly (or use template column splits if known)
    n = max(1, len(new_values))
    pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    dr = ImageDraw.Draw(pil)
    font_size = max(10, int(th * 0.42))
    font = _load_font(font_size)
    col_w = W / n
    for i, val in enumerate(new_values):
        cx = int(i * col_w + 8)
        cy = int(insert_y + (th - font_size) / 2 - 1)
        # text color: near-black (sample from template text if possible)
        dr.text((cx, cy), str(val), fill=(20, 20, 20), font=font)

    # Redraw horizontal rules to match (1px dark line top+bottom of new row)
    line_color = (60, 60, 60)
    cv_out = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    cv2.line(cv_out, (0, insert_y), (W - 1, insert_y), line_color, 1, cv2.LINE_AA)
    cv2.line(cv_out, (0, insert_y + th - 1), (W - 1, insert_y + th - 1), line_color, 1, cv2.LINE_AA)

    cv2.imwrite(out_path, cv_out)
    return {"out_height": int(new_H), "row_height": int(th), "insert_y": int(insert_y)}


def insert_pdf_digital_row(pdf_path: str, out_path: str, page_num: int,
                           after_index: int, template_index: int, new_values: list) -> dict:
    """Vector-preserving insert: copy drawings+text with y-shift, reuse fonts."""
    if not HAS_FITZ:
        raise RuntimeError("PyMuPDF required")
    src = fitz.open(pdf_path)
    if page_num >= len(src):
        page_num = 0
    page = src[page_num]
    rect = page.rect
    drawings = page.get_drawings()
    tdict = page.get_text("dict")

    # Rebuild row bands from text (same grouping as detect)
    spans = []
    for b in tdict.get("blocks", []):
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                if s.get("text", "").strip():
                    spans.append(s)
    spans_sorted = sorted(spans, key=lambda s: s["bbox"][1])
    groups = []
    for s in spans_sorted:
        placed = False
        for g in groups:
            if abs(g[0]["bbox"][1] - s["bbox"][1]) < 3.5:
                g.append(s); placed = True; break
        if not placed:
            groups.append([s])
    if not groups:
        src.close()
        raise ValueError("no text rows found in digital PDF")
    after_index = max(-1, min(after_index, len(groups) - 1))
    template_index = max(0, min(template_index, len(groups) - 1))

    tg = sorted(groups[template_index], key=lambda s: s["bbox"][0])
    t_y0 = min(s["bbox"][1] for s in tg) - 3
    t_y1 = max(s["bbox"][3] for s in tg) + 3
    th = t_y1 - t_y0
    insert_y = (max(s["bbox"][3] for s in groups[after_index]) + 3) if after_index >= 0 else (min(s["bbox"][1] for s in groups[0]) - 3)

    new_doc = fitz.open()
    # copy all pages, patch target page by redrawing with offset
    for pi in range(len(src)):
        sp = src[pi]
        npage = new_doc.new_page(width=rect.width, height=rect.height + (th if pi == page_num else 0))
        if pi != page_num:
            npage.show_pdf_page(npage.rect, src, pi)
            continue
        # drawings
        for d in drawings:
            r = d["rect"]
            # shift items at/below insert line
            dy = th if r.y0 >= insert_y - 1 else 0
            nr = fitz.Rect(r.x0, r.y0 + dy, r.x1, r.y1 + dy)
            try:
                if d["type"] == "re" or (nr.width > 5 and nr.height > 5):
                    npage.draw_rect(nr, color=d.get("color"), fill=d.get("fill"), width=d.get("width", 0.5))
                else:
                    npage.draw_line(nr.top_left, nr.bottom_right if nr.width < 3 else nr.top_right,
                                    color=d.get("color"), width=d.get("width", 0.5))
            except Exception:
                continue
        # template row rect clone (border)
        # infer template rect from drawings overlapping template band, else full width
        t_rects = [d["rect"] for d in drawings
                   if not (d["rect"].y1 < t_y0 - 2 or d["rect"].y0 > t_y1 + 2)]
        if t_rects:
            tx0 = min(r.x0 for r in t_rects); tx1 = max(r.x1 for r in t_rects)
        else:
            tx0, tx1 = 36, rect.width - 36
        try:
            npage.draw_rect(fitz.Rect(tx0, insert_y, tx1, insert_y + th), color=(0, 0, 0), width=0.5)
        except Exception:
            pass
        # texts: shift + clone template with new values
        for b in tdict.get("blocks", []):
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    x0, y0, x1, y1 = s["bbox"]
                    dy = th if y0 >= insert_y - 1 else 0
                    try:
                        npage.insert_text(fitz.Point(x0, y1 + dy - 1),
                                          s["text"], fontsize=s.get("size", 9),
                                          fontname="helv" if "helv" in s.get("font", "").lower() else s.get("font", "helv"),
                                          color=None)
                    except Exception:
                        try:
                            npage.insert_text(fitz.Point(x0, y1 + dy - 1), s["text"], fontsize=s.get("size", 9))
                        except Exception:
                            continue
        # new row values: place evenly across template columns
        cols = sorted(tg, key=lambda s: s["bbox"][0])
        if new_values:
            # column x positions from template spans
            if len(new_values) == len(cols):
                xs = [c["bbox"][0] for c in cols]
            else:
                xs = [tx0 + 4 + i * ((tx1 - tx0 - 8) / len(new_values)) for i in range(len(new_values))]
            ref = cols[0] if cols else {"size": 9, "font": "helv"}
            for x, val in zip(xs, new_values):
                try:
                    npage.insert_text(fitz.Point(x, insert_y + th - 4),
                                      str(val), fontsize=ref.get("size", 9),
                                      fontname="helv")
                except Exception:
                    continue
    new_doc.save(out_path)
    new_doc.close(); src.close()
    return {"row_height": float(th), "insert_y": float(insert_y)}
