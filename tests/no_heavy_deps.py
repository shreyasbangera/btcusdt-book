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

    # A synthetic panel with the columns the book reads. The NUMBERS are
    # meaningless - a random walk has no signal - so this asserts that a
    # decision comes out, never what it is.
    n, rng = 900, np.random.default_rng(0)
    px = 40_000 * np.exp(np.cumsum(rng.normal(0, .02, n)))
    g = pd.DataFrame({
        "dt": pd.date_range("2024-01-01", periods=n, freq="12h", tz="UTC"),
        "open": px, "high": px * 1.01, "low": px * .99, "close": px,
        "volume": rng.uniform(1e3, 1e4, n), "quote_volume": rng.uniform(1e7, 1e8, n),
        "cm_px": px * 1.0001, "dom": rng.uniform(.3, .6, n),
        "funding": rng.normal(0, 1e-4, n), "oi": rng.uniform(1e9, 2e9, n),
        "ls_ratio": rng.uniform(.8, 1.3, n), "taker_ratio": rng.uniform(.8, 1.3, n),
        "top_ratio": rng.uniform(.8, 1.3, n)})
    m4 = pd.DataFrame({
        "dt": pd.date_range("2024-01-01", periods=n * 3, freq="4h", tz="UTC"),
        "oi": rng.uniform(1e9, 2e9, n * 3), "ls_ratio": rng.uniform(.8, 1.3, n * 3),
        "taker_ratio": rng.uniform(.8, 1.3, n * 3), "top_ratio": rng.uniform(.8, 1.3, n * 3)})

    panelstore.write(g, store, "panel_12h")
    panelstore.write(m4, store, "panel_4h")
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
