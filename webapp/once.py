#!/usr/bin/env python3
"""One decision, then exit.  For cron, GitHub Actions, Cloud Run Jobs - anything
that runs on a schedule rather than staying up.

WHY THIS IS ENOUGH
------------------
The long-running scheduler exists so the app can react between bars.  For this
book there is nothing to react to:

  * targets only change on a closed 12h bar, so there are exactly two decisions
    a day and nothing in between
  * the stops are REDUCE-ONLY orders resting on the exchange.  They fire whether
    or not anything of yours is running
  * the holding cap (14 or 21 days) and the flat-signal exit are both evaluated
    at a 12h close, which is what the backtest does

So a process that wakes twice a day, decides, places orders and exits is not a
degraded version of the bot.  It is the same bot, and it is faithful to the
backtest in a way a laptop that sleeps at 3am is not.

    python -m webapp.once                 # decide and, if armed, send
    python -m webapp.once --dry-run       # decide and print; never send
    python -m webapp.once --arm           # send without the UI's arming step

`--arm` is required to place anything.  Without it this is a dry run, so a
mis-fired cron job cannot trade.
"""
import argparse, json, os, sys, datetime as dt
import webapp  # noqa: F401  - puts the project root on sys.path
import panelstore

from webapp import config, engine, journal
from webapp.strategies.registry import get
from webapp.broker.paper import PaperBroker
import pandas as pd


def make_broker(equity):
    if config.MODE in ("test", "live"):
        from webapp.broker.binance import BinanceFutures
        return BinanceFutures(config.MODE)
    df = panelstore.read(config.STORE, "panel_12h")
    return PaperBroker(lambda: float(df.close.iloc[-1]), equity)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strategy", default=os.environ.get("BOT_STRATEGY", "v7"))
    ap.add_argument("--equity", type=float, default=float(os.environ.get("BOT_EQUITY", 10_000)))
    ap.add_argument("--risk", type=float, default=float(os.environ.get("BOT_RISK", 0.08)))
    ap.add_argument("--arm", action="store_true", help="actually place orders")
    ap.add_argument("--dry-run", action="store_true", help="never place orders (default)")
    ap.add_argument("--json", action="store_true", help="emit the plan as JSON")
    ap.add_argument("--once-per-bar", action="store_true",
                    help="do nothing if this 12h bar already has a decision. Use "
                         "this with an HOURLY schedule on a machine that sleeps: "
                         "the bar gets decided whenever the machine is next awake, "
                         "and every other run that day is a no-op.")
    a = ap.parse_args()

    armed = a.arm and not a.dry_run

    # Cheap pre-check, before the panel is even read: if the bar we are
    # currently inside has already been traded, there is nothing to do and no
    # reason to touch the exchange.
    now = dt.datetime.now(dt.timezone.utc)
    if a.once_per_bar and journal.decided(config.STORE, journal.floor_bar(now)):
        if not a.json:
            print(f"{now:%Y-%m-%dT%H:%M:%SZ}  bar "
                  f"{journal.floor_bar(now):%Y-%m-%dT%H:%MZ} already decided — nothing to do")
        return 0
    strat = get(a.strategy)()
    try:
        broker = make_broker(a.equity)
    except PermissionError as e:
        # The state every new install is in for its first hour: the schedule is
        # already firing and .env is still blank. A traceback every hour reads
        # like a broken bot rather than an unfinished setup.
        print(f"{now:%Y-%m-%dT%H:%M:%SZ}  cannot start: {e}\n"
              f"  Put your TESTNET key and secret in .env "
              f"(BINANCE_TEST_KEY / BINANCE_TEST_SECRET) and this will run.\n"
              f"  Get them at testnet.binancefuture.com. Nothing is placed until "
              f"you also pass --arm.", file=sys.stderr)
        return 3
    plan = engine.plan_orders(strat, broker, a.equity, a.risk)

    # And again against the bar the DATA actually landed on, which is not always
    # the bar the clock says: when the feed falls back to the archive it can be
    # a bar behind, and without this a second run would re-trade a bar that was
    # already decided and churn the stop ladder for nothing.
    if a.once_per_bar and plan.get("bar"):
        b = dt.datetime.fromisoformat(plan["bar"])
        if journal.decided(config.STORE, b):
            if not a.json:
                print(f"{plan['ts']}  data is still on bar {b:%Y-%m-%dT%H:%MZ}, "
                      f"already decided — nothing to do")
            return 0

    if a.json:
        print(json.dumps(plan, indent=1, default=str))
    else:
        print(f"{plan['ts']}  mode={plan['mode']}  {plan['strategy']}")
        eq, cfg = plan["equity"], plan.get("configured_equity")
        note = "" if cfg is None or abs(eq - cfg) < 1 else f"  (config said {cfg:,.0f})"
        print(f"  price {plan['price']:,.1f}   equity {eq:,.2f}{note}")
        age = plan.get("bar_age_hours")
        if age is not None:
            limit = engine.MAX_BAR_AGE_HOURS
            flag = f"  STALE - past the {limit:.0f}h limit, this will not trade" \
                   if age > limit else ""
            print(f"  bar {plan.get('bar','?')}, {age:.0f}h old{flag}")
        print(f"  held {plan['position']:+.4f}   target {plan['target']:+.4f}")
        for s in plan["sleeves"]:
            q = f"{s['qty']:+.4f}" if s["qty"] else "flat"
            print(f"    {s['label']:<44} {q:>10}"
                  + (f"  stop {s['stop']:,.1f}" if s["stop"] else ""))
        print(f"  order: {plan['order'] or 'none'}")
        if plan["note"]:
            print(f"  note:  {plan['note']}")

    if plan["conflict"]:
        print(f"REFUSED: {plan['conflict_note']}", file=sys.stderr)
        return 2

    r = engine.execute(plan, broker, armed)
    print(f"  {'SENT' if r.get('sent') else 'not sent'}"
          f"{'' if r.get('sent') else ' — ' + r.get('reason', '')}")

    # Every run goes in the record, sent or not. On a machine that is not always
    # on - a laptop - the gaps in this file are the difference between a result
    # you can reason about and one you cannot. See webapp/journal.py.
    journal.record(config.STORE, plan, r)
    if not a.json:
        print(journal.summary_line(config.STORE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
