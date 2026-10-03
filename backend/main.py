"""FastAPI backend: upload / detect-rows / insert-row / export."""
import uuid
import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

try:
    from detect import detect_image_rows, detect_pdf_rows
    from insert import insert_image_row, insert_pdf_digital_row
except ImportError:  # allow `uvicorn backend.main:app` from repo root
    from backend.detect import detect_image_rows, detect_pdf_rows
    from backend.insert import insert_image_row, insert_pdf_digital_row

try:
    import fitz
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

BASE = Path(__file__).parent
STORE = BASE / "storage"
STORE.mkdir(exist_ok=True)

app = FastAPI(title="RowInsert API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
app.mount("/files", StaticFiles(directory=str(STORE)), name="files")


class DetectReq(BaseModel):
    sessionId: str
    page: int = 0


class InsertReq(BaseModel):
    sessionId: str
    page: int = 0
    afterIndex: int = 0
    templateIndex: int = 0
    newValues: List[str] = []


def _session_dir(sid: str) -> Path:
    d = STORE / sid
    if not d.exists():
        raise HTTPException(404, "session not found")
    return d


def _session_meta(d: Path) -> dict:
    import json
    mf = d / "meta.json"
    if mf.exists():
        return json.loads(mf.read_text())
    return {}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    sid = uuid.uuid4().hex[:12]
    d = STORE / sid
    d.mkdir(parents=True)
    ext = Path(file.filename or "upload.png").suffix.lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".pdf"):
        # normalize by content-type fallback
        ext = ".png" if "image" in (file.content_type or "") else ".pdf"
    orig = d / f"original{ext}"
    with orig.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    import json
    kind = "image"
    page_count = 1
    pw = ph = None
    if ext == ".pdf" and HAS_FITZ:
        doc = fitz.open(str(orig))
        page_count = len(doc)
        pw, ph = doc[0].rect.width, doc[0].rect.height
        # preview page 0 @200dpi
        pix = doc[0].get_pixmap(dpi=200)
        pix.save(str(d / "preview.png"))
        # digital vs scanned heuristic
        txt = doc[0].get_text().strip()
        kind = "pdf-digital" if len(txt) > 20 else "pdf-scanned"
        doc.close()
    else:
        # image: copy as preview
        shutil.copy(str(orig), str(d / "preview.png"))
        kind = "image"

    (d / "meta.json").write_text(json.dumps({
        "original": orig.name, "ext": ext, "kind": kind,
        "pages": page_count, "pw": pw, "ph": ph,
    }))
    return {"sessionId": sid, "kind": kind, "pages": page_count,
            "previewUrl": f"/files/{sid}/preview.png"}


@app.post("/detect-rows")
def detect_rows(req: DetectReq):
    d = _session_dir(req.sessionId)
    meta = _session_meta(d)
    ext = meta.get("ext", ".png")
    try:
        if ext == ".pdf":
            info = detect_pdf_rows(str(d / f"original{ext}"), req.page)
            rows = info["rows"]
            # For scanned PDFs, rows are in pt; also produce preview-scale rows
            # Preview is 200dpi PNG of page: scale pt->px = dpi/72
            if info["kind"] == "scanned" and (d / "preview.png").exists():
                scale = 200 / 72
                for r in rows:
                    r["px_y0"] = r["y0"] * scale
                    r["px_y1"] = r["y1"] * scale
            return {"kind": "pdf-" + info["kind"], "rows": rows,
                    "pageWidth": info["page_width"], "pageHeight": info["page_height"]}
        else:
            rows = detect_image_rows(str(d / "preview.png"))
            return {"kind": "image", "rows": rows}
    except Exception as e:
        raise HTTPException(500, f"detect failed: {e}")


@app.post("/insert-row")
def insert_row(req: InsertReq):
    d = _session_dir(req.sessionId)
    meta = _session_meta(d)
    ext = meta.get("ext", ".png")
    try:
        if ext == ".pdf":
            kind = meta.get("kind", "pdf-digital")
            if kind == "pdf-digital":
                out = d / "output.pdf"
                info = insert_pdf_digital_row(
                    str(d / f"original{ext}"), str(out), req.page,
                    req.afterIndex, req.templateIndex, req.newValues)
                # preview of new page
                if HAS_FITZ:
                    doc = fitz.open(str(out))
                    pix = doc[req.page].get_pixmap(dpi=150)
                    pix.save(str(d / "output_preview.png"))
                    doc.close()
                return {"ok": True, "previewUrl": f"/files/{req.sessionId}/output_preview.png",
                        "downloadUrl": f"/export?sessionId={req.sessionId}", **info}
            else:
                # scanned pdf: image-patch preview then rebuild pdf
                det = detect_pdf_rows(str(d / f"original{ext}"), req.page)
                rows = det["rows"]
                # render page @300dpi for quality work
                doc = fitz.open(str(d / f"original{ext}"))
                pix = doc[req.page].get_pixmap(dpi=300)
                work = d / "work.png"
                pix.save(str(work))
                doc.close()
                scale = 300 / 72
                px_rows = [{**r, "y0": r["y0"] * scale, "y1": r["y1"] * scale,
                            "x0": 0, "x1": pix.width} for r in rows]
                out_png = d / "output.png"
                info = insert_image_row(str(work), str(out_png), px_rows,
                                        req.afterIndex, req.templateIndex, req.newValues)
                # rebuild single-page pdf (MVP) preserving page size
                ndoc = fitz.open()
                pg = ndoc.new_page(width=det["page_width"], height=det["page_height"] + info["row_height"] * 72 / 300)
                pg.insert_image(pg.rect, filename=str(out_png))
                ndoc.save(str(d / "output.pdf"))
                ndoc.close()
                return {"ok": True, "previewUrl": f"/files/{req.sessionId}/output.png",
                        "downloadUrl": f"/export?sessionId={req.sessionId}", **info}
        else:
            det_rows = detect_image_rows(str(d / "preview.png"))
            out = d / "output.png"
            info = insert_image_row(str(d / "preview.png"), str(out), det_rows,
                                    req.afterIndex, req.templateIndex, req.newValues)
            return {"ok": True, "previewUrl": f"/files/{req.sessionId}/output.png",
                    "downloadUrl": f"/export?sessionId={req.sessionId}", **info}
    except Exception as e:
        raise HTTPException(500, f"insert failed: {e}")


@app.get("/export")
def export(sessionId: str):
    d = _session_dir(sessionId)
    meta = _session_meta(d)
    ext = meta.get("ext", ".png")
    if ext == ".pdf":
        for cand in ["output.pdf", f"original{ext}"]:
            p = d / cand
            if p.exists():
                return FileResponse(str(p), media_type="application/pdf", filename=f"edited{cand[cand.index('.'):]}")
    else:
        for cand in ["output.png", "preview.png", f"original{ext}"]:
            p = d / cand
            if p.exists():
                mt = "image/png" if cand.endswith(".png") else "image/jpeg"
                return FileResponse(str(p), media_type=mt, filename=cand)
    raise HTTPException(404, "nothing to export")
