import paths as _P
"""Positioning metrics for the alt complex, not just BTC.

Binance publishes the same long/short account ratios, top-trader position
ratios and open interest for every USD-M perpetual. The book already reads
BTC's own positioning; what it has never read is whether the REST of the
market is crowded the same way. Aggregate alt crowding is a different
population making a different bet, and it should not be the same signal.
"""
import os, io, zipfile, subprocess
import numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor

B = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/data/futures/um/daily/metrics"
SYMS = ["ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT"]
OUT = str(_P.DATA / "altmetrics")
os.makedirs(OUT, exist_ok=True)

def one(arg):
    sym, day = arg
    p = f"{OUT}/{sym}_{day}.parquet"
    if os.path.exists(p): return "cached"
    r = subprocess.run(["curl", "-s", "--max-time", "60",
                        f"{B}/{sym}/{sym}-metrics-{day}.zip"], capture_output=True)
    if r.returncode or len(r.stdout) < 300: return "miss"
    try:
        z = zipfile.ZipFile(io.BytesIO(r.stdout))
        with z.open(z.namelist()[0]) as fh:
            d = pd.read_csv(fh)
    except Exception:
        return "bad"
    keep = [c for c in d.columns if c in ("create_time", "symbol", "sum_open_interest_value",
            "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
            "count_long_short_ratio", "sum_taker_long_short_vol_ratio")]
    d = d[keep].copy()
    d["dt"] = pd.to_datetime(d.create_time, utc=True)
    d = d.set_index("dt").resample("1h").last().dropna(how="all").reset_index()
    d["sym"] = sym
    d.to_parquet(p, index=False)
    return "ok"

if __name__ == "__main__":
    days = pd.date_range("2021-03-01", "2026-08-31", freq="D").strftime("%Y-%m-%d").tolist()
    jobs = [(s, d) for s in SYMS for d in days if not os.path.exists(f"{OUT}/{s}_{d}.parquet")]
    print(f"{len(jobs)} files", flush=True)
    ok = miss = 0
    with ThreadPoolExecutor(max_workers=16) as ex:
        for i, r in enumerate(ex.map(one, jobs)):
            if r in ("ok", "cached"): ok += 1
            else: miss += 1
            if i % 1000 == 0: print(f"  {i}/{len(jobs)} ok={ok} miss={miss}", flush=True)
    fs = [f for f in os.listdir(OUT) if f.endswith(".parquet")]
    big = pd.concat([pd.read_parquet(f"{OUT}/{f}") for f in fs], ignore_index=True)
    big.to_parquet(str(_P.DATA / "altmetrics_1h.parquet"), index=False)
    print(f"done ok={ok} miss={miss}  {len(big)} rows  {big.dt.min()} -> {big.dt.max()}", flush=True)
    print(big.sym.value_counts().to_string(), flush=True)
