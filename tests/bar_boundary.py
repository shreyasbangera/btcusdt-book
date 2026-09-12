#!/usr/bin/env python3
"""The book decides on a CLOSED bar, and knows how old that bar is.

    python tests/bar_boundary.py

TWO BUGS THIS LOCKS DOWN, both found in a live Windows log rather than here.

1. THE FORMING BAR. Binance klines are labelled by OPEN time and the list
   always ends with the bar currently being built. The public archive never
   contains one, so a freshly seeded panel is clean and a REST top-up silently
   is not. The symptom in the log: two runs ten minutes apart, on the same 12h
   bar, returned a flat target and then +0.022 - because a new 4h positioning
   bucket had landed inside the unclosed bar. The position a laptop takes then
   depends on what time it happened to wake, which is not V7 and has no
   backtest behind it.

2. THE AGE REFERENCE. With the forming bar gone, the panel's last label is the
   OPEN of a bar that closed up to 12 hours later. Measuring staleness from the
   label made a just-closed bar look 12h old and a still-forming bar look
   fresh: precisely backwards, and it would have refused every legitimate run
   while waving through every illegitimate one.
"""
import sys, pathlib, datetime as dt
import pandas as pd, numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

UTC = dt.timezone.utc


def main():
    from live.fetch import drop_unclosed
    from webapp import engine

    now = pd.Timestamp("2026-09-11 20:03:00", tz="UTC")

    # --- 1. drop_unclosed ------------------------------------------------
    # 12h bars opening 00:00 and 12:00. At 20:03 the 12:00 bar is still open.
    d = pd.DataFrame({"dt": pd.to_datetime(
        ["2026-09-10 12:00", "2026-09-11 00:00", "2026-09-11 12:00"], utc=True)})
    out = drop_unclosed(d, "12h", now)
    assert list(out.dt.astype(str)) == ["2026-09-10 12:00:00+00:00",
                                        "2026-09-11 00:00:00+00:00"], list(out.dt)
    print("  ok  12h: the bar that opened at 12:00 is dropped at 20:03")

    # 4h: the 20:00 bucket is 3 minutes old and closes at 24:00.
    d4 = pd.DataFrame({"dt": pd.date_range("2026-09-11 00:00", periods=6, freq="4h",
                                           tz="UTC")})
    out4 = drop_unclosed(d4, "4h", now)
    assert str(out4.dt.iloc[-1]) == "2026-09-11 16:00:00+00:00", out4.dt.iloc[-1]
    assert len(out4) == 5, len(out4)
    print("  ok  4h: the forming 20:00 bucket is dropped, 16:00 kept")

    # A bar that closes exactly now counts as closed.
    d1 = pd.DataFrame({"dt": pd.to_datetime(["2026-09-11 19:00"], utc=True)})
    assert len(drop_unclosed(d1, "1h", now)) == 1
    print("  ok  a bar closing on the boundary counts as closed")

    assert len(drop_unclosed(pd.DataFrame({"dt": []}), "12h", now)) == 0
    print("  ok  an empty frame is not a crash")

    # --- 2. the age reference --------------------------------------------
    def panel_ending(open_time):
        n = 400
        dts = pd.date_range(end=pd.Timestamp(open_time), periods=n, freq="12h")
        return {"panel_12h": pd.DataFrame({"dt": dts, "close": np.arange(n) + 1.0})}

    # NOT floored to the hour: an earlier version of this rounded `now` down and
    # so asserted a range that depended on how many minutes past the hour the
    # suite happened to run. It passed for weeks and then did not. A test whose
    # result moves with the wall clock is worse than no test.
    real_now = pd.Timestamp.now("UTC")

    # A 12h bar that opened 13h ago closed exactly 1h ago.
    p = panel_ending(real_now - pd.Timedelta(hours=13))
    age = engine._bar_age(p)
    assert 0.9 <= age <= 1.1, f"a bar that closed an hour ago reads {age}h"
    print(f"  ok  a bar closed 1h ago reads {age}h old, not 13h")

    # And one that closed 20h ago reads 20h, so the guard can see it.
    p = panel_ending(real_now - pd.Timedelta(hours=32))
    age = engine._bar_age(p)
    assert 19.9 <= age <= 20.1, age
    assert age > engine.MAX_BAR_AGE_HOURS
    print(f"  ok  a bar closed 20h ago reads {age}h old and is past the limit")

    # --- 3. the guard actually refuses -----------------------------------
    class Dummy:
        mode = "paper"
        def cancel_all(self): return []
        def place_stop(self, *a, **k): return {}
        def market(self, *a, **k): return {}
    for hours, expect_sent in ((1, True), (20, False), (-4, False)):
        plan = dict(order=None, ladder=[], conflict=False, conflict_note="",
                    bar_age_hours=float(hours), strategy="t")
        r = engine.execute(plan, Dummy(), armed=True)
        assert bool(r.get("sent")) is expect_sent, (hours, r)
    print("  ok  execute() sends at 1h, refuses at 20h, refuses an UNCLOSED bar")

    # --- 4. end to end ----------------------------------------------------
    import synth, panelstore, tempfile, os
    from webapp.strategies.registry import get
    from webapp.broker.paper import PaperBroker
    store = pathlib.Path(tempfile.mkdtemp(prefix="bars-"))
    os.environ["BOOK_STORE"] = str(store)
    # last CLOSED 12h bar: the one whose close is most recent
    close = real_now.floor("12h")
    last_open = close - pd.Timedelta(hours=12)
    g, _ = synth.write(store, last_open)
    (store / "v7_plan.json").write_bytes((ROOT / "plans/v7_plan.json").read_bytes())

    import importlib
    from webapp import config
    importlib.reload(config)
    importlib.reload(engine)
    panels = engine.load_panels(["panel_12h", "panel_4h"])
    age = engine._bar_age(panels)
    assert age is not None and age < engine.MAX_BAR_AGE_HOURS, age
    plan = engine.plan_orders(get("v7")(), PaperBroker(lambda: float(g.close.iloc[-1]),
                                                       10_000), 10_000, 0.08)
    assert plan["bar_age_hours"] < engine.MAX_BAR_AGE_HOURS, plan["bar_age_hours"]
    r = engine.execute(plan, PaperBroker(lambda: float(g.close.iloc[-1]), 10_000), True)
    assert r.get("sent"), r
    print(f"  ok  a panel on the last closed bar ({age}h old) is tradeable")

    print("\nPASS  bar boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
