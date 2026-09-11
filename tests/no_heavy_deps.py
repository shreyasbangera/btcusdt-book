#!/usr/bin/env python3
"""The bot runs with neither numba nor pyarrow.  Proof, not a claim.

    python tests/no_heavy_deps.py

WHY THIS TEST EXISTS
--------------------
Where this bot can live is decided entirely by its dependency list, because
Binance refuses most datacentre ranges and the machines it does serve tend to
be small: a phone in a drawer, a home box, a micro VM.  Two dependencies were
in the way.

  numba    only the quarterly SELECTION needs it, and that happens elsewhere
  pyarrow  only the storage FORMAT needed it, and now it does not

Both are easy to reintroduce by accident - one `import` at the top of a module
the decision path happens to touch and the bot silently stops running on the
machines that matter, with no failure until deployment. So the claim is
enforced here: this blocks both modules outright and then makes a real
decision.
"""
import sys, os, tempfile, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Block:
    """Make named top-level packages un-importable for this process."""
    def __init__(self, *names):
        self.names = set(names)

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in self.names:
            raise ImportError(f"No module named {name!r} (blocked by this test)")
        return None


def panels_on_disk(store):
    """Panel files only. The paper broker keeps its ledger in the same
    directory, which is fine and not what this is checking."""
    return sorted(p.name for p in pathlib.Path(store).iterdir()
                  if p.name.startswith("panel_"))


def main():
    sys.meta_path.insert(0, Block("pyarrow", "fastparquet", "numba"))
    sys.path.insert(0, str(ROOT))

    store = tempfile.mkdtemp(prefix="book-store-")
    os.environ["BOOK_STORE"] = store
    os.environ["BOT_MODE"] = "paper"
    os.environ.pop("BOOK_PANEL_FORMAT", None)

    import pandas as pd, numpy as np
    import panelstore

    assert not panelstore.have_parquet()
    assert panelstore.preferred() == "pkl", panelstore.preferred()
    print(f"  ok  no parquet engine -> panels stored as {panelstore.preferred()}")

    for m in ("live.fetch", "live.runner", "live.v7", "webapp.once", "webapp.engine",
              "webapp.strategies.v7", "webapp.broker.paper", "webapp.broker.binance"):
        __import__(m)
        print(f"  ok  {m}")

    # The real panel schema, from tests/synth.py. An earlier version of this
    # test invented the column names, and because a store with no plan file
    # sends V7 down a shorter path it passed anyway - so it was not testing the
    # decision path it claimed to. The plan file below is what forces the long
    # way through build_signals().
    sys.path.insert(0, str(ROOT / "tests"))
    import synth, datetime as dtm
    bar = dtm.datetime.now(dtm.timezone.utc).replace(minute=0, second=0, microsecond=0)
    bar = bar.replace(hour=0 if bar.hour < 12 else 12)
    g, m4 = synth.write(store, bar)
    (pathlib.Path(store) / "v7_plan.json").write_bytes(
        (ROOT / "plans/v7_plan.json").read_bytes())

    on_disk = panels_on_disk(store)
    assert on_disk == ["panel_12h.pkl", "panel_4h.pkl"], on_disk
    print(f"  ok  wrote {on_disk}")

    back = panelstore.read(store, "panel_12h")
    assert back.equals(g), "the round trip changed the frame"
    assert str(back.dt.dtype) == str(g.dt.dtype), (back.dt.dtype, g.dt.dtype)
    print(f"  ok  round trip exact, dt still {back.dt.dtype}")

    from webapp import engine
    from webapp.strategies.registry import get
    from webapp.broker.paper import PaperBroker

    strat = get("v7")()
    panels = engine.load_panels(strat.needs())
    assert set(panels) == set(strat.needs())
    plan = engine.plan_orders(strat, PaperBroker(lambda: float(g.close.iloc[-1]), 10_000),
                              10_000, 0.08)
    assert "target" in plan, plan
    print(f"  ok  a decision came out: target={plan['target']} order={plan['order']}")

    # One panel per store, always. Two copies is the failure that looks like
    # success: the stale one gets read on the next machine that has pyarrow.
    os.environ["BOOK_PANEL_FORMAT"] = "pkl"
    panelstore.write(g, store, "panel_12h")
    on_disk = panels_on_disk(store)
    assert on_disk == ["panel_12h.pkl", "panel_4h.pkl"], on_disk
    print("  ok  never two formats of one panel in a store")

    print("\nPASS  the bot needs pandas and numpy, and nothing else.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
