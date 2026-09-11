import paths as _P
"""
Per-minute top-of-book features from Binance `bookTicker`.

This is the last Binance source not yet mined for BTCUSDT. Order-book imbalance
is the single most-documented short-horizon predictor in the microstructure
literature, and the microprice - the depth-weighted fair value - is its
canonical refinement. Neither is derivable from klines or from trade prints.

    obi        (bid_qty - ask_qty) / (bid_qty + ask_qty), time-weighted
    micro_dev  (microprice - mid) / mid, the depth-implied pull on price
    spread_bps quoted spread in bps, a liquidity/stress gauge
    depth_usd  quoted size at the touch
    obi_vol    within-minute standard deviation of obi (quote flickering)

Each day is downloaded, reduced to minute bars, and deleted before the next is
fetched, so peak disk stays near one day's file.
"""
import io, os, sys, zipfile, subprocess
import numpy as np, pandas as pd

BASE = ("https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/"
        "data/futures/um/daily/bookTicker/BTCUSDT")
COLS = ["update_id", "bid", "bid_qty", "ask", "ask_qty", "transaction_time", "event_time"]
TMP = str(_P.DATA / "raw/_bt.zip")

def one_day(day):
    url = f"{BASE}/BTCUSDT-bookTicker-{day}.zip"
    r = subprocess.run(["curl", "-sf", "--max-time", "600", "-o", TMP, url])
    if r.returncode != 0 or not os.path.exists(TMP):
        return None
    try:
        with zipfile.ZipFile(TMP) as z:
            raw = z.read(z.namelist()[0])
    except Exception:
        return None
    finally:
        pass
    first = raw[:80].decode(errors="ignore").split("\n")[0]
    hdr = 0 if not first.split(",")[0].strip().lstrip("-").isdigit() else None
    df = pd.read_csv(io.BytesIO(raw), header=hdr, names=None if hdr == 0 else COLS,
                     usecols=range(7),
                     dtype={1: "float64", 2: "float64", 3: "float64", 4: "float64"})
    df.columns = COLS
    t = df.transaction_time.astype("int64")
    unit = "us" if t.iloc[0] > 1e15 else "ms"
    df["dt"] = pd.to_datetime(t, unit=unit, utc=True).dt.floor("min")
    bq, aq = df.bid_qty.to_numpy(), df.ask_qty.to_numpy()
    b, a = df.bid.to_numpy(), df.ask.to_numpy()
    tot = bq + aq
    df["obi"] = np.where(tot > 0, (bq - aq) / np.where(tot == 0, np.nan, tot), np.nan)
    mid = 0.5 * (a + b)
    micro = np.where(tot > 0, (b * aq + a * bq) / np.where(tot == 0, np.nan, tot), np.nan)
    df["micro_dev"] = (micro - mid) / mid
    df["spread_bps"] = (a - b) / mid * 1e4
    df["depth_usd"] = tot * mid
    g = df.groupby("dt", sort=True)
    out = pd.DataFrame({
        "obi": g.obi.mean(),
        "obi_last": g.obi.last(),
        "obi_vol": g.obi.std(),
        "micro_dev": g.micro_dev.mean(),
        "spread_bps": g.spread_bps.mean(),
        "depth_usd": g.depth_usd.mean(),
        "n_quotes": g.size(),
    }).reset_index()
    del df
    return out

if __name__ == "__main__":
    import datetime as dt
    # bookTicker daily files exist only ~2023-06 .. early 2024; sample across that window
    days = []
    for start in ("2023-06-05", "2023-09-04", "2023-12-04", "2024-02-05"):
        d0 = dt.date.fromisoformat(start)
        days += [(d0 + dt.timedelta(days=i)).isoformat() for i in range(6)]
    parts = []
    for i, day in enumerate(days):
        o = one_day(day)
        if o is None:
            print("  MISS", day, flush=True); continue
        parts.append(o)
        if os.path.exists(TMP): os.remove(TMP)
        print(f"  {i+1}/{len(days)} {day}  minutes={len(o)}", flush=True)
    m = pd.concat(parts, ignore_index=True).drop_duplicates("dt").sort_values("dt")
    m.to_parquet(str(_P.DATA / "book_1m.parquet"))
    print(f"\nminute rows: {len(m)}   {m.dt.iloc[0]:%Y-%m-%d} -> {m.dt.iloc[-1]:%Y-%m-%d}")
    print(m[["obi","obi_vol","micro_dev","spread_bps","depth_usd","n_quotes"]]
          .describe().T[["mean","std","min","max"]].round(6).to_string())
