import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from engine.data import load
import strategies.s07_smart as s07
import strategies.s31_ofi6 as s31
import strategies.s32_pair as s32

START = "2021-01-03"
cur = {}
f12 = s32.P("12h")
m = backtest(f12, s31.arrays(f12, s31.signal(f12), thr=1.0, atr_stop=3.0, rr=2.0), "12h",
             start=START, end=OOS_END, risk=0.035, max_lev=10.0, max_bars_h=7*24)
cur["FLOW"] = pd.Series(m["equity"], index=pd.to_datetime(m["dt"]))
print(f"FLOW   CAGR {m['cagr']*100:5.1f}%  DD {m['max_dd']*100:6.1f}%  PF {m['profit_factor']:.2f}")

f4 = s32.P("4h"); comp = s07.composite(f4)
m = backtest(f4, s07.arrays(f4, comp, thr=0.7, atr_stop=3.5, rr=2.5), "4h",
             start=START, end=OOS_END, risk=0.025, max_lev=10.0, max_bars_h=10*24)
cur["POSN"] = pd.Series(m["equity"], index=pd.to_datetime(m["dt"]))
print(f"POSN   CAGR {m['cagr']*100:5.1f}%  DD {m['max_dd']*100:6.1f}%  PF {m['profit_factor']:.2f}")

s1 = s32.sleeves(1, START, IS_END, with_convex=True)
cc = [c for c in s1 if not c.startswith("_")]
inv = {c: 1.0/max(s1[c].std(), 1e-9) for c in cc}; tot = sum(inv.values())
rp = {c: inv[c]/tot for c in cc}
p = s32.combine(s32.sleeves(1.5, START, OOS_END, with_convex=True), rp)
cur["PORT3"] = pd.Series(p["equity"], index=pd.to_datetime(p["index"]))
print(f"PORT3  CAGR {p['cagr']*100:5.1f}%  DD {p['max_dd']*100:6.1f}%  PF {p['pf']:.2f}  Shp {p['sharpe']:.2f}")

perp = load("fut_1h"); perp = perp[(perp.dt >= START) & (perp.dt < OOS_END)]
b = perp.set_index("dt").close
cur["PERP"] = 10_000.0 * b / b.iloc[0]
w = pd.DataFrame(cur).resample("1W").last().ffill().dropna(how="all")

SER = [("PORT3","s1","S32 Flow + positioning portfolio · size 1.5"),
       ("FLOW","s2","S31 Short-window orthogonal flow · 3.5% risk"),
       ("POSN","s3","S7 Smart-money vs retail · 2.5% risk"),
       ("PERP","btc","BTCUSDT perpetual, buy & hold")]
W,H,L,R,T,B = 1040,380,52,14,16,30
lo,hi = 8000.0, 90000.0
x = lambda i,n: L+(W-L-R)*i/(n-1)
y = lambda v: T+(H-T-B)*(1-(np.log(max(v,lo))-np.log(lo))/(np.log(hi)-np.log(lo)))
p_=[f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Equity curves, log scale, '
    f'10,000 USDT start, 2021 to 2026" style="display:block;max-width:100%;height:auto">']
for v in (10_000,20_000,40_000,80_000):
    yy=y(v); p_.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{W-R}" y2="{yy:.1f}" stroke="var(--hair)" stroke-width="1"/>')
    p_.append(f'<text x="{L-8}" y="{yy+3.5:.1f}" text-anchor="end" font-size="10.5" fill="var(--faint)">{v//1000}k</text>')
idx=w.index
for yr in sorted({d.year for d in idx}):
    pos=[i for i,d in enumerate(idx) if d.year==yr]
    if not pos: continue
    xx=x(pos[0],len(idx))
    p_.append(f'<line x1="{xx:.1f}" y1="{T}" x2="{xx:.1f}" y2="{H-B}" stroke="var(--hair)" stroke-width="1"/>')
    p_.append(f'<text x="{xx+4:.1f}" y="{H-B+15:.1f}" font-size="10.5" fill="var(--faint)">{yr}</text>')
oi=next((i for i,d in enumerate(idx) if d>=pd.Timestamp(IS_END,tz="UTC")),None)
if oi:
    xs=x(oi,len(idx))
    p_.append(f'<rect x="{xs:.1f}" y="{T}" width="{W-R-xs:.1f}" height="{H-B-T}" fill="var(--ink)" opacity="0.035"/>')
    p_.append(f'<line x1="{xs:.1f}" y1="{T}" x2="{xs:.1f}" y2="{H-B}" stroke="var(--ash)" stroke-width="1" stroke-dasharray="3 3"/>')
    p_.append(f'<text x="{xs+6:.1f}" y="{T+13:.1f}" font-size="10.5" fill="var(--ash)" letter-spacing="0.08em">OUT OF SAMPLE</text>')
for col,tok,_ in SER:
    s_=w[col]; pts=[(x(i,len(idx)),y(v)) for i,v in enumerate(s_) if np.isfinite(v)]
    if not pts: continue
    d_="M"+" L".join(f"{a:.1f} {b_:.1f}" for a,b_ in pts)
    dash=' stroke-dasharray="4 3"' if col=="PERP" else ""
    p_.append(f'<path d="{d_}" fill="none" stroke="var(--{tok})" stroke-width="{2.2 if col=="PORT3" else 1.5}" '
              f'stroke-linejoin="round" stroke-linecap="round"{dash}/>')
p_.append("</svg>")
open("results/chart3.svg","w").write("\n".join(p_))
open("results/legend3.html","w").write("\n".join(
    (f'<div class="lg bench"><span class="sw" style="background:var(--{t})"></span>{lab}</div>'
     if c=="PERP" else f'<div class="lg"><span class="sw" style="background:var(--{t})"></span>{lab}</div>')
    for c,t,lab in SER))
print("finals:", {c:int(w[c].dropna().iloc[-1]) for c,_,_ in SER})
