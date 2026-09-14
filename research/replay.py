"""Replay the deployed code over history, so a change can be checked against the
backtest before it is trusted.

This is not a reimplementation.  It imports webapp.engine and
webapp.strategies.v7 and calls plan_orders() and execute() once per 12h bar,
exactly as deploy/run.ps1 does.  Only two things are substituted: load_panels(),
which is data plumbing, and the venue - a broker implementing
webapp/broker/base.py that fills from historical bars and fires resting
reduce-only orders against 15m highs and lows.

    python research/replay.py 0.08

TIMING.  panel_12h.dt is the bar's OPEN, so the bar stamped T is only complete at
T+12h.  A decision made on bar i therefore acts at the open of bar i+1 - the same
lag the backtest uses, and what the laptop does at 00:05 and 12:05 UTC.  Getting
this wrong reads eleven hours into the future and roughly quadruples the result.

MODES.  `trades` runs the code as it is.  `targets` neuters the trade book, which
makes v7.decide() size fresh from the current conviction every bar with both
levels re-derived from the current close - the behaviour that shipped.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("BOOK_STORE", "/tmp/replaystore")
os.environ.setdefault("BOT_MODE", "paper")

import numpy as np, pandas as pd
from webapp.broker.base import Position
from webapp import engine as wengine, tradebook
from webapp.strategies.v7 import V7
from engine.core import funding_array
from research.harness import exec_grid, slice_period
from strategies.s87_combined import rankings
from strategies.s77_lookback import stats

FEE, SLIP = 5e-4, 3e-4                       # per side, as the backtest
STORE = os.environ["BOOK_STORE"]
PLAN = os.path.join(STORE, "v7_plan.json")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P12 = pd.read_parquet(os.path.join(ROOT, "data/live/panel_12h.parquet"))
P4 = pd.read_parquet(os.path.join(ROOT, "data/live/panel_4h.parquet"))


class Replay:
    """A venue the real engine can talk to."""
    mode = "test"

    def __init__(self, eq0):
        self.cash = eq0; self.qty = 0.0; self.entry = 0.0
        self.orders = []; self.px = 0.0; self.fillpx = 0.0
        self.pnl = []; self.sent = 0; self.stopped = 0; self.tp = 0

    def equity(self):
        return self.cash + (self.qty * (self.px - self.entry) if self.qty else 0.0)

    def position(self):
        return Position(self.qty, self.entry, self.equity())

    def price(self):
        return self.px

    def market(self, side, qty, note=""):
        self._fill(qty if side == "BUY" else -qty, self.fillpx)
        self.sent += 1
        return dict(ok=True)

    def cancel_all(self):
        self.orders = []
        return dict(ok=True)

    def place_stop(self, side, qty, stop, kind):
        self.orders.append((side, float(qty), float(stop), kind))
        return dict(ok=True)

    def _fill(self, dq, px):
        if dq == 0.0:
            return
        f = px * (1.0 + (1.0 if dq > 0 else -1.0) * SLIP)
        self.cash -= FEE * abs(dq) * f
        if self.qty == 0.0 or (self.qty > 0) == (dq > 0):
            self.entry = ((self.entry * abs(self.qty) + f * abs(dq))
                          / (abs(self.qty) + abs(dq)))
            self.qty += dq
            return
        c = min(abs(dq), abs(self.qty)); s = 1.0 if self.qty > 0 else -1.0
        p = s * (f - self.entry) * c
        self.cash += p; self.pnl.append(p); self.qty += dq
        if abs(self.qty) < 1e-12:
            self.qty = 0.0; self.entry = 0.0
        elif (self.qty > 0) != (s > 0):
            self.entry = f

    def touch(self, hi, lo):
        """Stops before targets, so a bar spanning both is scored against us."""
        if not self.qty or not self.orders:
            return
        keep = []
        for o in sorted(self.orders, key=lambda x: x[3] != "STOP_MARKET"):
            side, q, lvl, kind = o
            if not self.qty:
                keep.append(o); continue
            stop = kind == "STOP_MARKET"
            hit = ((lo <= lvl) if stop else (hi >= lvl)) if side == "SELL" \
                  else ((hi >= lvl) if stop else (lo <= lvl))
            if hit:
                self._fill(-np.sign(self.qty) * min(q, abs(self.qty)), lvl)
                self.stopped += stop; self.tp += (not stop)
            else:
                keep.append(o)
        self.orders = keep


def run(R, risk, mode="trades", eq0=10_000.0):
    real = tradebook.reconcile
    if mode == "targets":
        tradebook.reconcile = lambda book, px, flat: {}
    os.makedirs(STORE, exist_ok=True)
    for f in os.listdir(STORE):
        os.remove(os.path.join(STORE, f))

    ex, _ = slice_period(exec_grid(), R[0][0], R[-1][1])
    eo, eh, el, ec = (ex.open.to_numpy(float), ex.high.to_numpy(float),
                      ex.low.to_numpy(float), ex.close.to_numpy(float))
    fund = funding_array(ex)
    ens = pd.DatetimeIndex(ex.dt).asi8
    d12 = pd.DatetimeIndex(P12.dt).asi8

    strat = V7(); strat.params = dict(strat.params); strat.params["plan"] = PLAN
    b = Replay(eq0)
    eqc = np.full(len(ex), np.nan)
    last = -1

    for s0, e0, cfgs in R:
        json.dump({"asof": s0,
                   "configs": [list(c[:4]) + (["ema", c[4]] if c[4] else [None, 0])
                               for c in cfgs[:3]]}, open(PLAN, "w"))
        lo_i = int(np.searchsorted(d12, pd.Timestamp(s0, tz="UTC").value, "left"))
        hi_i = int(np.searchsorted(d12, pd.Timestamp(e0, tz="UTC").value, "left"))
        for i in range(lo_i, hi_i):
            if i + 1 >= len(d12):
                continue
            j = int(np.searchsorted(ens, d12[i + 1], "left"))   # open of bar i+1
            if j >= len(ex) or b.equity() <= 0:
                continue
            a12 = P12.iloc[:i + 1]
            a4 = P4[P4.dt <= P12.dt.iloc[i] + pd.Timedelta("8h")]
            wengine.load_panels = lambda n, x=a12, y=a4: {"panel_12h": x, "panel_4h": y}
            b.px = float(a12.close.iloc[-1]); b.fillpx = eo[j]
            plan = wengine.plan_orders(strat, b, b.equity(), risk)
            wengine.execute(plan, b, armed=True, max_bar_age=1e9)

            nxt = d12[i + 2] if i + 2 < len(d12) else ens[-1] + 1
            k = int(np.searchsorted(ens, nxt, "left"))
            for t in range(j, min(k, len(ex))):
                b.px = ec[t]
                if b.qty and fund[t]:
                    b.cash -= fund[t] * b.qty * ec[t]
                b.touch(eh[t], el[t])
                eqc[t] = b.equity()

    tradebook.reconcile = real
    s = pd.Series(eqc, index=pd.to_datetime(ex.dt)).ffill().dropna()
    s = s.resample("1D").last().dropna()
    return s.pct_change().dropna(), np.array(b.pnl), b


if __name__ == "__main__":
    R = rankings()
    for risk in [float(x) for x in (sys.argv[1:] or ["0.08"])]:
        print(f"\n{'='*108}\nDEPLOYED CODE REPLAYED   risk {risk:.1%}\n{'='*108}")
        for mode, tag in (("targets", "TARGETS  resize every bar (what shipped)"),
                          ("trades",  "TRADES   backtested rules (this branch)")):
            r, pl, b = run(R, risk, mode)
            stats(r, pl, tag, risk)
            print(f"        orders {b.sent}   stops fired {b.stopped}   targets hit {b.tp}")
