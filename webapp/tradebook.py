"""The open trades, so a position can outlive the bar that opened it.

WHY THIS EXISTS
---------------
V7's published numbers come from engine/core.py, which is a TRADE simulator: it
opens a position at the signal, FREEZES the quantity and the stop for the life of
that trade, and closes it on the stop, the target, a flat signal, a reversal or
the holding cap.

webapp/ shipped as a TARGET simulator instead: every 12h it recomputed the wanted
size from the current conviction and re-derived both levels from the current
close.  Same signals, different strategy - and replaying the deployed code gives
Sharpe 0.99 against the backtest's 2.15.

Running the tested rules means remembering what is open.  That is all this is:
one record per sleeve label, written only after an armed send, so a dry run can
read the book but never change it.

A record is dropped when reality says the trade is over:
  * the account is flat                  - nothing is open, whatever we recorded
  * price has reached the stop or target - the exchange filled it; we may not
                                           have seen the fill yet
  * the label is gone                    - the quarterly reselection replaced
                                           that configuration
"""
import json, os


def path(store):
    return os.path.join(str(store), "v7_trades.json")


def load(store):
    try:
        with open(path(store)) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(store, obj):
    p = path(store)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, p)              # never leave a half-written book


def spent(rec, px):
    """True if price has already reached this trade's stop or target."""
    long = rec["qty"] > 0
    stop, tp = rec.get("stop"), rec.get("tp")
    if long:
        return (stop and px <= stop) or (tp and px >= tp)
    return (stop and px >= stop) or (tp and px <= tp)


def reconcile(book, px, flat):
    """Drop records the account can no longer be holding."""
    if flat:
        return {}
    return {k: r for k, r in book.items() if not spent(r, px)}


def snapshot(sleeves):
    """What is open after this decision, as the engine is about to place it."""
    out = {}
    for s in sleeves:
        if not s.qty:
            continue
        m = s.meta or {}
        out[s.label] = dict(qty=s.qty, stop=s.stop, tp=s.take_profit,
                            opened=m.get("opened"), hold_days=m.get("hold_days"))
    return out
