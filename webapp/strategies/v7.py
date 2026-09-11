"""V7 — the gated top-3 blend, wired into the web app.

Reads the three configurations chosen by the last quarterly selection
(`v7_plan.json`, written by live/v7_select.py) and returns them as three
sleeves at a third of the risk budget each.

All three sleeves read the same composite and differ only in exponent, stop,
target, holding cap and gate, and the exponent never changes a sign — so the
sleeves are always on the same side or flat, and each sleeve's stop can be a
separate reduce-only order against one netted position.
"""
import os, sys, json
import webapp  # noqa: F401  - puts the project root on sys.path
import numpy as np, pandas as pd

from webapp.strategies.base import Strategy, Sleeve, Decision
from webapp.config import STORE
from live.runner import build_signals, unit, THR


class V7(Strategy):
    name = "v7"
    description = ("Five signals netted to one position every 12h; the best three "
                   "configurations by trailing Calmar held together; short entries "
                   "blocked above a long moving average.")
    decision_tf = "12h"
    warmup_bars = 520
    params = {"plan": str(STORE / "v7_plan.json"), "cap": 3.0, "max_leverage": 10.0}

    def needs(self):
        return ["panel_12h", "panel_4h"]

    # -- the composite, identical to the backtest ---------------------------
    @staticmethod
    def _composite(s):
        return np.nanmean(np.vstack([unit(s[k], THR[k]) for k in s]), axis=0)

    @staticmethod
    def _shaped(v, p, cap):
        nz = np.abs(v) > 0
        if not nz.any():
            return v
        u = np.sign(v) * np.abs(v) ** p
        u = u * (float(np.abs(v[nz]).mean()) / max(float(np.abs(u[nz]).mean()), 1e-12))
        return np.sign(u) * np.minimum(np.abs(u), cap)

    @staticmethod
    def _above_ema(close, span):
        px = pd.Series(close)
        return bool((px > px.ewm(span=span, adjust=False).mean()).iloc[-1])

    def decide(self, panels, equity, risk):
        plan_path = self.params["plan"]
        if not os.path.exists(plan_path):
            return Decision([], note=f"no plan at {plan_path} — run live/v7_select.py")
        plan = json.load(open(plan_path))
        cfgs = plan["configs"]

        df, df4 = panels["panel_12h"], panels["panel_4h"]
        if len(df) < self.warmup_bars:
            return Decision([], note=f"only {len(df)} bars, need {self.warmup_bars}")

        s, atr = build_signals(df, df4)
        base = self._composite(s)
        i = len(df) - 1
        px = float(df.close.iloc[i]); a = float(atr[i])
        close = df.close.to_numpy(float)
        per = risk / len(cfgs)

        sleeves = []
        for n, (p, stp, rr, hold, gk, gn) in enumerate(cfgs, 1):
            u = float(self._shaped(base, p, self.params["cap"])[i])
            if gk and u < 0 and self._above_ema(close, gn):
                u = 0.0                                    # gate blocks SHORTS only
            if u == 0.0:
                sleeves.append(Sleeve(f"#{n} exp {p} · {stp}ATR ×{rr}R · {hold}d", 0.0,
                                      meta=dict(conviction=0.0, gated=bool(gk))))
                continue
            side = 1 if u > 0 else -1
            sd = stp * a
            q = self.size_for(equity, per, u, sd, px, self.params["max_leverage"])
            sleeves.append(Sleeve(
                label=f"#{n} exp {p} · {stp}ATR ×{rr}R · {hold}d"
                      + (f" · gate ema{gn}" if gk else ""),
                qty=side * q,
                stop=px - side * sd,
                take_profit=px + side * rr * sd,
                hold_bars=int(hold * 2),                   # days -> 12h bars
                meta=dict(conviction=round(u, 4), exponent=p, stop_atr=stp, rr=rr)))

        diag = {k: round(float(s[k][i]), 3) for k in s}
        diag |= {"composite": round(float(base[i]), 4), "atr14": round(a, 1),
                 "close": round(px, 1), "plan_asof": plan.get("asof", "?")}
        return Decision(sleeves, diagnostics=diag,
                        note=f"bar {pd.to_datetime(df.dt.iloc[i])}")


class BuyAndHold(Strategy):
    """A deliberately trivial second strategy, so the plug-in interface has a
    worked example that is not V7.  One sleeve, always long, no stop."""
    name = "buyhold"
    description = "Always long, unlevered. A benchmark, not a strategy."
    decision_tf = "12h"
    warmup_bars = 2

    def decide(self, panels, equity, risk):
        df = panels["panel_12h"]
        px = float(df.close.iloc[-1])
        return Decision([Sleeve("long 1x", equity / px)],
                        diagnostics={"close": round(px, 1)})
