import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
df = pd.read_parquet("results/curves2.parquet")
df.index = pd.to_datetime(df.index, utc=True)
w = df.resample("1W").last().ffill().dropna(how="all")
b = w["PERP"]
peak = np.maximum.accumulate(b.values); dd = b.values/peak - 1
yrs = (w.index[-1]-w.index[0]).days/365.25
print(f"PERP benchmark: total {b.iloc[-1]/100:.0f}%  CAGR {((b.iloc[-1]/10000)**(1/yrs)-1)*100:.1f}%  MaxDD {dd.min()*100:.1f}%")
d = pd.Series(b.values, index=w.index).pct_change().fillna(0)
print(f"  Sharpe {d.mean()/d.std()*np.sqrt(52):.2f}")

SER = [("CONVEX","s1","S15 Convex trend · 2% risk · pyramid 3"),
       ("CONT","s2","S20 Continuous vol-targeted"),
       ("SMRD","s3","S7 Smart-money vs retail · 2.5% risk"),
       ("PORT","s4","S19 Futures-only portfolio · size 2"),
       ("PERP","btc","BTCUSDT perpetual, buy & hold")]
W,H,L,R,T,B = 1040,380,52,14,16,30
lo,hi = 8000.0, 80000.0
x = lambda i,n: L+(W-L-R)*i/(n-1)
y = lambda v: T+(H-T-B)*(1-(np.log(max(v,lo))-np.log(lo))/(np.log(hi)-np.log(lo)))
p=[f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Equity curves, log scale, '
   f'10,000 USDT start, 2021 to 2026" style="display:block;max-width:100%;height:auto">']
for v in (10_000,20_000,40_000,80_000):
    yy=y(v); p.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{W-R}" y2="{yy:.1f}" stroke="var(--hair)" stroke-width="1"/>')
    p.append(f'<text x="{L-8}" y="{yy+3.5:.1f}" text-anchor="end" font-size="10.5" fill="var(--faint)">{v//1000}k</text>')
idx=w.index
for yr in sorted({d.year for d in idx}):
    pos=[i for i,d in enumerate(idx) if d.year==yr]
    if not pos: continue
    xx=x(pos[0],len(idx))
    p.append(f'<line x1="{xx:.1f}" y1="{T}" x2="{xx:.1f}" y2="{H-B}" stroke="var(--hair)" stroke-width="1"/>')
    p.append(f'<text x="{xx+4:.1f}" y="{H-B+15:.1f}" font-size="10.5" fill="var(--faint)">{yr}</text>')
oi=next((i for i,d in enumerate(idx) if d>=pd.Timestamp("2024-07-01",tz="UTC")),None)
if oi:
    xs=x(oi,len(idx))
    p.append(f'<rect x="{xs:.1f}" y="{T}" width="{W-R-xs:.1f}" height="{H-B-T}" fill="var(--ink)" opacity="0.035"/>')
    p.append(f'<line x1="{xs:.1f}" y1="{T}" x2="{xs:.1f}" y2="{H-B}" stroke="var(--ash)" stroke-width="1" stroke-dasharray="3 3"/>')
    p.append(f'<text x="{xs+6:.1f}" y="{T+13:.1f}" font-size="10.5" fill="var(--ash)" letter-spacing="0.08em">OUT OF SAMPLE</text>')
for col,tok,_ in SER:
    s=w[col]; pts=[(x(i,len(idx)),y(v)) for i,v in enumerate(s) if np.isfinite(v)]
    if not pts: continue
    d_="M"+" L".join(f"{a:.1f} {b_:.1f}" for a,b_ in pts)
    dash=' stroke-dasharray="4 3"' if col=="PERP" else ""
    p.append(f'<path d="{d_}" fill="none" stroke="var(--{tok})" stroke-width="{2.2 if col=="CONVEX" else 1.5}" '
             f'stroke-linejoin="round" stroke-linecap="round"{dash}/>')
p.append("</svg>")
open("results/chart2.svg","w").write("\n".join(p))
open("results/legend2.html","w").write("\n".join(
    f'<div class="lg"><span class="sw" style="background:var(--{t})"></span>{lab}</div>' for _,t,lab in SER))
print("chart2 written; finals:", {c:int(w[c].dropna().iloc[-1]) for c,_,_ in SER})
