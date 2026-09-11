import paths as _P
"""Stream Binance BTC BVOL (implied volatility index) daily files -> minute bars.
Download -> reduce to 1-minute OHLC -> delete raw, so peak disk stays small."""
import os, sys, io, zipfile, subprocess, datetime as dt
import numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor

B = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/data/option/daily/BVOLIndex/BTCBVOLUSDT"
OUT = str(_P.DATA / "bvol")
os.makedirs(OUT, exist_ok=True)

def one(day):
    p = f"{OUT}/{day}.parquet"
    if os.path.exists(p): return day, "cached"
    url = f"{B}/BTCBVOLUSDT-BVOLIndex-{day}.zip"
    r = subprocess.run(["curl","-s","--max-time","90",url], capture_output=True)
    if r.returncode or len(r.stdout) < 500: return day, "miss"
    try:
        z = zipfile.ZipFile(io.BytesIO(r.stdout))
        with z.open(z.namelist()[0]) as fh:
            df = pd.read_csv(fh, usecols=[0,4], names=["t","iv"], header=0)
    except Exception as e:
        return day, f"bad:{e}"
    if not len(df): return day, "empty"
    df["dt"] = pd.to_datetime(df.t, unit="ms", utc=True).dt.floor("1min")
    g = df.groupby("dt")["iv"]
    out = pd.DataFrame({"iv": g.last(), "iv_hi": g.max(), "iv_lo": g.min(),
                        "iv_mean": g.mean(), "n": g.size()}).reset_index()
    out.to_parquet(p, index=False)
    return day, f"ok:{len(out)}"

days = pd.date_range("2023-06-20", "2026-09-09", freq="D").strftime("%Y-%m-%d").tolist()
todo = [d for d in days if not os.path.exists(f"{OUT}/{d}.parquet")]
print(f"{len(todo)} days to fetch", flush=True)
ok = miss = 0
with ThreadPoolExecutor(max_workers=12) as ex:
    for i, (d, s) in enumerate(ex.map(one, todo)):
        if s.startswith("ok") or s == "cached": ok += 1
        else: miss += 1
        if i % 100 == 0: print(f"  {i}/{len(todo)} ok={ok} miss={miss} last={d}:{s}", flush=True)
print(f"done ok={ok} miss={miss}", flush=True)

fs = sorted(os.listdir(OUT))
fs = [f for f in fs if f.endswith(".parquet") and f != "bvol_1m.parquet"]
big = pd.concat([pd.read_parquet(f"{OUT}/{f}") for f in fs]).sort_values("dt").reset_index(drop=True)
big.to_parquet(str(_P.DATA / "bvol_1m.parquet"), index=False)
print("merged", len(big), big.dt.min(), big.dt.max(), flush=True)
