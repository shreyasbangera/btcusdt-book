"""
S83c - Is the top-up buying drawdown cheaply, or just buying it?

Every top-up variant raises return AND drawdown.  That is not interesting on its
own: the risk dial does the same thing for free.  The only question that decides
the mechanism is whether, at MATCHED DRAWDOWN, the top-up beats simply turning
the risk up.  Run the plain control across a risk ladder and read off what it
returns at each top-up variant's drawdown.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.planscache import cached_plan
from strategies.s83b_topup import replay
from strategies.s77_lookback import stats

if __name__ == "__main__":
    P12 = cached_plan(12)
    print("plain control across the risk dial\n")
    for risk in (0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20):
        r, pl = replay(P12, risk)
        stats(r, pl, "control", risk)
    print("\nbest top-up variants, for comparison\n")
    for tag, risk, kw in (("m1 2x max1", 0.08, dict(mult=2.0, mx=1, mode=1)),
                          ("m2 2x max1", 0.08, dict(mult=2.0, mx=1, mode=2))):
        r, pl = replay(P12, risk, **kw)
        stats(r, pl, tag, risk)
    print("\ndone: matched-risk comparison")
