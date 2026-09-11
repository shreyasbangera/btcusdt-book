"""Simulated fills at the real price, charged what the backtest charged.

5 bps commission and 3 bps adverse slippage per side.  This is the only broker
whose numbers are directly comparable to the backtest, which is why it is the
default and why testnet is not.
"""
import json, os, datetime as dt
import numpy as np
from .base import Broker, Position
from ..config import STORE

FEE_BPS, SLIP_BPS = 5.0, 3.0


class PaperBroker(Broker):
    mode = "paper"

    def __init__(self, price_fn, equity=10_000.0, path=None):
        self.price_fn = price_fn
        self.path = str(path or STORE / "webapp_paper.json")
        if os.path.exists(self.path):
            self.b = json.load(open(self.path))
        else:
            self.b = dict(equity=equity, start=equity, qty=0.0, entry=0.0,
                          ledger=[], stops=[])
            self._save()

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        json.dump(self.b, open(self.path, "w"), indent=1)

    def price(self):
        return float(self.price_fn())

    def position(self):
        px = self.price()
        eq = self.b["equity"] + (self.b["qty"] * (px - self.b["entry"]) if self.b["qty"] else 0.0)
        return Position(self.b["qty"], self.b["entry"], eq)

    def market(self, side, qty, note="", at=None):
        """`at` forces the fill price. A stop that fires must fill at its own
        level, not at whatever the ticker happens to say - without this the
        broker reported a 150 USDT stop-out as a 4 USDT one."""
        px = float(at) if at is not None else self.price()
        sgn = 1.0 if side == "BUY" else -1.0
        fill = px * (1 + sgn * SLIP_BPS / 1e4)
        fee = abs(qty) * fill * FEE_BPS / 1e4
        pos, entry, realised = self.b["qty"], self.b["entry"], 0.0
        if pos * sgn < 0:
            closing = min(abs(qty), abs(pos))
            realised = np.sign(pos) * (fill - entry) * closing
            self.b["equity"] += realised
            after = pos + sgn * qty
            entry = 0.0 if abs(after) < 1e-12 else (fill if np.sign(after) != np.sign(pos) else entry)
            pos = after
        else:
            after = pos + sgn * qty
            entry = fill if abs(pos) < 1e-12 else (entry * abs(pos) + fill * abs(qty)) / abs(after)
            pos = after
        self.b["equity"] -= fee
        self.b["qty"], self.b["entry"] = pos, entry
        self.b["ledger"].append(dict(t=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                     side=side, qty=round(qty, 6), fill=round(fill, 2),
                                     fee=round(fee, 4), realised=round(realised, 2),
                                     pos=round(pos, 6), equity=round(self.b["equity"], 2),
                                     note=note))
        self._save()
        return dict(ok=True, fill=fill, fee=fee, realised=realised)

    def place_stop(self, side, qty, stop, kind="STOP_MARKET"):
        self.b["stops"].append(dict(side=side, qty=round(qty, 6), stop=round(stop, 2), kind=kind))
        self._save()
        return dict(ok=True, simulated=True)

    def cancel_all(self):
        self.b["stops"] = []; self._save(); return dict(ok=True)

    def open_orders(self):
        return self.b["stops"]

    def check_stops(self, high, low):
        """Called by the engine with the latest completed bar's range.  Fires any
        resting stop the bar traded through, worst case first."""
        fired = []
        for o in list(self.b["stops"]):
            hit = (o["side"] == "SELL" and low <= o["stop"]) or \
                  (o["side"] == "BUY" and high >= o["stop"])
            if hit:
                self.market(o["side"], o["qty"], at=o["stop"],
                            note=f"{o['kind']} @ {o['stop']}")
                self.b["stops"].remove(o); fired.append(o)
        if fired:
            self._save()
        return fired
