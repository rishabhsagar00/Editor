"""Generate a statement-style sample PDF + PNG for testing (own-product layout)."""
import fitz
from pathlib import Path

OUT = Path(__file__).parent / "storage" / "_samples"
OUT.mkdir(parents=True, exist_ok=True)

headers = ["Date", "Description", "Debit", "Credit", "Balance"]
data = [
    ["01-09-2026", "Opening Balance", "-", "-", "12,500.00"],
    ["03-09-2026", "UPI Payment - Store", "1,200.00", "-", "11,300.00"],
    ["05-09-2026", "Salary Credit", "-", "45,000.00", "56,300.00"],
    ["07-09-2026", "Rent Transfer", "15,000.00", "-", "41,300.00"],
    ["09-09-2026", "Grocery Purchase", "2,350.00", "-", "38,950.00"],
]

doc = fitz.open()
page = doc.new_page(width=595, height=842)
y = 80
page.insert_text((72, 50), "My Product - Account Statement", fontsize=16)
page.insert_text((72, 66), "Sep 2026 (Sample - own product)", fontsize=9)

x_cols = [72, 150, 330, 400, 470]
col_w = [78, 180, 70, 70, 65]
row_h = 26

def draw_row(yy, vals, bold=False, fill=None):
    if fill:
        page.draw_rect(fitz.Rect(72, yy, 523, yy + row_h), color=None, fill=fill, width=0)
    page.draw_rect(fitz.Rect(72, yy, 523, yy + row_h), color=(0, 0, 0), width=0.5)
    for xc, ww, v in zip(x_cols, col_w, vals):
        page.insert_text((xc + 4, yy + 17), v, fontsize=9, fontname="helv")

draw_row(y, headers, fill=(0.9, 0.9, 0.9)); y += row_h
for i, r in enumerate(data):
    draw_row(y, r, fill=(0.96, 0.96, 0.96) if i % 2 else None); y += row_h

pdf_path = OUT / "sample_statement.pdf"
doc.save(str(pdf_path))
doc.close()
print("wrote", pdf_path)

# PNG version @200dpi
d = fitz.open(str(pdf_path))
pix = d[0].get_pixmap(dpi=200)
png_path = OUT / "sample_statement.png"
pix.save(str(png_path))
print("wrote", png_path)
