"""Largest risk whose realised drawdown stays STRICTLY under the 20% gate."""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from strategies.registry import v7, v8, measure

CASES = (("V8 fund-gate top-3", v8, (0.120, 0.130, 0.140, 0.150)),
         ("V7 wide gate top-3", v7, (0.144,)))

for tag, fn, risks in CASES:
    for r in risks:
        m = measure(*fn(r))
        ok = abs(m["dd"]) < 0.200
        print(f"{tag:<20} risk {r*100:5.2f}%  CAGR {m['cagr']*100:7.1f}%  "
              f"DD {m['dd']*100:6.2f}%  {'OK ' if ok else 'over'}  PF {m['pf']:5.2f}  "
              f"N {m['n']:5d}  Shp {m['sharpe']:5.2f}  Clm {m['calmar']:5.2f}  "
              f"P>20 {m['p20']*100:3.0f}%", flush=True)
        if ok:
            print("      yearly " + "  ".join(f"{y}:{x*100:+.0f}%"
                  for y, x in m["yearly"].items()), flush=True)
print("done: gate tune")
