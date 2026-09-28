"""Verifica el PDF: número de páginas y renderiza páginas a PNG para revisarlas."""
import pathlib
import sys

import pymupdf

HERE = pathlib.Path(__file__).resolve().parent
doc = pymupdf.open(HERE / "grill-me-pinn-zonatec.pdf")
print("paginas:", doc.page_count)
out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
for i in [int(a) for a in sys.argv[2:]] or [0]:
    doc[i].get_pixmap(dpi=80).save(out / f"page{i + 1}.png")
