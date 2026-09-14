#!/usr/bin/env python3
"""A trade has to outlive the bar that opened it.

The whole point of running the backtested rules is that a sleeve keeps its size
and both its levels until a rule closes it.  These check the two halves of that:
the book's own bookkeeping, and that the engine reads it, hands it to the
strategy, and writes it only on an armed send.

    python tests/tradebook.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapp import tradebook
from webapp.strategies.base import Sleeve

FAIL = []
L = "#1 exp 3.0 · 3.0ATR ×2.0R · 14d"


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        FAIL.append(name)


print("1. a record survives while the trade is open")
SHORT = {L: dict(qty=-0.011, stop=80_869.8, tp=68_675.4, opened="2026-09-14T00:00:00+00:00",
                 hold_days=14)}
check("price between the levels -> kept", tradebook.reconcile(SHORT, 77_000.0, False) == SHORT)

print("\n2. and is dropped the moment the account says it cannot be open")
check("flat account -> book empty", tradebook.reconcile(SHORT, 77_000.0, True) == {})
check("short: price reached the stop", tradebook.reconcile(SHORT, 80_900.0, False) == {})
check("short: price reached the target", tradebook.reconcile(SHORT, 68_000.0, False) == {})

LONG = {L: dict(qty=0.011, stop=72_000.0, tp=85_000.0, opened=None, hold_days=14)}
check("long: price reached the stop", tradebook.reconcile(LONG, 71_000.0, False) == {})
check("long: price reached the target", tradebook.reconcile(LONG, 86_000.0, False) == {})
check("long: in between -> kept", tradebook.reconcile(LONG, 77_000.0, False) == LONG)

print("\n3. what a decision records")
snap = tradebook.snapshot([
    Sleeve(L, -0.004, 80_869.8, 68_675.4,
           meta=dict(opened="2026-09-14T00:00:00+00:00", hold_days=14)),
    Sleeve("#2 flat", 0.0, None, None, meta=dict()),
])
check("only sleeves actually holding something", set(snap) == {L}, sorted(snap))
check("the open time is carried, so the cap can be judged later",
      snap[L]["opened"] == "2026-09-14T00:00:00+00:00")
check("and the holding cap with it", snap[L]["hold_days"] == 14)

print("\n4. on disk")
with tempfile.TemporaryDirectory() as d:
    check("a missing file reads as empty, not an error", tradebook.load(d) == {})
    tradebook.save(d, snap)
    check("round trips", tradebook.load(d) == snap)
    open(os.path.join(d, "v7_trades.json"), "w").write("{ truncated")
    check("a half-written file reads as empty rather than killing the run",
          tradebook.load(d) == {})

print("\n5. the strategy is told what is open, and holds it unchanged")
import inspect
from webapp.strategies.v7 import V7
sig = inspect.signature(V7.decide)
check("V7.decide accepts a book", "book" in sig.parameters)
src = inspect.getsource(V7.decide)
check("it holds the recorded quantity, not a fresh one", 'qty=held["qty"]' in src)
check("and the recorded levels", 'stop=held.get("stop")' in src)
check("it closes on a flat signal", "signal flat" in src)
check("on the holding cap", "d cap" in src)
check("and on a reversal", "reversal" in src)
check("the flat test reads the UNGATED signal, as the backtest does",
      "if u0 == 0.0:" in src)

print("\n6. the engine wires it, and only an armed send writes")
import webapp.engine as E
esrc = inspect.getsource(E)
check("plan_orders reconciles against the account", "tradebook.reconcile(" in esrc)
check("...and passes it to the strategy", "book=book" in esrc)
check("execute persists it", "tradebook.save(" in esrc)
check("nothing else writes the book", esrc.count("tradebook.save(") == 1)
check("it is written before the ladder, so a rejected leg cannot hide a position",
      esrc.index("tradebook.save(") < esrc.index('for leg in plan["ladder"]'))

print("\n" + ("FAILED: " + ", ".join(FAIL) if FAIL else "trade book: all checks passed"))
sys.exit(1 if FAIL else 0)
