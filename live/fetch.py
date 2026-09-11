#!/usr/bin/env python3
"""
Data collection for the live book.

Two sources, because neither alone is enough:

  ARCHIVE  data.binance.vision publishes the full history of everything the
           book needs, as daily/monthly zips.  Used to SEED the local store.
  REST     fapi.binance.com serves the last ~30 days of positioning metrics
           and current klines.  Used to TOP UP daily.

The split exists because the signals need 240-day z-scores while the
positioning endpoints only return 30 days.  A store seeded once from the
archive and topped up daily is the only way to have both depth and freshness.

Nothing here needs an API key: every endpoint used is public.
"""
import os, io, sys, json, zipfile, argparse, subprocess
import numpy as np, pandas as pd

ARCHIVE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
FAPI = "https://fapi.binance.com"
DAPI = "https://dapi.binance.com"
STORE = os.environ.get("BOOK_STORE", os.path.expanduser("~/quant/data/live"))
ALTS = ["ETHUSDT","SOLUSDT","XRPUSDT","BNBUSDT","DOGEUSDT","ADAUSDT","LINKUSDT","AVAXUSDT",
        "DOTUSDT","LTCUSDT","BCHUSDT","ATOMUSDT","FILUSDT","NEARUSDT","TRXUSDT"]

def curl(url, timeout=30):
    r = subprocess.run(["curl","-sS","--max-time",str(timeout),url],
                       capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        raise RuntimeError(f"failed: {url}\n{r.stderr[:200]}")
    return r.stdout

def curl_bin(url, timeout=90):
    r = subprocess.run(["curl","-sS","--max-time",str(timeout),url], capture_output=True)
    return r.stdout if r.returncode == 0 and len(r.stdout) > 500 else None

KL = ["open_time","open","high","low","close","volume","close_time","quote_volume",
      "count","taker_buy_base","taker_buy_quote","ignore"]

def archive_klines(sym, tf, months, market="futures/um"):
    """Monthly kline zips from the public archive."""
    out = []
    for ym in months:
        blob = curl_bin(f"{ARCHIVE}/data/{market}/monthly/klines/{sym}/{tf}/{sym}-{tf}-{ym}.zip")
        if blob is None: continue
        z = zipfile.ZipFile(io.BytesIO(blob))
        with z.open(z.namelist()[0]) as fh:
            d = pd.read_csv(fh, header=None)
        d = d.iloc[:, :12]; d.columns = KL[:d.shape[1]]
        out.append(d)
    if not out: return pd.DataFrame()
    d = pd.concat(out, ignore_index=True)
    unit = "us" if d.open_time.max() > 1e15 else "ms"
    d["dt"] = pd.to_datetime(d.open_time, unit=unit, utc=True)
    for c in ("open","high","low","close","volume","quote_volume","taker_buy_base"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d[["dt","open","high","low","close","volume","quote_volume","taker_buy_base"]] \
             .sort_values("dt").reset_index(drop=True)

def rest_klines(sym, tf, limit=1500, base=FAPI, path="/fapi/v1/klines"):
    j = json.loads(curl(f"{base}{path}?symbol={sym}&interval={tf}&limit={limit}"))
    d = pd.DataFrame(j, columns=KL[:len(j[0])])
    d["dt"] = pd.to_datetime(d.open_time, unit="ms", utc=True)
    for c in ("open","high","low","close","volume","quote_volume","taker_buy_base"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d[["dt","open","high","low","close","volume","quote_volume","taker_buy_base"]]

def rest_metrics(sym="BTCUSDT", period="4h", limit=500):
    """Positioning ratios.  ~30 days of history is all these endpoints return."""
    def q(p):
        j = json.loads(curl(f"{FAPI}/futures/data/{p}?symbol={sym}&period={period}&limit={limit}"))
        return pd.DataFrame(j)
    tp = q("topLongShortPositionRatio").rename(columns={"longShortRatio":"tt_pos"})
    ta = q("topLongShortAccountRatio").rename(columns={"longShortRatio":"tt_acct"})
    ga = q("globalLongShortAccountRatio").rename(columns={"longShortRatio":"retail_acct"})
    out = tp[["timestamp","tt_pos"]].merge(ta[["timestamp","tt_acct"]], on="timestamp") \
            .merge(ga[["timestamp","retail_acct"]], on="timestamp")
    out["dt"] = pd.to_datetime(out.timestamp, unit="ms", utc=True).dt.floor("4h")
    for c in ("tt_pos","tt_acct","retail_acct"): out[c] = pd.to_numeric(out[c], errors="coerce")
    return out[["dt","tt_pos","tt_acct","retail_acct"]].sort_values("dt").reset_index(drop=True)

def rest_funding(sym="BTCUSDT", limit=1000):
    j = json.loads(curl(f"{FAPI}/fapi/v1/fundingRate?symbol={sym}&limit={limit}"))
    d = pd.DataFrame(j)
    d["dt"] = pd.to_datetime(d.fundingTime, unit="ms", utc=True)
    d["rate"] = pd.to_numeric(d.fundingRate, errors="coerce")
    return d[["dt","rate"]].sort_values("dt").reset_index(drop=True)

def assemble(k12, cm12, alt_hourly, funding, metrics4):
    """Fold the raw pieces into the two panels runner.py expects."""
    g = k12.copy()
    g["cm_px"] = cm12.set_index("dt")["close"].reindex(g.dt).ffill(limit=2).to_numpy()
    # btc_dom_z is a 480-HOUR z-score, so it is computed hourly then sampled to 12h
    btc_h, alt_h = alt_hourly["BTCUSDT"], alt_hourly["ALTSUM"]
    dom = (btc_h / (btc_h + alt_h)).dropna()
    z = ((dom - dom.rolling(480).mean()) / (dom.rolling(480).std() + 1e-12))
    g["btc_dom_z"] = z.resample("12h").last().reindex(g.dt).to_numpy()
    fd = funding.dt.to_numpy(); rt = funding.rate.to_numpy()
    i = np.searchsorted(fd, g.dt.to_numpy(), side="right") - 1     # strictly past
    g["fund"] = np.where(i >= 0, rt[np.maximum(i, 0)], np.nan)
    return g, metrics4

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["seed","update"])
    ap.add_argument("--months", type=int, default=36, help="history to seed")
    a = ap.parse_args()
    os.makedirs(STORE, exist_ok=True)
    if a.mode == "seed":
        end = pd.Timestamp.utcnow().normalize()
        months = pd.date_range(end - pd.DateOffset(months=a.months), end,
                               freq="MS").strftime("%Y-%m").tolist()
        print(f"seeding {len(months)} months from the archive...")
        k12 = archive_klines("BTCUSDT", "12h", months)
        cm12 = archive_klines("BTCUSD_PERP", "12h", months, market="futures/cm")
        hourly = {"BTCUSDT": archive_klines("BTCUSDT","1h",months).set_index("dt")["quote_volume"]}
        alt = None
        for s in ALTS:
            q = archive_klines(s, "1h", months)
            if not len(q): continue
            v = q.set_index("dt")["quote_volume"]
            alt = v if alt is None else alt.add(v, fill_value=0)
            print(f"  {s} ok", flush=True)
        hourly["ALTSUM"] = alt
        print("archive done; funding and positioning come from REST")
        funding = rest_funding(); metrics4 = rest_metrics()
        g, m4 = assemble(k12, cm12, hourly, funding, metrics4)
        g.to_parquet(f"{STORE}/panel_12h.parquet", index=False)
        m4.to_parquet(f"{STORE}/panel_4h.parquet", index=False)
        print(f"wrote {len(g)} 12h rows and {len(m4)} 4h rows to {STORE}")
        print("\nNOTE: the REST positioning endpoints only return ~30 days. The 4h panel\n"
              "will be too short for the 480-bar z-scores until you have run `update`\n"
              "daily for a few months, OR you backfill it from your own records.")
    else:
        m_old = pd.read_parquet(f"{STORE}/panel_4h.parquet")
        m_new = rest_metrics()
        m = pd.concat([m_old, m_new]).drop_duplicates("dt", keep="last") \
              .sort_values("dt").reset_index(drop=True)
        m.to_parquet(f"{STORE}/panel_4h.parquet", index=False)
        k12 = rest_klines("BTCUSDT","12h"); cm12 = rest_klines("BTCUSD_PERP","12h",
                                                               base=DAPI, path="/dapi/v1/klines")
        hourly = {"BTCUSDT": rest_klines("BTCUSDT","1h").set_index("dt")["quote_volume"]}
        alt = None
        for s in ALTS:
            v = rest_klines(s,"1h").set_index("dt")["quote_volume"]
            alt = v if alt is None else alt.add(v, fill_value=0)
        hourly["ALTSUM"] = alt
        g_new, _ = assemble(k12, cm12, hourly, rest_funding(), m)
        g_old = pd.read_parquet(f"{STORE}/panel_12h.parquet")
        g = pd.concat([g_old, g_new]).drop_duplicates("dt", keep="last") \
              .sort_values("dt").reset_index(drop=True)
        g.to_parquet(f"{STORE}/panel_12h.parquet", index=False)
        print(f"12h panel now {len(g)} rows to {g.dt.max()};  4h panel {len(m)} rows to {m.dt.max()}")

if __name__ == "__main__":
    main()
