"""The loop: panels -> strategy -> sleeves -> one net order -> a stop ladder.

The engine never asks a strategy what is held; it asks what SHOULD be held, sums
the sleeves, and moves the difference.  That keeps strategies stateless and makes
adding one a matter of answering a single question.
"""
import os, sys, json, datetime as dt
import webapp  # noqa: F401  - puts the project root on sys.path
import pandas as pd
import panelstore

from .config import STORE, MODE
from .strategies.registry import get, discover


def _decision_bar(panels):
    """The last closed 12h bar - the one this decision is made on."""
    df = panels.get("panel_12h")
    if df is None or not len(df):
        return None
    return pd.Timestamp(df.dt.iloc[-1]).tz_convert("UTC")


def _bar_step(panels):
    """The panel's own bar length, rather than a hardcoded 12h."""
    df = panels.get("panel_12h")
    if df is None or len(df) < 3:
        return pd.Timedelta(hours=12)
    return pd.Series(df.dt).diff().median()


def _bar_age(panels):
    """Hours since the decision bar CLOSED.

    Measured from the CLOSE, not the label. Binance labels a bar by its OPEN
    time, so a bar labelled 12:00 covers 12:00-24:00 and is only decidable
    after 24:00. Measuring from the label made a bar that had just closed look
    12 hours old, and a bar still forming look fresh - the exact inversion of
    what the guard is for.
    """
    bar = _decision_bar(panels)
    if bar is None:
        return None
    close = bar + _bar_step(panels)
    return round((pd.Timestamp.now("UTC") - close).total_seconds() / 3600, 1)


def load_panels(names):
    return {n: panelstore.read(STORE, n) for n in names}


def plan_orders(strategy, broker, equity, risk, min_notional=100.0):
    """Everything the engine decides, as data.  Nothing is sent from here."""
    panels = load_panels(strategy.needs())

    # Ask the account what it holds BEFORE sizing anything. The first version
    # sized off the configured `equity` and only read the real balance
    # afterwards, for display - so a 10,000 setting against a 5,000 account
    # placed every bet at twice the intended risk, and the log showed the true
    # balance next to positions that had ignored it.
    pos = broker.position()
    px = broker.price()
    sizing_equity = pos.equity if pos.equity and pos.equity > 0 else equity

    d = strategy.decide(panels, sizing_equity, risk)
    target = sum(s.qty for s in d.sleeves)

    sides = {1 if s.qty > 0 else -1 for s in d.sleeves if s.qty}
    conflict = len(sides) > 1
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
        strategy=strategy.name, mode=broker.mode, price=px,
        equity=sizing_equity, configured_equity=equity,
        bar=(lambda b: b.isoformat() if b is not None else None)(_decision_bar(panels)),
        bar_age_hours=_bar_age(panels),
        position=pos.qty, target=target, delta=delta, order=order, ladder=ladder,
        sleeves=[dict(label=s.label, qty=s.qty, stop=s.stop, tp=s.take_profit,
                      hold_bars=s.hold_bars, meta=s.meta) for s in d.sleeves],
        diagnostics=d.diagnostics, note=d.note,
        conflict=conflict,
        conflict_note=("sleeves disagree on side — the engine refuses to net them. "
                       "This should be impossible for V7; investigate before trading."
                       if conflict else ""))


# Hours since the decision bar CLOSED. In normal operation the run fires within
# the hour after a close, so the age is near zero; past 13h the next bar has
# already closed too and this one is history.
#
# Two earlier versions of this were wrong in opposite directions. 24h was
# useless because the archive fallback lags 22-23h and sailed under it. Then the
# age was measured from the bar's LABEL, which is its OPEN time - so a bar that
# had just closed read as 12h old and a bar still forming read as fresh, which
# is precisely backwards.
MAX_BAR_AGE_HOURS = 13.0


def execute(plan, broker, armed: bool, max_bar_age=MAX_BAR_AGE_HOURS):
    """Send the planned order and replace the stop ladder.  Refuses unless armed.

    Also refuses on STALE DATA. The backtest fills at the open of the bar after
    the signal; acting on a bar that closed a day ago takes the same trades at
    prices that have already moved through most of what the signal predicted.
    A bot doing that twice a day forever is worse than one that stops, so a stale
    feed is a refusal rather than a warning nobody reads.
    """
    if not armed:
        return dict(sent=False, reason="not armed")
    if plan["conflict"]:
        return dict(sent=False, reason=plan["conflict_note"])
    age = plan.get("bar_age_hours")
    if age is not None and age < 0:
        # A negative age means the last row in the panel is a bar that has not
        # closed yet. That should be impossible - live/fetch.py drops the
        # forming bar from every feed - but if one ever gets in, its signals are
        # computed on half a bar and change with the clock. Refusing is the only
        # safe answer, and a panel written before that fix looks exactly like
        # this until the bar closes.
        return dict(sent=False, reason=(
            f"the last panel bar has not closed yet ({-age:.1f}h to go). Its "
            f"values are still moving, so any decision from it is not the "
            f"backtest's. Run `python live/fetch.py update` to clean the panel."))
    if age is not None and age > max_bar_age:
        return dict(sent=False, reason=(
            f"data is {age:.1f}h old (limit {max_bar_age:.0f}h). The decision bar "
            f"closed too long ago to trade on. Fix the feed rather than raising "
            f"the limit."))
    done = []
    if plan["order"]:
        # If the entry itself is rejected there is nothing to protect and
        # nothing worth reporting but that rejection, so this one may raise.
        done.append(broker.market(plan["order"]["side"], plan["order"]["qty"],
                                  note=f"{plan['strategy']} rebalance"))
    cancelled = broker.cancel_all()

    # Each leg is placed independently and a failure is COLLECTED, not raised.
    # Raising would abort before journal.record() and leave no trace of a
    # position that had just opened; swallowing is how a naked position hid
    # behind a log saying SENT. So place what can be placed, and report exactly
    # what could not.
    errors = []
    for leg in plan["ladder"]:
        try:
            done.append(broker.place_stop(leg["side"], leg["qty"],
                                          leg["stop"], leg["kind"]))
        except Exception as e:                     # noqa: BLE001 - see above
            errors.append(f"{leg['label']} {leg['kind']}: {e}")

    # `sent` gates journal.decided(), which gates --once-per-bar. A partially
    # protected position is NOT a decided bar: returning False lets the next
    # hourly run retry the ladder, which is safe because the rebalance will be
    # a no-op by then and cancel_all + re-place is idempotent.
    ok = not errors
    return dict(sent=ok, results=done, cancelled=cancelled, errors=errors,
                reason=("" if ok else
                        f"{len(errors)} of {len(plan['ladder'])} ladder legs "
                        f"REJECTED — position is not fully protected"))
