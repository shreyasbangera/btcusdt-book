#!/usr/bin/env python3
"""The conditional-order path, which was broken from the day it was written.

    python tests/conditional_orders.py

Binance moved STOP_MARKET / TAKE_PROFIT_MARKET off POST /fapi/v1/order to a
separate Algo Service on 2025-12-09. The old endpoint answers -4120 and the bot
went on placing market entries with no stops behind them, because three things
each hid the failure independently:

    curl -sS has no -f        -> HTTP 400 parsed as a successful reply
    execute() returned True   -> without inspecting what came back
    once.py printed SENT      -> and never logged the replies

Any one of those alone would have made it visible. This file pins all three,
plus the endpoint contract, because the first symptom was a real account
holding a position with zero protective orders and a log that said SENT.

No network: a fake transport records what WOULD be sent.
"""
import sys, pathlib, json

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from webapp.broker.binance import BinanceFutures, BinanceError
from webapp import engine

FAIL = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


class FakeBroker(BinanceFutures):
    """A BinanceFutures whose transport records instead of sending."""

    def __init__(self, replies=None):
        self.mode = "test"
        self.symbol = "BTCUSDT"
        self.recv = 5000
        self.key, self.secret, self.base = "k", "s", "https://x"
        self.sent = []
        self.replies = replies or {}

    def _curl(self, args):
        url = args[-1]
        method = args[args.index("-X") + 1] if "-X" in args else "GET"
        path = url.split("?")[0].replace(self.base, "")
        params = dict(p.split("=", 1) for p in url.split("?")[1].split("&")
                      if "=" in p) if "?" in url else {}
        self.sent.append((method, path, params))
        return self.replies.get(path, {"ok": True})


print("1. the endpoint contract")
b = FakeBroker()
b.place_stop("SELL", 0.017, 72385.4, "STOP_MARKET")
method, path, p = b.sent[-1]
check("posts to the Algo endpoint", path == "/fapi/v1/algoOrder", path)
check("method is POST", method == "POST")
check("algoType=CONDITIONAL is set", p.get("algoType") == "CONDITIONAL")
check("type carries the order kind", p.get("type") == "STOP_MARKET")
check("uses triggerPrice, not stopPrice",
      "triggerPrice" in p and "stopPrice" not in p, sorted(p))
check("still reduce-only", p.get("reduceOnly") == "true")
check("triggers on mark price", p.get("workingType") == "MARK_PRICE")

b = FakeBroker()
b.place_stop("SELL", 0.0067, 86802.4, "TAKE_PROFIT_MARKET")
check("take-profit uses the same endpoint",
      b.sent[-1][1] == "/fapi/v1/algoOrder" and
      b.sent[-1][2].get("type") == "TAKE_PROFIT_MARKET")

print("\n2. both order books are listed and cancelled")
b = FakeBroker({"/fapi/v1/openOrders": [], "/fapi/v1/openAlgoOrders": [{"algoId": 1}]})
orders = b.open_orders()
paths = [s[1] for s in b.sent]
check("open_orders queries the plain book", "/fapi/v1/openOrders" in paths)
check("open_orders queries the algo book", "/fapi/v1/openAlgoOrders" in paths)
check("open_orders merges both", orders == [{"algoId": 1}], orders)

b = FakeBroker()
b.cancel_all()
paths = [s[1] for s in b.sent]
check("cancel_all clears plain orders", "/fapi/v1/allOpenOrders" in paths)
check("cancel_all clears algo orders", "/fapi/v1/algoOpenOrders" in paths)

print("\n3. a rejection is an exception, not a plausible dict")
b = FakeBroker({"/fapi/v1/algoOrder": {"code": -4120, "msg": "Order type not supported"}})
try:
    b.place_stop("SELL", 0.017, 72385.4)
    check("error payload raises", False, "returned instead of raising")
except BinanceError as e:
    check("error payload raises", True, f"[{e.code}]")
    check("carries the code", e.code == -4120)

b = FakeBroker({"/fapi/v1/order": {"code": 200, "msg": "done"}})
try:
    b.market("BUY", 0.017)
    check("a positive code is not an error", True)
except BinanceError:
    check("a positive code is not an error", False, "code 200 treated as failure")

print("\n4. a quantity that rounds to zero is refused loudly")
b = FakeBroker()
try:
    b.place_stop("SELL", 0.0004, 72385.4)
    check("sub-step quantity raises", False, "would have sent quantity=0.000")
except BinanceError:
    check("sub-step quantity raises", True)


print("\n5. execute() cannot report SENT when the ladder was refused")


class LadderBroker:
    """Market order succeeds; every conditional order is rejected."""

    def __init__(self, fail=True):
        self.fail = fail
        self.placed = 0

    def market(self, side, qty, note=""):
        return {"orderId": 1}

    def cancel_all(self):
        return {"plain": {}, "algo": {}}

    def place_stop(self, side, qty, stop, kind="STOP_MARKET"):
        if self.fail:
            raise BinanceError({"code": -4120, "msg": "nope"}, "POST /fapi/v1/algoOrder")
        self.placed += 1
        return {"algoId": self.placed}


plan = dict(conflict=False, bar_age_hours=1.0, strategy="v7", position=0.017,
            order=dict(side="BUY", qty=0.017),
            ladder=[dict(label=f"#{i}", side="SELL", qty=0.005,
                         stop=72385.4, kind="STOP_MARKET") for i in range(3)])

r = engine.execute(plan, LadderBroker(fail=True), armed=True)
check("sent is False when legs are refused", r["sent"] is False)
check("every failure is reported", len(r["errors"]) == 3, r["errors"][:1])
check("the reason names the danger", "not fully protected" in r["reason"].lower(),
      r["reason"])

r = engine.execute(plan, LadderBroker(fail=False), armed=True)
check("sent is True when the ladder lands", r["sent"] is True)
check("no errors on success", r["errors"] == [])

print("\n6. a refused ladder leaves the bar UNDECIDED so the next run retries")
# journal.decided() keys off `sent`; that is the whole mechanism by which
# --once-per-bar would otherwise skip a position that never got its stops.
from webapp import journal  # noqa: E402
import tempfile, datetime as dt  # noqa: E402

with tempfile.TemporaryDirectory() as store:
    bar = dt.datetime(2026, 9, 11, 12, tzinfo=dt.timezone.utc)
    p = dict(ts=bar.isoformat(), bar=bar.isoformat(), strategy="v7", mode="test",
             price=1.0, equity=1.0, position=0.017, target=0.017, order=None,
             bar_age_hours=1.0)
    journal.record(store, p, dict(sent=False, reason="legs REJECTED"))
    check("a refused ladder is not a decided bar",
          journal.decided(store, bar) is False)
    journal.record(store, p, dict(sent=True, reason=""))
    check("a clean run is a decided bar", journal.decided(store, bar) is True)


print()
if FAIL:
    print(f"FAILED: {len(FAIL)} check(s): {', '.join(FAIL)}")
    raise SystemExit(1)
print("conditional orders: all checks passed")
