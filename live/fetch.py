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
    """Fetch a zip, or None if the archive does not have it.

    Validity is decided by the ZIP MAGIC BYTES, not by size. The previous
    version required > 500 bytes to reject error pages, which also silently
    discarded every legitimate daily file - a 12h daily kline zip is about 415
    bytes because it holds two bars. The panel then stopped at the last complete
    month and nothing said so.
    """
    r = subprocess.run(["curl", "-sS", "--max-time", str(timeout), url],
                       capture_output=True)
    if r.returncode or len(r.stdout) < 22:      # 22 = smallest possible zip
        return None
    return r.stdout if r.stdout[:2] == b"PK" else None

KL = ["open_time","open","high","low","close","volume","close_time","quote_volume",
      "count","taker_buy_base","taker_buy_quote","ignore"]

def _read_kline_zip(blob):
    """One archive zip to a frame.

    Binance added a HEADER ROW to these CSVs; older files have none. Reading a
    headered file with header=None turns the header into a data row, and the
    frame then fails in confusing ways far from here. Detect it instead of
    assuming either format.
    """
    z = zipfile.ZipFile(io.BytesIO(blob))
    raw = z.read(z.namelist()[0]).decode("utf-8", "replace")
    if not raw.strip():
        return None
    hdr = 0 if raw.split("\n", 1)[0].lower().startswith("open_time") else None
    d = pd.read_csv(io.StringIO(raw), header=hdr)
    d = d.iloc[:, :12]
    d.columns = KL[:d.shape[1]]          # normalise positionally; names vary by era
    return d


def archive_klines(sym, tf, months, market="futures/um", days=None):
    """Kline zips from the public archive.

    Monthly files for whole months, plus DAILY files for the current month,
    which has no monthly file until it ends. Without the daily tail the panel
    stops up to a month short of today, which for a live book is fatal and
    silent.
    """
    out = []
    for ym in months:
        blob = curl_bin(f"{ARCHIVE}/data/{market}/monthly/klines/{sym}/{tf}/{sym}-{tf}-{ym}.zip")
        if blob is None: continue
        d = _read_kline_zip(blob)
        if d is not None: out.append(d)
    for ymd in (days or []):
        blob = curl_bin(f"{ARCHIVE}/data/{market}/daily/klines/{sym}/{tf}/{sym}-{tf}-{ymd}.zip")
        if blob is None: continue
        d = _read_kline_zip(blob)
        if d is not None: out.append(d)
    if not out:
        raise RuntimeError(
            f"no archive data for {sym} {tf} ({market}). Tried {len(months)} monthly "
            f"and {len(days or [])} daily files and every one was missing or empty. "
            f"Check the symbol and that {ARCHIVE} is reachable.")
    d = pd.concat(out, ignore_index=True)
    d["open_time"] = pd.to_numeric(d.open_time, errors="coerce")
    d = d.dropna(subset=["open_time"])
    unit = "us" if d.open_time.max() > 1e15 else "ms"   # Binance switched in 2025
    d["dt"] = pd.to_datetime(d.open_time, unit=unit, utc=True)
    for c in ("open","high","low","close","volume","quote_volume","taker_buy_base"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return (d[["dt","open","high","low","close","volume","quote_volume","taker_buy_base"]]
            .drop_duplicates("dt").sort_values("dt").reset_index(drop=True))

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
        end = pd.Timestamp.now("UTC").normalize()
        months = pd.date_range(end - pd.DateOffset(months=a.months), end,
                               freq="MS").strftime("%Y-%m").tolist()
        # The current month has no monthly file yet, so take it a day at a time.
        # Yesterday is the last day the archive is guaranteed to have published.
        days = pd.date_range(end.replace(day=1), end - pd.Timedelta(days=1),
                             freq="D").strftime("%Y-%m-%d").tolist()
        print(f"seeding {len(months)} months + {len(days)} days from the archive...",
              flush=True)
        k12 = archive_klines("BTCUSDT", "12h", months, days=days)
        cm12 = archive_klines("BTCUSD_PERP", "12h", months, market="futures/cm", days=days)
        hourly = {"BTCUSDT": archive_klines("BTCUSDT","1h",months,
                                            days=days).set_index("dt")["quote_volume"]}
        alt = None
        for s in ALTS:
            try:
                q = archive_klines(s, "1h", months, days=days)
            except RuntimeError as e:
                print(f"  {s} skipped: {e}", flush=True); continue
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
        if not (os.path.exists(f"{STORE}/panel_4h.parquet")
                and os.path.exists(f"{STORE}/panel_12h.parquet")):
            print(f"no panels in {STORE} yet - seeding first", flush=True)
            sys.argv = [sys.argv[0], "seed", "--months", str(a.months)]
            return main()
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
