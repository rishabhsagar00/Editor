"use client";

import { useState } from "react";

type Row = {
  index: number;
  x0: number; x1: number; y0: number; y1: number;
  height: number;
  text?: string;
  cells?: string[];
  px_y0?: number; px_y1?: number;
};

const DEFAULT_API = "http://localhost:8000";

export default function Home() {
  const [api, setApi] = useState(DEFAULT_API);
  const [file, setFile] = useState<File | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [kind, setKind] = useState("");
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState(0);
  const [previewUrl, setPreviewUrl] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [afterIndex, setAfterIndex] = useState(0);
  const [templateIndex, setTemplateIndex] = useState(0);
  const [newValues, setNewValues] = useState("04-09-2026, New entry, 500.00, -, 40,800.00");
  const [outPreview, setOutPreview] = useState("");
  const [downloadUrl, setDownloadUrl] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const abs = (u: string) => (u.startsWith("http") ? u : `${api}${u}`);

  async function doUpload() {
    setError(""); setInfo("");
    if (!file) { setError("Choose a PNG/JPG/PDF file first."); return; }
    setBusy("upload");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch(`${api}/upload`, { method: "POST", body: fd });
      if (!r.ok) throw new Error(await r.text());
      const j = await r.json();
      setSessionId(j.sessionId);
      setKind(j.kind);
      setPages(j.pages ?? 1);
      setPage(0);
      setPreviewUrl(abs(j.previewUrl));
      setRows([]);
      setOutPreview("");
      setDownloadUrl("");
      // sensible defaults: insert after first data row, clone it
      setAfterIndex(0);
      setTemplateIndex(0);
      setInfo(`Uploaded (${j.kind}, ${j.pages} page(s)). Now click Detect rows.`);
      // auto-detect
      await doDetect(j.sessionId, 0, api);
    } catch (e: any) {
      setError(`Upload failed: ${e.message}`);
    } finally {
      setBusy("");
    }
  }

  async function doDetect(sid = sessionId, pg = page, base = api) {
    setError(""); setInfo("");
    if (!sid) { setError("No session — upload first."); return; }
    setBusy("detect");
    try {
      const r = await fetch(`${base}/detect-rows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId: sid, page: pg }),
      });
      if (!r.ok) throw new Error(await r.text());
      const j = await r.json();
      setKind(j.kind);
      setRows(j.rows ?? []);
      if ((j.rows ?? []).length > 1) {
        // default to cloning the first data-looking row
        setAfterIndex(1);
        setTemplateIndex(1);
      }
      // prefill newValues with right column count
      const first = (j.rows ?? [])[0] as Row | undefined;
      const ncols = first?.cells?.length || 5;
      const cur = newValues.split(",").map((s) => s.trim());
      if (cur.length !== ncols) {
        setNewValues(Array(ncols).fill("").map((_, i) => cur[i] ?? `val${i + 1}`).join(", "));
      }
      setInfo(`Detected ${(j.rows ?? []).length} rows (${j.kind}).`);
    } catch (e: any) {
      setError(`Detect failed: ${e.message}`);
    } finally {
      setBusy("");
    }
  }

  async function doInsert() {
    setError(""); setInfo("");
    if (!sessionId) { setError("No session — upload first."); return; }
    setBusy("insert");
    try {
      const vals = newValues.split(",").map((s) => s.trim());
      const r = await fetch(`${api}/insert-row`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId, page,
          afterIndex: Number(afterIndex),
          templateIndex: Number(templateIndex),
          newValues: vals,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      const j = await r.json();
      setOutPreview(abs(j.previewUrl));
      setDownloadUrl(abs(j.downloadUrl));
      setInfo(`Inserted row after #${afterIndex} (height ${j.row_height ?? j.row_height}).`);
    } catch (e: any) {
      setError(`Insert failed: ${e.message}`);
    } finally {
      setBusy("");
    }
  }

  return (
    <main>
      <h1>RowInsert — statement row editor</h1>
      <p className="muted">
        Upload a statement PNG/JPG/PDF → detect table rows → insert a new row after any
        row → preview &amp; download. Backend: FastAPI (<code>/upload</code>,{" "}
        <code>/detect-rows</code>, <code>/insert-row</code>, <code>/export</code>).
      </p>

      <div className="card">
        <div className="row">
          <label className="muted">API
            <input type="text" value={api} onChange={(e) => setApi(e.target.value)} style={{ marginLeft: 8, width: 240 }} />
          </label>
          <input
            type="file"
            accept=".png,.jpg,.jpeg,.pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <button onClick={doUpload} disabled={busy === "upload"}>
            {busy === "upload" ? "Uploading…" : "1 · Upload"}
          </button>
          <button className="secondary" onClick={() => doDetect()} disabled={!sessionId || busy === "detect"}>
            {busy === "detect" ? "Detecting…" : "2 · Detect rows"}
          </button>
        </div>
        {sessionId && (
          <p className="muted">
            session <code>{sessionId}</code> · kind <code>{kind}</code> · {pages} page(s)
            {pages > 1 && (
              <> · page <input type="number" min={0} max={pages - 1} value={page}
                onChange={(e) => setPage(Number(e.target.value))} style={{ width: 64 }} />
                <button className="secondary" onClick={() => doDetect()}>reload page</button>
              </>
            )}
          </p>
        )}
      </div>

      {error && <div className="card"><div className="error">{error}</div></div>}
      {info && <div className="card"><div className="success">{info}</div></div>}

      <div className="grid2">
        <div className="card">
          <h3>Original preview</h3>
          {previewUrl ? <img className="preview" src={previewUrl} alt="original preview" /> : <p className="muted">No file yet.</p>}
        </div>
        <div className="card">
          <h3>Output preview</h3>
          {outPreview ? (
            <>
              <img className="preview" src={outPreview} alt="output preview" />
              <p><a href={downloadUrl} target="_blank" rel="noreferrer">Download edited file</a></p>
            </>
          ) : <p className="muted">Insert a row to see the result here.</p>}
        </div>
      </div>

      <div className="card">
        <h3>Detected rows ({rows.length})</h3>
        {rows.length === 0 ? <p className="muted">No rows yet — upload a file.</p> : (
          <table>
            <thead>
              <tr><th>#</th><th>text / cells</th><th>y0–y1 (h)</th><th>after?</th><th>template?</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.index} className={r.index === afterIndex ? "selected" : ""}>
                  <td>{r.index}</td>
                  <td>{r.text || (r.cells ?? []).join(" | ") || <span className="muted">(image row)</span>}</td>
                  <td>{r.y0.toFixed(1)}–{r.y1.toFixed(1)} ({r.height.toFixed(1)})</td>
                  <td><input type="radio" name="after" checked={afterIndex === r.index} onChange={() => setAfterIndex(r.index)} /></td>
                  <td><input type="radio" name="tpl" checked={templateIndex === r.index} onChange={() => setTemplateIndex(r.index)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h3>3 · Insert new row</h3>
        <div className="row">
          <label>After row <input type="number" value={afterIndex} min={-1} max={Math.max(0, rows.length - 1)} onChange={(e) => setAfterIndex(Number(e.target.value))} style={{ width: 70 }} /></label>
          <label>Template row <input type="number" value={templateIndex} min={0} max={Math.max(0, rows.length - 1)} onChange={(e) => setTemplateIndex(Number(e.target.value))} style={{ width: 70 }} /></label>
        </div>
        <p className="muted">New values — comma-separated, one per column (uses template row&apos;s columns):</p>
        <input type="text" value={newValues} onChange={(e) => setNewValues(e.target.value)} style={{ width: "100%" }} />
        <div className="row" style={{ marginTop: 12 }}>
          <button onClick={doInsert} disabled={!sessionId || busy === "insert"}>
            {busy === "insert" ? "Inserting…" : "Insert row"}
          </button>
          {downloadUrl && <a href={downloadUrl} target="_blank" rel="noreferrer">Download</a>}
        </div>
      </div>
    </main>
  );
}
