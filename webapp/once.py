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
import argparse, json, os, sys
import webapp  # noqa: F401  - puts the project root on sys.path

from webapp import config, engine
from webapp.strategies.registry import get
from webapp.broker.paper import PaperBroker
import pandas as pd


def make_broker(equity):
    if config.MODE in ("test", "live"):
        from webapp.broker.binance import BinanceFutures
        return BinanceFutures(config.MODE)
    df = pd.read_parquet(config.STORE / "panel_12h.parquet")
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
    a = ap.parse_args()

    armed = a.arm and not a.dry_run
    strat = get(a.strategy)()
    broker = make_broker(a.equity)
    plan = engine.plan_orders(strat, broker, a.equity, a.risk)

    if a.json:
        print(json.dumps(plan, indent=1, default=str))
    else:
        print(f"{plan['ts']}  mode={plan['mode']}  {plan['strategy']}")
        print(f"  price {plan['price']:,.1f}   equity {plan['equity']:,.2f}")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
