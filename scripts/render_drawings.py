"""Render docs/structure_drawings.pdf to PNGs (one per page) for the restoration planner.

Run:  .venv/Scripts/python scripts/render_drawings.py
"""
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from common import PROCESSED, ROOT  # noqa: E402

out = PROCESSED / "drawings"
out.mkdir(exist_ok=True)
doc = pymupdf.open(ROOT / "docs" / "structure_drawings.pdf")
for i, page in enumerate(doc, start=1):
    page.get_pixmap(dpi=110).save(out / f"page{i}.png")
print("rendered", len(doc), "pages to", out)
