"""Data loading, validation and resampling for BTCUSDT research."""
import pandas as pd, numpy as np, os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

def load_1h(path=None):
    path = path or os.path.join(DATA_DIR, "raw_1h_2024_2025.csv")
    df = pd.read_csv(path)
    df["dt"] = pd.to_datetime(df["Date"], format="%d-%m-%Y %H:%M", utc=True)
    df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
    df = df[["dt","open","high","low","close","volume"]].sort_values("dt").reset_index(drop=True)
    return df

def validate(df, freq="1h"):
    """Return dict of data quality diagnostics."""
    out = {}
    out["rows"] = len(df)
    out["start"] = str(df.dt.iloc[0]); out["end"] = str(df.dt.iloc[-1])
    d = df.dt.diff().dropna()
    expected = pd.Timedelta(freq)
    out["gaps"] = int((d != expected).sum())
    out["gap_examples"] = [str(x) for x in d[d != expected].unique()[:5]]
    out["dupes"] = int(df.dt.duplicated().sum())
    # OHLC integrity
    bad_hi = (df.high < df[["open","close"]].max(axis=1) - 1e-9).sum()
    bad_lo = (df.low  > df[["open","close"]].min(axis=1) + 1e-9).sum()
    out["bad_high"] = int(bad_hi); out["bad_low"] = int(bad_lo)
    out["hl_inverted"] = int((df.high < df.low).sum())
    out["nonpositive"] = int((df[["open","high","low","close"]] <= 0).sum().sum())
    out["nan"] = int(df.isna().sum().sum())
    out["zero_volume_bars"] = int((df.volume <= 0).sum())
    # continuity: open[t] vs close[t-1] jumps
    jump = (df.open / df.close.shift(1) - 1).abs()
    out["max_open_gap_pct"] = float(jump.max()*100)
    out["open_gap_gt_1pct"] = int((jump > 0.01).sum())
    r = np.log(df.close/df.close.shift(1)).dropna()
    out["ann_vol_pct"] = float(r.std()*np.sqrt(365*24)*100)
    out["max_1h_move_pct"] = float((np.exp(r.abs().max())-1)*100)
    out["price_min"] = float(df.low.min()); out["price_max"] = float(df.high.max())
    return out

def resample(df, rule):
    """Resample 1h OHLCV to a coarser timeframe. Left-labelled, left-closed."""
    s = df.set_index("dt")
    o = s.resample(rule, label="left", closed="left").agg(
        open=("open","first"), high=("high","max"), low=("low","min"),
        close=("close","last"), volume=("volume","sum"))
    o = o.dropna().reset_index()
    return o


# ---------------------------------------------------------------- Binance data
import functools

@functools.lru_cache(maxsize=None)
def load(name):
    """name in {spot_1h, fut_1h, spot_15m, fut_15m, fut_5m, funding}"""
    return pd.read_parquet(os.path.join(DATA_DIR, f"{name}.parquet"))

def agg(df, rule):
    """Aggregate a base timeframe to a coarser one. Label = bar OPEN time."""
    s = df.set_index("dt")
    o = s.resample(rule, label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"),
        quote_volume=("quote_volume", "sum"), count=("count", "sum"),
        taker_buy_base=("taker_buy_base", "sum"))
    return o.dropna(subset=["open"]).reset_index()

def align_to_exec(sig_df, exec_df, arrays, lag=1):
    """
    Map per-signal-bar values onto the execution grid WITHOUT look-ahead.

    A value computed from signal bar t (which closes at sig_dt[t] + tf) may only
    influence execution bars that begin at or after that close.  `lag=1` shifts
    the signal series forward by one signal bar, then forward-fills onto the
    execution timestamps.  Execution bars before the first valid signal get NaN.
    """
    out = {}
    sd = pd.Series(sig_df.dt.to_numpy())
    tf = sd.diff().median()
    valid_from = sd + tf * lag          # timestamp at which signal bar t becomes usable
    ed = exec_df.dt.to_numpy()
    idx = np.searchsorted(valid_from.to_numpy(), ed, side="right") - 1
    ok = idx >= 0
    for k, v in arrays.items():
        v = np.asarray(v, dtype=float)
        r = np.full(len(ed), np.nan)
        r[ok] = v[idx[ok]]
        out[k] = r
    return out
