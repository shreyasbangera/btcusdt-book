"""The loop: panels -> strategy -> sleeves -> one net order -> a stop ladder.

The engine never asks a strategy what is held; it asks what SHOULD be held, sums
the sleeves, and moves the difference.  That keeps strategies stateless and makes
adding one a matter of answering a single question.
"""
import os, sys, json, datetime as dt
import webapp  # noqa: F401  - puts the project root on sys.path
import pandas as pd

from .config import STORE, MODE
from .strategies.registry import get, discover


def load_panels(names):
    out = {}
    for n in names:
        p = STORE / f"{n}.parquet"
        if not p.exists():
            raise FileNotFoundError(f"missing {p} — run `python live/fetch.py seed` first")
        out[n] = pd.read_parquet(p)
    return out


def plan_orders(strategy, broker, equity, risk, min_notional=100.0):
    """Everything the engine decides, as data.  Nothing is sent from here."""
    panels = load_panels(strategy.needs())
    d = strategy.decide(panels, equity, risk)
    target = sum(s.qty for s in d.sleeves)

    sides = {1 if s.qty > 0 else -1 for s in d.sleeves if s.qty}
    conflict = len(sides) > 1

    pos = broker.position()
    px = broker.price()
    delta = target - pos.qty
    order = None
    if abs(delta) * px >= min_notional and not conflict:
        order = dict(side="BUY" if delta > 0 else "SELL", qty=abs(delta),
                     notional=abs(delta) * px)

    ladder = []
    if not conflict:
        for s in d.sleeves:
            if s.qty and s.stop:
                ladder.append(dict(label=s.label, side="SELL" if s.qty > 0 else "BUY",
                                   qty=abs(s.qty), stop=s.stop, kind="STOP_MARKET"))
            if s.qty and s.take_profit:
                ladder.append(dict(label=s.label, side="SELL" if s.qty > 0 else "BUY",
                                   qty=abs(s.qty), stop=s.take_profit,
                                   kind="TAKE_PROFIT_MARKET"))

    return dict(
        ts=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        strategy=strategy.name, mode=broker.mode, price=px, equity=pos.equity or equity,
        position=pos.qty, target=target, delta=delta, order=order, ladder=ladder,
        sleeves=[dict(label=s.label, qty=s.qty, stop=s.stop, tp=s.take_profit,
                      hold_bars=s.hold_bars, meta=s.meta) for s in d.sleeves],
        diagnostics=d.diagnostics, note=d.note,
        conflict=conflict,
        conflict_note=("sleeves disagree on side — the engine refuses to net them. "
                       "This should be impossible for V7; investigate before trading."
                       if conflict else ""))


def execute(plan, broker, armed: bool):
    """Send the planned order and replace the stop ladder.  Refuses unless armed."""
    if not armed:
        return dict(sent=False, reason="not armed")
    if plan["conflict"]:
        return dict(sent=False, reason=plan["conflict_note"])
    done = []
    if plan["order"]:
        done.append(broker.market(plan["order"]["side"], plan["order"]["qty"],
                                  note=f"{plan['strategy']} rebalance"))
    broker.cancel_all()
    for leg in plan["ladder"]:
        done.append(broker.place_stop(leg["side"], leg["qty"], leg["stop"], leg["kind"]))
    return dict(sent=True, results=done)
