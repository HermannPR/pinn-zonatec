"""Construye grill-me-pinn-zonatec.pdf desde el .md: Markdown -> HTML (KaTeX) -> PDF con Edge headless.

Uso:  python grill/build.py
"""
import pathlib
import re
import subprocess

import markdown

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "grill-me-pinn-zonatec.md"
HTML = HERE / "grill-me-pinn-zonatec.html"
PDF = HERE / "grill-me-pinn-zonatec.pdf"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

text = SRC.read_text(encoding="utf-8")

# proteger las fórmulas $...$ del procesador de Markdown (los _ y \ se romperían)
maths = []


def _stash(m):
    maths.append(m.group(1))
    return f"@@MATH{len(maths) - 1}@@"


text = re.sub(r"\$([^$\n]+?)\$", _stash, text)
# líneas para rellenar a mano: ____ -> raya
text = re.sub(r"_{4,}", lambda m: f'<span class="blank" style="width:{min(len(m.group(0)) * 4, 380)}px"></span>', text)

body = markdown.markdown(text, extensions=["tables", "md_in_html", "sane_lists"])

# casillas: "<li>[ ] ..." -> casilla dibujada
body = re.sub(r"<li>\s*(<p>)?\[ \]\s*", r'<li class="opt">\1<span class="box"></span>', body)
body = body.replace("☐", '<span class="box sm"></span>')
body = body.replace("<strong>REC</strong>", '<span class="tag">REC</span>')
body = body.replace("REC</li>", '<span class="tag">REC</span></li>')
body = re.sub(r"\*\*REC\*\*", '<span class="tag">REC</span>', body)
body = re.sub(r"(?<![\w>])REC(?= para| si|,| \(|</p>|</li>)", '<span class="tag">REC</span>', body)
body = body.replace("<strong>[no verificado", '<strong class="nv">[no verificado')
body = re.sub(r"<strong>\[(estimación[^<]*|orden de magnitud[^<]*|edición[^<]*|cobertura[^<]*|URL[^<]*|estación[^<]*|límite[^<]*|identificador[^<]*)\]</strong>",
              r'<strong class="nv">[\1]</strong>', body)
body = body.replace('<div class="pb"></div>', '<div class="pb"></div>')

for i, m in enumerate(maths):
    body = body.replace(f"@@MATH{i}@@", f'<span class="math">{m.replace("&", "&amp;").replace("<", "&lt;")}</span>')

CSS = r"""
@page { size: Letter; margin: 18mm 17mm 18mm 17mm; }
:root { --ink:#1b1f24; --muted:#5b6470; --accent:#0b5cad; --accent2:#e8f1fb; --warn:#9a3b00; --warnbg:#fff4e8; --line:#d7dde4; }
html { font-size: 10.2pt; }
body { font-family: "Segoe UI", "Calibri", Arial, sans-serif; color: var(--ink); line-height: 1.42; margin: 0; background: #fff; }
h1 { font-size: 26pt; line-height: 1.12; margin: 0 0 10pt; color: #0d2a4a; letter-spacing: -0.3pt; }
h2 { font-size: 16pt; color: #0d2a4a; border-bottom: 2px solid var(--accent); padding-bottom: 3pt; margin: 0 0 10pt; }
h3 { font-size: 12.2pt; color: #0d2a4a; margin: 14pt 0 5pt; }
p { margin: 4pt 0 6pt; }
code { font-family: Consolas, monospace; font-size: 9pt; background: #f1f3f6; padding: 0 3px; border-radius: 3px; }
table { border-collapse: collapse; width: 100%; font-size: 8.9pt; margin: 6pt 0 10pt; }
th, td { border: 1px solid var(--line); padding: 3.5pt 5pt; vertical-align: top; text-align: left; }
th { background: #eef2f7; }
tr { break-inside: avoid; }
.pb { break-after: page; }
.cover { height: 238mm; display: flex; flex-direction: column; break-after: page; overflow: hidden; }
.cover .kicker { text-transform: uppercase; letter-spacing: 1.6pt; font-size: 9pt; color: var(--accent); font-weight: 600; margin-top: 30mm; }
.cover h1 { font-size: 32pt; }
.cover .subtitle { font-size: 13pt; color: var(--muted); margin-bottom: 16pt; }
.cover-meta p { margin: 2pt 0; }
.cover-meta { border-left: 4px solid var(--accent); padding: 4pt 10pt; margin: 8pt 0 16pt; }
.prompt { background: #f5f7fa; border: 1px solid var(--line); border-radius: 6px; padding: 8pt 11pt; font-size: 9.6pt; font-style: normal; }
.howto { margin-top: auto; font-size: 9.3pt; color: #333; border-top: 1px solid var(--line); padding-top: 8pt; }
.trap { border-left: 4px solid var(--warn); background: var(--warnbg); padding: 5pt 10pt; margin: 0 0 8pt; break-inside: avoid; border-radius: 0 5px 5px 0; }
.trap p { margin: 2pt 0; }
.quick { font-size: 9.9pt; }
.q { break-inside: avoid; margin-bottom: 8pt; padding-top: 2pt; border-top: 1px dashed var(--line); }
.q h3 { break-after: avoid; }
.q ul { list-style: none; padding-left: 2pt; margin: 4pt 0 6pt; }
.q li.opt { margin: 2.5pt 0; padding-left: 20pt; position: relative; break-inside: avoid; }
.q li.opt p { margin: 0; }
.box { display: inline-block; width: 10pt; height: 10pt; border: 1.4px solid #2a3440; border-radius: 2px; vertical-align: -1.5pt; margin-right: 4pt; background: #fff; }
li.opt > .box, li.opt > p > .box:first-child { position: absolute; left: 2pt; top: 2pt; }
.box.sm { width: 8pt; height: 8pt; margin: 0 2pt 0 5pt; position: static !important; }
.tag { display: inline-block; background: var(--accent); color: #fff; font-size: 7.4pt; font-weight: 700; padding: 0 4pt; border-radius: 3px; letter-spacing: 0.5pt; vertical-align: 0.5pt; }
.rec { background: var(--accent2); border: 1px solid #b9d3ef; border-radius: 5px; padding: 4pt 9pt; margin: 5pt 0 6pt; break-inside: avoid; }
.rec p { margin: 2pt 0; }
.nv { color: var(--warn); font-weight: 600; font-size: 0.92em; }
.refs p { padding-left: 18pt; text-indent: -18pt; font-size: 8.9pt; margin: 0 0 4pt; word-break: break-word; }
.blank { display: inline-block; border-bottom: 1px solid #555; height: 1em; vertical-align: -2pt; margin: 0 6pt 0 2pt; }
.lines { height: 60mm; background: repeating-linear-gradient(to bottom, transparent 0, transparent 9mm, #9aa4b0 9mm, #9aa4b0 calc(9mm + 1px)); }
ol, ul { margin: 4pt 0 6pt; }
"""

page = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Grill PINN Zona Tec</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<style>{CSS}</style></head>
<body>
{body}
<script>
document.querySelectorAll('.math').forEach(function (el) {{
  try {{ katex.render(el.textContent, el, {{throwOnError: false}}); }} catch (e) {{}}
}});
</script>
</body></html>"""

HTML.write_text(page, encoding="utf-8")
subprocess.run([EDGE, "--headless", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=15000",
                f"--print-to-pdf={PDF}", HTML.as_uri()], check=True, timeout=180)
print("PDF:", PDF, PDF.stat().st_size // 1024, "KB")
