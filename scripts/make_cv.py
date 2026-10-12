"""Render data/cv/sample_cv.md to data/cv/sample_cv.pdf so the pipeline's PDF path is exercised.

Usage: uv run python scripts/make_cv.py
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

NX = dict(new_x=XPos.LMARGIN, new_y=YPos.NEXT)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "cv" / "sample_cv.md"
OUT = ROOT / "data" / "cv" / "sample_cv.pdf"


def main() -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(18, 15, 18)
    for line in SRC.read_text().splitlines():
        if line.startswith("# "):
            pdf.set_font("Helvetica", "B", 18)
            pdf.multi_cell(0, 9, line[2:], **NX)
        elif line.startswith("## "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 13)
            pdf.multi_cell(0, 7, line[3:], **NX)
        elif line.startswith("### "):
            pdf.ln(1)
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(0, 6, line[4:], **NX)
        elif line.startswith("- "):
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, "    - " + line[2:], **NX)
        elif line.strip():
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, line, **NX)
        else:
            pdf.ln(2)
    pdf.output(str(OUT))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
