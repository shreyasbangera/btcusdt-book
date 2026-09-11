"""The autonomous loop.

Without this the dashboard is a calculator you have to press.  This runs the
decision on its own schedule so the bot keeps trading while nobody is watching -
which is the entire point of automating it.

Two cadences, for different reasons:

    decisions   at each 12h close (00:05 and 12:05 UTC, a few minutes after the
                bar so the data feed has caught up).  This is when targets can
                change at all, because the signals only move on a closed bar.
    stop watch  every 60s, and ONLY in paper mode.  On testnet and live the
                exchange holds the reduce-only stops and fires them itself; in
                paper mode nothing else will.

If it is not armed it still computes and logs, it simply does not send.  That
makes a disarmed bot a live dry run rather than a dead one, so you can watch a
full week of decisions before letting it touch anything.
"""
import asyncio, datetime as dt, traceback
from collections import deque

LOG = deque(maxlen=400)
_TASK = None


def log(kind, msg, **extra):
    LOG.append(dict(t=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    kind=kind, msg=msg, **extra))


def next_decision(now=None):
    """The next 12h boundary plus a 5-minute grace for the data feed."""
    now = now or dt.datetime.now(dt.timezone.utc)
    for h in (0, 12, 24):
        t = now.replace(hour=h % 24, minute=5, second=0, microsecond=0)
        if h == 24:
            t += dt.timedelta(days=1)
        if t > now:
            return t
    return now + dt.timedelta(hours=12)


async def _decide_once(state, make_broker, get_strategy, engine):
    strat = get_strategy(state["strategy"])()
    broker = make_broker()
    plan = engine.plan_orders(strat, broker, state["equity"], state["risk"])
    state["last_plan"] = plan
    o = plan["order"]
    log("decision",
        f"{plan['strategy']} @ {plan['price']:,.1f} — target {plan['target']:+.4f}, "
        f"held {plan['position']:+.4f}" + (f", order {o['side']} {o['qty']:.4f}" if o else ", no order"),
        armed=state["armed"], mode=plan["mode"])
    if plan["conflict"]:
        log("refused", plan["conflict_note"]); return
    r = engine.execute(plan, broker, state["armed"])
    log("sent" if r.get("sent") else "held", r.get("reason", "order and ladder sent"))


async def _run(state, make_broker, get_strategy, engine, mode_fn):
    log("start", "scheduler running")
    last_stop_check = 0.0
    while True:
        try:
            nxt = next_decision()
            log("idle", f"next decision {nxt.isoformat(timespec='minutes')}")
            while dt.datetime.now(dt.timezone.utc) < nxt:
                await asyncio.sleep(20)
                if mode_fn() == "paper":
                    b = make_broker()
                    if hasattr(b, "check_stops"):
                        px = b.price()
                        fired = b.check_stops(high=px, low=px)
                        for f in fired:
                            log("stop", f"{f['kind']} fired: {f['side']} {f['qty']:.4f} @ {f['stop']}")
            await _decide_once(state, make_broker, get_strategy, engine)
        except asyncio.CancelledError:
            log("stop", "scheduler stopped"); raise
        except Exception as e:
            log("error", f"{type(e).__name__}: {e}")
            traceback.print_exc()
            await asyncio.sleep(60)


def start(state, make_broker, get_strategy, engine, mode_fn):
    """Must be called from the event loop - i.e. from an `async def` route.
    `asyncio.get_event_loop()` raises in FastAPI's sync worker threads."""
    global _TASK
    if _TASK and not _TASK.done():
        return False
    _TASK = asyncio.create_task(_run(state, make_broker, get_strategy, engine, mode_fn))
    return True


def stop():
    global _TASK
    if _TASK and not _TASK.done():
        _TASK.cancel(); _TASK = None; return True
    return False


def running():
    return bool(_TASK and not _TASK.done())
