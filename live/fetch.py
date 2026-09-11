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
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
import panelstore, consoleio
consoleio.relax()         # see consoleio.py: Windows, redirected output

ARCHIVE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
FAPI = "https://fapi.binance.com"
DAPI = "https://dapi.binance.com"
STORE = os.environ.get("BOOK_STORE", os.path.expanduser("~/quant/data/live"))
ALTS = ["ETHUSDT","SOLUSDT","XRPUSDT","BNBUSDT","DOGEUSDT","ADAUSDT","LINKUSDT","AVAXUSDT",
        "DOTUSDT","LTCUSDT","BCHUSDT","ATOMUSDT","FILUSDT","NEARUSDT","TRXUSDT"]

def curl(url, timeout=30):
    r = subprocess.run(["curl", "-sS", "--max-time", str(timeout), url],
                       capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        raise RuntimeError(f"failed: {url}\n{r.stderr[:200]}")
    body = r.stdout.lstrip()
    if body.startswith("{"):
        # A LIST is data; an OBJECT is an error. Binance answers restricted
        # locations with {"code":0,"msg":"Service unavailable from a restricted
        # location..."}, and handing that to pandas fails somewhere unhelpful.
        try:
            j = json.loads(body)
            if isinstance(j, dict) and ("msg" in j or "code" in j):
                raise RuntimeError(f"Binance refused {url}\n  {j}")
        except json.JSONDecodeError:
            pass
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

def archive_funding(sym, months):
    """Funding settlements from the archive.

    The REST endpoint is the obvious source and it is not always reachable -
    GitHub's runners sit in datacentre ranges that Binance restricts, and the
    reply is then a JSON error OBJECT rather than a list, which fails far away as
    "If using all scalar values, you must pass an index". The archive has the
    same data, needs no key, and is reachable from anywhere.
    """
    out = []
    for ym in months:
        blob = curl_bin(f"{ARCHIVE}/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip")
        if blob is None: continue
        z = zipfile.ZipFile(io.BytesIO(blob))
        raw = z.read(z.namelist()[0]).decode("utf-8", "replace")
        hdr = 0 if raw.split("\n", 1)[0].lower().startswith("calc_time") else None
        d = pd.read_csv(io.StringIO(raw), header=hdr,
                        names=None if hdr == 0 else ["calc_time", "funding_interval_hours",
                                                     "last_funding_rate"])
        out.append(d)
    if not out:
        raise RuntimeError(f"no funding history in the archive for {sym}")
    d = pd.concat(out, ignore_index=True)
    d["dt"] = pd.to_datetime(pd.to_numeric(d.calc_time), unit="ms", utc=True)
    d["rate"] = pd.to_numeric(d.last_funding_rate, errors="coerce")
    return (d[["dt", "rate"]].dropna().drop_duplicates("dt")
            .sort_values("dt").reset_index(drop=True))


def funding_series(sym, months):
    """Funding, archive first and REST for the tail.

    Funding is the one series the archive cannot finish: there are no daily
    files, and the current month's monthly file does not exist until the month
    ends. So the archive always stops at the end of last month and only REST
    reaches today. When REST is unreachable the run continues on archive data
    and says how stale it is, because `s_fundz` is a 240-bar (120-day) z-score
    and a month of carried-forward constant quietly distorts it.
    """
    f = archive_funding(sym, months)
    try:
        f = (pd.concat([f, rest_funding(sym)]).drop_duplicates("dt", keep="last")
               .sort_values("dt").reset_index(drop=True))
    except RuntimeError as e:
        lag = (pd.Timestamp.now("UTC") - pd.Timestamp(f.dt.max())).days
        print(f"funding: REST unavailable, archive only (last settlement "
              f"{f.dt.max()}, {lag} days ago)\n  {e}", flush=True)
        if lag > 2:
            print(f"  WARNING: s_fundz z-scores over 120 days, so {lag} days of "
                  f"carried-forward funding degrades that signal.", flush=True)
    return f


def archive_metrics(sym, days):
    """Positioning metrics from the archive, at 5-minute resolution.

    This is the fix for the study's longest-standing operational weakness. The
    REST endpoints serve about 30 days, while `s_posn` needs 480 four-hour bars -
    80 days - so a REST-seeded store left that signal quietly wrong rather than
    missing. The archive carries the full history.
    """
    out = []
    for ymd in days:
        blob = curl_bin(f"{ARCHIVE}/data/futures/um/daily/metrics/{sym}/{sym}-metrics-{ymd}.zip")
        if blob is None: continue
        z = zipfile.ZipFile(io.BytesIO(blob))
        raw = z.read(z.namelist()[0]).decode("utf-8", "replace")
        out.append(pd.read_csv(io.StringIO(raw)))
    if not out:
        raise RuntimeError(f"no positioning metrics in the archive for {sym}")
    d = pd.concat(out, ignore_index=True)
    d["dt"] = pd.to_datetime(d.create_time, utc=True)
    ren = {"sum_toptrader_long_short_ratio": "tt_pos",
           "count_toptrader_long_short_ratio": "tt_acct",
           "count_long_short_ratio": "retail_acct"}
    d = d.rename(columns=ren)
    for c in ren.values():
        d[c] = pd.to_numeric(d[c], errors="coerce")
    # the book reads the LAST 5-minute observation inside each 4h bar
    d = (d.set_index("dt")[list(ren.values())].resample("4h").last()
          .dropna().reset_index())
    return d[["dt", "tt_pos", "tt_acct", "retail_acct"]]


TF_HOURS = {"1m": 1/60, "5m": 1/12, "15m": .25, "30m": .5, "1h": 1, "2h": 2,
            "4h": 4, "6h": 6, "8h": 8, "12h": 12, "1d": 24}


def drop_unclosed(d, tf, now=None):
    """Remove the bar that is still forming.

    THIS IS NOT COSMETIC. Binance klines are labelled by OPEN time and the list
    always ends with the CURRENT, INCOMPLETE bar. The archive never contains
    one, so a seeded panel is clean and a REST top-up silently is not.

    The book decides on a CLOSED 12h bar and the backtest acts at the open of
    the next one. Leaving the forming bar in makes the live bot compute its
    signals on half a bar - and worse, on a DIFFERENT half depending on what
    time the machine happened to wake, so two laptops running the same book
    take different positions. That is not a small error in V7; it is a
    different strategy with no backtest behind it.

    Observed in the wild: a run at 19:53 UTC returned a flat target and a run
    at 20:03 UTC on the same 12h bar returned +0.022, because a new 4h
    positioning bucket had landed inside the unclosed bar.
    """
    if not len(d):
        return d
    h = TF_HOURS.get(tf)
    if h is None:
        return d
    now = pd.Timestamp.now("UTC") if now is None else pd.Timestamp(now)
    return d[d.dt + pd.Timedelta(hours=h) <= now].reset_index(drop=True)


def rest_klines(sym, tf, limit=1500, base=FAPI, path="/fapi/v1/klines"):
    j = json.loads(curl(f"{base}{path}?symbol={sym}&interval={tf}&limit={limit}"))
    d = pd.DataFrame(j, columns=KL[:len(j[0])])
    d["dt"] = pd.to_datetime(d.open_time, unit="ms", utc=True)
    for c in ("open","high","low","close","volume","quote_volume","taker_buy_base"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[["dt","open","high","low","close","volume","quote_volume","taker_buy_base"]]
    return drop_unclosed(d, tf)

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
    out = out[["dt","tt_pos","tt_acct","retail_acct"]].sort_values("dt").reset_index(drop=True)
    # The current 4h bucket is partial for the same reason the klines are, and
    # it is the one that feeds the positioning composite - so it moves the
    # signal mid-bar. See drop_unclosed().
    return drop_unclosed(out, period)

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

def _update_from_archive(a, g_old, m_old):
    """Extend both panels from the archive, which lags by about a day.

    A day-old panel is worse than a live one and far better than no decision at
    all; the run prints how stale it is so the gap is visible rather than
    implied.
    """
    end = pd.Timestamp.now("UTC").normalize()
    start = min(pd.Timestamp(g_old.dt.max()), pd.Timestamp(m_old.dt.max())) - pd.Timedelta(days=2)
    days = pd.date_range(start.normalize(), end - pd.Timedelta(days=1),
                         freq="D").strftime("%Y-%m-%d").tolist()
    # Funding has no daily files, so reach back far enough to find at least one
    # complete monthly file - days inside the current month alone would find none.
    months = pd.date_range(end - pd.DateOffset(months=3), end,
                           freq="MS").strftime("%Y-%m").tolist()
    print(f"archive top-up: {len(days)} days", flush=True)
    k12 = archive_klines("BTCUSDT", "12h", [], days=days)
    cm12 = archive_klines("BTCUSD_PERP", "12h", [], market="futures/cm", days=days)
    hourly = {"BTCUSDT": archive_klines("BTCUSDT", "1h", [], days=days).set_index("dt")["quote_volume"]}
    alt = None
    for sym in ALTS:
        try:
            q = archive_klines(sym, "1h", [], days=days)
        except RuntimeError:
            continue
        v = q.set_index("dt")["quote_volume"]
        alt = v if alt is None else alt.add(v, fill_value=0)
    hourly["ALTSUM"] = alt
    m = (pd.concat([m_old, archive_metrics("BTCUSDT", days)])
           .drop_duplicates("dt", keep="last").sort_values("dt").reset_index(drop=True))
    g_new, _ = assemble(k12, cm12, hourly, funding_series("BTCUSDT", months), m)
    g = (pd.concat([g_old, g_new]).drop_duplicates("dt", keep="last")
           .sort_values("dt").reset_index(drop=True))
    g, m = drop_unclosed(g, "12h"), drop_unclosed(m, "4h")
    panelstore.write(g, STORE, "panel_12h")
    panelstore.write(m, STORE, "panel_4h")
    # from the bar's CLOSE: dt is the OPEN time, so a just-closed 12h bar is
    # labelled 12 hours ago and would otherwise always look stale
    lag = ((pd.Timestamp.now("UTC") - pd.Timestamp(g.dt.max())).total_seconds() / 3600) - 12
    print(f"12h panel now {len(g)} rows to {g.dt.max()} ({lag:.0f}h past its close); "
          f"4h panel {len(m)} rows to {m.dt.max()}")
    if lag > 18:          # from the CLOSE now, so 18h is already a bar behind
        print("WARNING: the panel is more than a day old. The archive publishes "
              "yesterday's file each morning; if this keeps growing, the data "
              "source is stale and the decisions are not current.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["seed","update"])
    ap.add_argument("--months", type=int, default=36, help="price history to seed")
    ap.add_argument("--metrics-months", type=int, default=15,
                    help="positioning history: the 12-month selection window plus "
                         "its 80-day warm-up")
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
        print("archive klines done; funding and positioning from the archive too",
              flush=True)
        funding = funding_series("BTCUSDT", months)
        # positioning only needs to cover the selection window plus its own
        # 480-bar (80-day) warm-up, not the whole price history
        mdays = pd.date_range(end - pd.DateOffset(months=a.metrics_months),
                              end - pd.Timedelta(days=1), freq="D").strftime("%Y-%m-%d").tolist()
        print(f"positioning metrics: {len(mdays)} daily files", flush=True)
        metrics4 = archive_metrics("BTCUSDT", mdays)
        g, m4 = assemble(k12, cm12, hourly, funding, metrics4)
        g, m4 = drop_unclosed(g, "12h"), drop_unclosed(m4, "4h")
        panelstore.write(g, STORE, "panel_12h")
        panelstore.write(m4, STORE, "panel_4h")
        print(f"wrote {len(g)} 12h rows and {len(m4)} 4h rows to {STORE}")
        print(f"\npositioning covers {(m4.dt.max() - m4.dt.min()).days} days, against the "
              f"80 the 480-bar z-scores need.")
    else:
        if not (panelstore.exists(STORE, "panel_4h")
                and panelstore.exists(STORE, "panel_12h")):
            print(f"no panels in {STORE} yet - seeding first", flush=True)
            sys.argv = [sys.argv[0], "seed", "--months", str(a.months)]
            return main()
        m_old = panelstore.read(STORE, "panel_4h")
        g_old = panelstore.read(STORE, "panel_12h")
        try:
            m_new = rest_metrics()
        except RuntimeError as e:
            # REST is not reachable everywhere - Binance restricts some datacentre
            # ranges, and GitHub's runners live in them. The archive has the same
            # data up to yesterday, so carry on a day behind rather than stopping.
            print(f"REST unavailable, extending from the archive instead:\n  {e}",
                  flush=True)
            return _update_from_archive(a, g_old, m_old)
        m = pd.concat([m_old, m_new]).drop_duplicates("dt", keep="last") \
              .sort_values("dt").reset_index(drop=True)
        m = drop_unclosed(m, "4h")
        panelstore.write(m, STORE, "panel_4h")
        k12 = rest_klines("BTCUSDT","12h"); cm12 = rest_klines("BTCUSD_PERP","12h",
                                                               base=DAPI, path="/dapi/v1/klines")
        hourly = {"BTCUSDT": rest_klines("BTCUSDT","1h").set_index("dt")["quote_volume"]}
        alt = None
        for s in ALTS:
            v = rest_klines(s,"1h").set_index("dt")["quote_volume"]
            alt = v if alt is None else alt.add(v, fill_value=0)
        hourly["ALTSUM"] = alt
        g_new, _ = assemble(k12, cm12, hourly, rest_funding(), m)
        g = pd.concat([g_old, g_new]).drop_duplicates("dt", keep="last") \
              .sort_values("dt").reset_index(drop=True)
        g = drop_unclosed(g, "12h")
        panelstore.write(g, STORE, "panel_12h")
        lag = ((pd.Timestamp.now("UTC") - pd.Timestamp(g.dt.max())).total_seconds()
               / 3600) - 12
        print(f"12h panel now {len(g)} rows to {g.dt.max()} ({lag:.0f}h past its "
              f"close);  4h panel {len(m)} rows to {m.dt.max()}")

if __name__ == "__main__":
    main()
