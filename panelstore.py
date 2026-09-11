#!/usr/bin/env python3
"""Reading and writing the live panels without requiring pyarrow.

WHY THIS EXISTS
---------------
The twice-daily decision needs pandas and numpy and nothing else - the numba
backtest engine is only used by the quarterly selection, which happens
elsewhere and arrives as a committed plan file.  That small dependency set is
what lets the bot run on almost any always-on machine.

`pyarrow` was the one exception, and it is the one dependency that is NOT
available everywhere: there is no Termux (Android) build, and it is a ~40 MB
wheel that some small ARM images cannot install.  Since Binance refuses most
datacentre ranges, an old phone on a home connection is one of the few free
always-on machines that can actually trade - so parquet was, in practice,
deciding where this bot could live.

So the panels are stored as parquet WHEN pyarrow is present and as pickle when
it is not.  Both are exact: unlike CSV, neither loses a dtype.  (This project
has already been bitten once by a CSV round-trip turning a timestamp column
into strings, which surfaced as `'>' not supported between str and float`.)

The pickles are local derived caches, written by this checkout and regenerable
from the public archive at any time.  Nothing here ever unpickles a file from a
third party, which is the only situation in which the format's trust model
matters.

ONE PANEL ON DISK
-----------------
`write` deletes the other format's file after a successful write, so a store
never holds two copies of the same panel.  Without that, a machine that lost
pyarrow would start writing `panel_12h.pkl` next to a now-frozen
`panel_12h.parquet`, and a later read on a machine that had pyarrow back would
silently pick up the stale one.  A stale panel is the worst failure this bot
has, because it looks exactly like a working one.

    python panelstore.py                  # what is in the store, and in what format
    python panelstore.py convert pkl      # rewrite the store as pickle
    python panelstore.py convert parquet  # ... or back, if pyarrow is installed

Override the choice with BOOK_PANEL_FORMAT=parquet|pkl.
"""
import os, pathlib
import pandas as pd

EXT = {"parquet": ".parquet", "pkl": ".pkl"}


def have_parquet():
    for mod in ("pyarrow", "fastparquet"):
        try:
            __import__(mod)
            return True
        except ImportError:
            pass
    return False


def preferred():
    """The format this machine writes.  Read every time rather than cached at
    import, so a test can set the variable and get the behaviour."""
    want = (os.environ.get("BOOK_PANEL_FORMAT") or "").strip().lower()
    if want in EXT:
        return want
    return "parquet" if have_parquet() else "pkl"


def path(store, name, fmt=None):
    return pathlib.Path(store) / f"{name}{EXT[fmt or preferred()]}"


def find(store, name):
    """The panel on disk, preferring this machine's format.  None if absent."""
    p = path(store, name)
    if p.exists():
        return p
    for fmt in EXT:
        q = path(store, name, fmt)
        if q.exists():
            return q
    return None


def exists(store, name):
    return find(store, name) is not None


def read(store, name):
    p = find(store, name)
    if p is None:
        raise FileNotFoundError(
            f"no {name} in {store} - run `python live/fetch.py seed` first")
    if p.suffix == ".pkl":
        return pd.read_pickle(p)
    if not have_parquet():
        raise ImportError(
            f"{p} is parquet and this machine has no pyarrow. Either "
            f"`pip install pyarrow`, or convert the store on a machine that "
            f"has it: `python panelstore.py convert pkl`.")
    return pd.read_parquet(p)


def write(df, store, name):
    """Write the panel, then remove the same panel in the other format."""
    store = pathlib.Path(store)
    store.mkdir(parents=True, exist_ok=True)
    fmt = preferred()
    p = path(store, name, fmt)
    if fmt == "pkl":
        df.to_pickle(p)
    else:
        df.to_parquet(p, index=False)
    for other in EXT:
        if other != fmt:
            q = path(store, name, other)
            if q.exists():
                q.unlink()
    return p


def main(argv=None):
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    store = os.environ.get("BOOK_STORE", os.path.expanduser("~/quant/data/live"))
    names = ["panel_12h", "panel_4h"]

    if argv and argv[0] == "convert":
        fmt = argv[1] if len(argv) > 1 else "pkl"
        if fmt not in EXT:
            print(f"format must be one of {list(EXT)}")
            return 2
        if fmt == "parquet" and not have_parquet():
            print("cannot convert to parquet: pyarrow is not installed here")
            return 2
        for n in names:
            if not exists(store, n):
                print(f"  --  {n}: not in this store")
                continue
            df = read(store, n)                      # before the format changes
            os.environ["BOOK_PANEL_FORMAT"] = fmt    # so write() picks it
            print(f"  ok  {write(df, store, n)}  ({len(df)} rows)")
        return 0

    print(f"store            {store}")
    print(f"pyarrow          {'present' if have_parquet() else 'NOT installed'}")
    print(f"writes as        {preferred()}")
    for n in names:
        p = find(store, n)
        if p is None:
            print(f"  --  {n}: missing")
            continue
        try:
            df = read(store, n)
            print(f"  ok  {p.name:<20} {len(df):>6} rows, to {df.dt.max()}")
        except Exception as e:                        # unreadable is still news
            print(f"  !!  {p.name:<20} {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
