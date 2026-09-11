"""The strategy interface.  Add a strategy by subclassing Strategy and dropping
the file in this directory - `registry.py` discovers it automatically.

A strategy's only job is to answer one question, once per decision bar:

    given the data and my risk budget, what should I be holding?

It answers with a list of SLEEVES.  Most strategies return one.  V7 returns
three, because it holds three configurations at once.  The engine sums the
sleeves into a single net position and works out the order from there, so a
strategy never has to know what is currently held or what the exchange is doing.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Sleeve:
    label: str                      # shown in the UI, e.g. "exp 2.5 / 2.5ATR x3R"
    qty: float                      # SIGNED base-asset quantity; + long, - short
    stop: float | None = None       # price; the engine places it reduce-only
    take_profit: float | None = None
    hold_bars: int = 0              # 0 = no time cap
    meta: dict = field(default_factory=dict)


@dataclass
class Decision:
    sleeves: list[Sleeve]
    diagnostics: dict = field(default_factory=dict)   # anything to show in the UI
    note: str = ""


class Strategy:
    name = "unnamed"
    description = ""
    symbol = "BTCUSDT"
    decision_tf = "12h"             # how often targets change
    warmup_bars = 500               # bars of history needed before it is valid
    params: dict[str, Any] = {}     # editable defaults, surfaced in the UI

    def __init__(self, **params):
        self.params = {**self.params, **params}

    def needs(self) -> list[str]:
        """Panel names this strategy reads, e.g. ['panel_12h', 'panel_4h']."""
        return ["panel_12h"]

    def decide(self, panels: dict, equity: float, risk: float) -> Decision:
        raise NotImplementedError

    # -- helpers every strategy may use -------------------------------------
    @staticmethod
    def size_for(equity, risk, conviction, stop_distance, price, max_lev=10.0):
        """The sizing rule this whole study uses: risk a fixed fraction of
        equity, scaled by conviction, to the stop."""
        if stop_distance <= 0 or conviction == 0:
            return 0.0
        q = (equity * risk * abs(conviction)) / stop_distance
        return min(q, equity * max_lev / price)
