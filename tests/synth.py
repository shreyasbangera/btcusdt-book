"""A synthetic pair of panels with the REAL schema, for tests that must not
touch the network.

The column names here are load-bearing. An earlier version of the dependency
test invented plausible-looking names, and because a store with no plan file
sends V7 down a shorter path, it passed anyway - testing rather less than it
claimed to. The schema below is the one `live/fetch.py: assemble()` writes and
`live/runner.py: build_signals()` reads:

    12h   dt open high low close volume taker_buy_base cm_px btc_dom_z fund
    4h    dt tt_pos tt_acct retail_acct

The NUMBERS are meaningless. They are shaped to be non-degenerate - a drifting
price, positioning that actually moves - so that the book takes a position and
an assertion about "it decided" is not vacuous. Nothing here should ever assert
WHAT the decision is.
"""
import numpy as np
import pandas as pd

BARS_12H = 900          # 450 days: past the 480-bar z-score warm-up
BARS_4H = 2700          # the same span, and past the 480 4h-bar warm-up


def panels(last_bar, seed=7):
    """Two frames ending exactly on `last_bar`, so the staleness guard passes."""
    rng = np.random.default_rng(seed)
    n, n4 = BARS_12H, BARS_4H
    dt12 = pd.date_range(end=pd.Timestamp(last_bar), periods=n, freq="12h", tz="UTC")
    px = 40_000 * np.exp(np.cumsum(rng.normal(.004, .02, n)))
    vol = rng.uniform(1e3, 1e4, n)
    g = pd.DataFrame({
        "dt": dt12,
        "open": px, "high": px * 1.012, "low": px * .988, "close": px,
        "volume": vol,
        # order flow that wanders rather than sitting at half
        "taker_buy_base": vol * np.clip(.5 + np.cumsum(rng.normal(0, .01, n)) * .02, .2, .8),
        "cm_px": px * (1 + rng.normal(0, 3e-4, n)),
        "btc_dom_z": np.cumsum(rng.normal(0, .12, n)),
        "fund": rng.normal(-1e-4, 1.2e-4, n)})

    dt4 = pd.date_range(end=pd.Timestamp(last_bar), periods=n4, freq="4h", tz="UTC")
    m4 = pd.DataFrame({
        "dt": dt4,
        "tt_pos": np.exp(np.cumsum(rng.normal(0, .01, n4))) * 1.4,
        "tt_acct": np.exp(np.cumsum(rng.normal(0, .01, n4))) * 1.9,
        "retail_acct": np.exp(np.cumsum(rng.normal(0, .01, n4))) * 2.3})
    return g, m4


def write(store, last_bar, seed=7):
    import panelstore
    g, m4 = panels(last_bar, seed)
    panelstore.write(g, store, "panel_12h")
    panelstore.write(m4, store, "panel_4h")
    return g, m4
