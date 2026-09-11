import paths as _P
"""Render the growth-optimal leverage curve as inline SVG for the report."""
import re, numpy as np

txt = open(str(_P.RESULTS / "s18.txt")).read()
books, cur = {}, None
for ln in txt.splitlines():
    m = re.match(r"=== (.+?) — full period ===", ln)
    if m:
        cur = m.group(1); books[cur] = []
        continue
    m = re.match(r"\s+([\d.]+)%\s+(-?[\d.]+)%\s+(-?[\d.]+)%", ln)
    if m and cur:
        books[cur].append((float(m.group(1)), float(m.group(2)), float(m.group(3))))

W, H, L, R, T, B = 1040, 380, 58, 16, 18, 34
xs_all = [r[0] for b in books.values() for r in b]
xmax = max(xs_all)
ymin, ymax = -80.0, 70.0
x = lambda v: L + (W-L-R) * (np.log(v) - np.log(0.5)) / (np.log(xmax) - np.log(0.5))
y = lambda v: T + (H-T-B) * (1 - (v - ymin) / (ymax - ymin))
TOK = ["s1", "s2", "s3"]
p = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Compound annual '
     f'return versus risk per trade, showing a peak near 5 to 12 percent risk" '
     f'style="display:block;max-width:100%;height:auto">']
for v in (-80, -60, -40, -20, 0, 20, 40, 60):
    yy = y(v)
    col = "var(--ash)" if v == 0 else "var(--hair)"
    p.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{W-R}" y2="{yy:.1f}" stroke="{col}" stroke-width="1"/>')
    p.append(f'<text x="{L-8}" y="{yy+3.5:.1f}" text-anchor="end" font-size="10.5" '
             f'fill="var(--faint)">{v:+d}%</text>')
for v in (0.5, 1, 2, 5, 10, 20, 30):
    xx = x(v)
    p.append(f'<line x1="{xx:.1f}" y1="{T}" x2="{xx:.1f}" y2="{H-B}" stroke="var(--hair)" stroke-width="1"/>')
    p.append(f'<text x="{xx:.1f}" y="{H-B+15:.1f}" text-anchor="middle" font-size="10.5" '
             f'fill="var(--faint)">{v:g}%</text>')
p.append(f'<text x="{(L+W-R)/2:.0f}" y="{H-4}" text-anchor="middle" font-size="10.5" '
         f'fill="var(--faint)" letter-spacing="0.08em">RISK PER TRADE</text>')
legend = []
for i, (name, rows) in enumerate(books.items()):
    tok = TOK[i % 3]
    pts = [(x(r[0]), y(r[1])) for r in rows]
    d = "M" + " L".join(f"{a:.1f} {b:.1f}" for a, b in pts)
    p.append(f'<path d="{d}" fill="none" stroke="var(--{tok})" stroke-width="2" '
             f'stroke-linejoin="round" stroke-linecap="round"/>')
    pk = max(rows, key=lambda r: r[1])
    px_, py_ = x(pk[0]), y(pk[1])
    p.append(f'<circle cx="{px_:.1f}" cy="{py_:.1f}" r="4" fill="var(--{tok})"/>')
    p.append(f'<text x="{px_+8:.1f}" y="{py_-7:.1f}" font-size="11" font-weight="600" '
             f'fill="var(--{tok})">{pk[1]:.0f}% peak</text>')
    legend.append(f'<div class="lg"><span class="sw" style="background:var(--{tok})"></span>'
                  f'{name} · peak {pk[1]:.1f}% at {pk[0]:g}% risk · DD {pk[2]:.0f}%</div>')
p.append("</svg>")
open(str(_P.RESULTS / "kelly.svg"), "w").write("\n".join(p))
open(str(_P.RESULTS / "kelly_legend.html"), "w").write("\n".join(legend))
print("kelly chart written")
for n, rows in books.items():
    pk = max(rows, key=lambda r: r[1])
    print(f"  {n:<34} peak {pk[1]:6.1f}% at risk {pk[0]:>5}%  DD {pk[2]:6.1f}%  "
          f"| worst {min(r[1] for r in rows):7.1f}%")
