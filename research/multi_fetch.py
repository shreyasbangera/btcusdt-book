import paths as _P
"""
Data for the cross-instrument test: ETHUSDT, SOLUSDT, ZECUSDT, XRPUSDT.

Everything comes from the public archive, which has full history for all of
them. Per instrument: 12h klines (for flow and ATR), funding, positioning
metrics, and the coin-margined perpetual where one exists (ZEC has none, so it
runs on four signals rather than five).
"""
import os, io, sys, zipfile, subprocess
import numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor

B = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
OUT = str(_P.DATA / "multi")
SYMS = ["ETHUSDT","SOLUSDT","ZECUSDT","XRPUSDT","BNBUSDT","DOGEUSDT","ADAUSDT","LINKUSDT","AVAXUSDT","LTCUSDT"]
COINM = {"ETHUSDT":"ETHUSD_PERP","SOLUSDT":"SOLUSD_PERP","XRPUSDT":"XRPUSD_PERP","BNBUSDT":"BNBUSD_PERP","DOGEUSDT":"DOGEUSD_PERP","ADAUSDT":"ADAUSD_PERP","LINKUSDT":"LINKUSD_PERP","AVAXUSDT":"AVAXUSD_PERP","LTCUSDT":"LTCUSD_PERP"}
KL = ["open_time","open","high","low","close","volume","close_time","quote_volume",
      "count","taker_buy_base","taker_buy_quote","ignore"]
MONTHS = pd.date_range("2021-06-01", "2026-08-01", freq="MS").strftime("%Y-%m").tolist()
DAYS = pd.date_range("2021-12-01", "2026-08-31", freq="D").strftime("%Y-%m-%d").tolist()

def blob(url, t=90):
    r = subprocess.run(["curl","-s","--max-time",str(t),url], capture_output=True)
    return r.stdout if r.returncode == 0 and len(r.stdout) > 400 else None

def klines(sym, tf, market="um"):
    out = []
    def one(ym):
        b = blob(f"{B}/data/futures/{market}/monthly/klines/{sym}/{tf}/{sym}-{tf}-{ym}.zip")
        if b is None: return None
        z = zipfile.ZipFile(io.BytesIO(b))
        with z.open(z.namelist()[0]) as fh:
            d = pd.read_csv(fh, header=None)
        d = d.iloc[:, :12]; d.columns = KL[:d.shape[1]]
        return d
    with ThreadPoolExecutor(max_workers=10) as ex:
        for d in ex.map(one, MONTHS):
            if d is not None: out.append(d)
    if not out: return pd.DataFrame()
    d = pd.concat(out, ignore_index=True)
    d = d[pd.to_numeric(d.open_time, errors="coerce").notna()]
    ot = pd.to_numeric(d.open_time)
    d["dt"] = pd.to_datetime(ot, unit="us" if ot.max() > 1e15 else "ms", utc=True)
    for c in ("open","high","low","close","volume","quote_volume","taker_buy_base"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d[["dt","open","high","low","close","volume","quote_volume","taker_buy_base"]] \
             .drop_duplicates("dt").sort_values("dt").reset_index(drop=True)

def funding(sym):
    out = []
    def one(ym):
        b = blob(f"{B}/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip")
        if b is None: return None
        z = zipfile.ZipFile(io.BytesIO(b))
        with z.open(z.namelist()[0]) as fh:
            return pd.read_csv(fh)
    with ThreadPoolExecutor(max_workers=10) as ex:
        for d in ex.map(one, MONTHS):
            if d is not None: out.append(d)
    if not out: return pd.DataFrame()
    d = pd.concat(out, ignore_index=True)
    tc = [c for c in d.columns if "time" in c.lower()][0]
    rc = [c for c in d.columns if "rate" in c.lower()][0]
    d = d[pd.to_numeric(d[tc], errors="coerce").notna()]
    t = pd.to_numeric(d[tc])
    d["dt"] = pd.to_datetime(t, unit="us" if t.max() > 1e15 else "ms", utc=True)
    d["rate"] = pd.to_numeric(d[rc], errors="coerce")
    return d[["dt","rate"]].drop_duplicates("dt").sort_values("dt").reset_index(drop=True)

def metrics(sym):
    keep = ["create_time","sum_open_interest_value","count_toptrader_long_short_ratio",
            "sum_toptrader_long_short_ratio","count_long_short_ratio"]
    def one(day):
        b = blob(f"{B}/data/futures/um/daily/metrics/{sym}/{sym}-metrics-{day}.zip", 60)
        if b is None: return None
        try:
            z = zipfile.ZipFile(io.BytesIO(b))
            with z.open(z.namelist()[0]) as fh:
                d = pd.read_csv(fh)
        except Exception: return None
        return d[[c for c in keep if c in d.columns]]
    out = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        for i, d in enumerate(ex.map(one, DAYS)):
            if d is not None: out.append(d)
            if i % 400 == 0: print(f"    metrics {sym} {i}/{len(DAYS)}", flush=True)
    if not out: return pd.DataFrame()
    d = pd.concat(out, ignore_index=True)
    d["dt"] = pd.to_datetime(d.create_time, utc=True)
    d = d.rename(columns={"sum_toptrader_long_short_ratio":"tt_pos",
                          "count_toptrader_long_short_ratio":"tt_acct",
                          "count_long_short_ratio":"retail_acct",
                          "sum_open_interest_value":"oi"})
    for c in ("tt_pos","tt_acct","retail_acct","oi"):
        if c in d: d[c] = pd.to_numeric(d[c], errors="coerce")
    cols = ["dt"] + [c for c in ("tt_pos","tt_acct","retail_acct","oi") if c in d]
    return d[cols].drop_duplicates("dt").sort_values("dt").reset_index(drop=True)

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for s in SYMS:
        p = f"{OUT}/{s}_12h.parquet"
        if not os.path.exists(p):
            k = klines(s, "12h"); k.to_parquet(p, index=False)
            print(f"{s} klines {len(k)} {k.dt.min()} -> {k.dt.max()}", flush=True)
        p = f"{OUT}/{s}_funding.parquet"
        if not os.path.exists(p):
            f = funding(s); f.to_parquet(p, index=False)
            print(f"{s} funding {len(f)}", flush=True)
        if s in COINM:
            p = f"{OUT}/{s}_cm.parquet"
            if not os.path.exists(p):
                c = klines(COINM[s], "12h", market="cm"); c.to_parquet(p, index=False)
                print(f"{s} coin-margined {len(c)}", flush=True)
        p = f"{OUT}/{s}_15m.parquet"
        if not os.path.exists(p):
            k = klines(s, "15m"); k.to_parquet(p, index=False)
            print(f"{s} 15m {len(k)}", flush=True)
        p = f"{OUT}/{s}_metrics.parquet"
        if not os.path.exists(p):
            m = metrics(s); m.to_parquet(p, index=False)
            print(f"{s} metrics {len(m)} {m.dt.min() if len(m) else '-'} -> {m.dt.max() if len(m) else '-'}", flush=True)
    print("done")
