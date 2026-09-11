"""Produce the risk-parity knob-6 curve and render the equity chart as inline SVG."""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd, json
from research.harness import IS_START, IS_END, OOS_END
from strategies.s09_portfolio_real import sleeves, combine
from engine.data import load

sl_is = sleeves(1, IS_START, IS_END)
cols = [c for c in sl_is if not c.startswith("_")]
inv = {c: 1.0 / sl_is[c].std() for c in cols}
tot = sum(inv.values()); rp = {c: inv[c] / tot for c in cols}
print("risk-parity weights:", {c: round(v, 3) for c, v in rp.items()})
p = combine(sleeves(6, IS_START, OOS_END), rp)
print(f"RP knob6 -> CAGR {p['cagr']*100:.1f}%  DD {p['max_dd']*100:.1f}%  PF {p['pf']:.2f} "
      f"Sharpe {p['sharpe']:.2f} Calmar {p['calmar']:.2f} N {p['trades']}")
print("  yearly:", {y: round(v*100) for y, v in p["yearly"].items()})

cur = pd.read_parquet("results/curves.parquet")
cur.index = pd.to_datetime(cur.index, utc=True)
rpc = pd.Series(p["equity"], index=pd.to_datetime(p["index"], utc=True))
cur["PORT_RP6"] = rpc.reindex(cur.index).ffill()
sp = load("spot_1h"); sp = sp[(sp.dt >= cur.index[0]) & (sp.dt <= cur.index[-1])]
b = sp.set_index("dt").close.reindex(cur.index, method="ffill")
cur["BTC"] = 10_000.0 * b / b.dropna().iloc[0]
w = cur.resample("1W").last().dropna(how="all")

SERIES = [("PORT_RP6", "s1", "Portfolio · risk parity · size 6"),
          ("SMRD_r0.025", "s2", "S7 Smart-money vs retail · 2.5% risk"),
          ("AVT_r0.025", "s3", "S4 Adaptive trend · 2.5% risk"),
          ("OFS_r0.02", "s4", "S3 Order-flow swing · 2.0% risk"),
          ("BTC", "btc", "BTC spot buy & hold")]

W, H = 1040, 400
L, R, T, B = 52, 14, 16, 30
lo, hi = 9000.0, 200000.0
x = lambda i, n: L + (W - L - R) * i / (n - 1)
y = lambda v: T + (H - T - B) * (1 - (np.log(max(v, lo)) - np.log(lo)) / (np.log(hi) - np.log(lo)))

parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" '
         f'aria-label="Equity curves, log scale, 10,000 USDT start, 2020 to 2026" '
         f'style="display:block;max-width:100%;height:auto">']
for v in (10_000, 20_000, 50_000, 100_000, 200_000):
    yy = y(v)
    parts.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{W-R}" y2="{yy:.1f}" stroke="var(--hair)" stroke-width="1"/>')
    parts.append(f'<text x="{L-8}" y="{yy+3.5:.1f}" text-anchor="end" font-size="10.5" '
                 f'fill="var(--faint)">{v//1000}k</text>')
idx = w.index
years = sorted({d.year for d in idx})
for yr in years:
    pos = [i for i, d in enumerate(idx) if d.year == yr]
    if not pos: continue
    xx = x(pos[0], len(idx))
    parts.append(f'<line x1="{xx:.1f}" y1="{T}" x2="{xx:.1f}" y2="{H-B}" stroke="var(--hair)" stroke-width="1"/>')
    parts.append(f'<text x="{xx+4:.1f}" y="{H-B+15:.1f}" font-size="10.5" fill="var(--faint)">{yr}</text>')
# OOS shading
oos_i = next((i for i, d in enumerate(idx) if d >= pd.Timestamp(IS_END, tz="UTC")), None)
if oos_i:
    xs = x(oos_i, len(idx))
    parts.append(f'<rect x="{xs:.1f}" y="{T}" width="{W-R-xs:.1f}" height="{H-B-T}" '
                 f'fill="var(--ink)" opacity="0.035"/>')
    parts.append(f'<line x1="{xs:.1f}" y1="{T}" x2="{xs:.1f}" y2="{H-B}" stroke="var(--ash)" '
                 f'stroke-width="1" stroke-dasharray="3 3"/>')
    parts.append(f'<text x="{xs+6:.1f}" y="{T+13:.1f}" font-size="10.5" fill="var(--ash)" '
                 f'letter-spacing="0.08em">OUT OF SAMPLE</text>')
for col, tok, _ in SERIES:
    s = w[col]
    pts = [(x(i, len(idx)), y(v)) for i, v in enumerate(s) if np.isfinite(v)]
    if not pts: continue
    d = "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in pts)
    dash = ' stroke-dasharray="4 3"' if col == "BTC" else ""
    wdt = 2.2 if col == "PORT_RP6" else 1.5
    parts.append(f'<path d="{d}" fill="none" stroke="var(--{tok})" stroke-width="{wdt}" '
                 f'stroke-linejoin="round" stroke-linecap="round"{dash}/>')
parts.append("</svg>")
open("results/chart.svg", "w").write("\n".join(parts))
leg = "\n".join(f'<div class="lg"><span class="sw" style="background:var(--{t})"></span>{lab}</div>'
                for _, t, lab in SERIES)
open("results/legend.html", "w").write(leg)
print("chart written; final values:",
      {c: int(w[c].dropna().iloc[-1]) for c, _, _ in SERIES})
