import paths as _P
"""
Per-minute microstructure features from tick-level aggTrades.

These cannot be derived from klines. Klines expose aggregate taker-buy volume;
ticks additionally expose WHO is trading (size distribution), HOW they trade
(order splitting, run lengths) and WHAT IT COSTS (price impact per unit of
signed flow).

    lg_imb    signed volume restricted to LARGE prints, normalised - the flow of
              participants who move size, separated from retail noise
    sm_imb    the same for SMALL prints - the retail side
    run_len   mean length of consecutive same-aggressor runs; long runs are the
              signature of a single participant working an order
    vpin      volume-synchronised probability of informed trading
    lam       Kyle's lambda: |price change| per unit of signed volume (impact)
    ntr_conc  Herfindahl concentration of trade sizes within the minute
"""
import zipfile, glob, io, os
import numpy as np, pandas as pd

COLS = ["agg_id", "price", "qty", "first_id", "last_id", "ts", "is_buyer_maker"]

def minute_features(path, big_usd=50_000.0, small_usd=1_000.0):
    with zipfile.ZipFile(path) as z:
        raw = z.read(z.namelist()[0])
    first = raw[:64].decode(errors="ignore").split("\n")[0]
    hdr = 0 if not first.split(",")[0].strip().lstrip("-").isdigit() else None
    df = pd.read_csv(io.BytesIO(raw), header=hdr, names=None if hdr == 0 else COLS,
                     usecols=range(7))
    df.columns = COLS
    t = df.ts.astype("int64")
    unit = "us" if t.iloc[0] > 1e15 else "ms"
    df["dt"] = pd.to_datetime(t, unit=unit, utc=True).dt.floor("min")
    df["price"] = pd.to_numeric(df.price, errors="coerce")
    df["qty"] = pd.to_numeric(df.qty, errors="coerce")
    bm = df.is_buyer_maker
    if bm.dtype == object:
        bm = bm.astype(str).str.lower().isin(["true", "1"])
    df["side"] = np.where(bm, -1.0, 1.0)          # taker sell = -1, taker buy = +1
    df["usd"] = df.price * df.qty
    df["sgn_usd"] = df.side * df.usd
    df["big"] = df.usd >= big_usd
    df["small"] = df.usd <= small_usd

    g = df.groupby("dt", sort=True)
    out = pd.DataFrame(index=g.size().index)
    tot = g.usd.sum()
    out["tot_usd"] = tot
    out["n_trades"] = g.size()
    out["imb"] = g.sgn_usd.sum() / tot.replace(0, np.nan)
    bigu = df[df.big].groupby("dt").usd.sum().reindex(out.index).fillna(0.0)
    bigs = df[df.big].groupby("dt").sgn_usd.sum().reindex(out.index).fillna(0.0)
    smlu = df[df.small].groupby("dt").usd.sum().reindex(out.index).fillna(0.0)
    smls = df[df.small].groupby("dt").sgn_usd.sum().reindex(out.index).fillna(0.0)
    out["big_frac"] = bigu / tot.replace(0, np.nan)
    out["lg_imb"] = bigs / bigu.replace(0, np.nan)
    out["sm_imb"] = smls / smlu.replace(0, np.nan)
    out["lg_sm_div"] = out.lg_imb - out.sm_imb          # institutions vs retail
    out["avg_usd"] = tot / out.n_trades.replace(0, np.nan)
    # aggressor run lengths
    sd = df.side.to_numpy()
    newrun = np.r_[True, sd[1:] != sd[:-1]]
    df["run_id"] = np.cumsum(newrun)
    rl = df.groupby(["dt", "run_id"]).size().groupby("dt").mean()
    out["run_len"] = rl.reindex(out.index)
    # VPIN-style absolute imbalance and size concentration
    out["vpin"] = (g.sgn_usd.sum().abs() / tot.replace(0, np.nan))
    hh = df.assign(w=(df.usd / df.dt.map(tot))**2).groupby("dt").w.sum()
    out["size_conc"] = hh.reindex(out.index)
    # Kyle's lambda: |return| per $ of signed flow
    px = g.price.agg(["first", "last"])
    ret = (px["last"] / px["first"] - 1.0)
    out["ret_1m"] = ret
    out["lam"] = ret.abs() / (out.imb.abs() * tot / 1e6).replace(0, np.nan)
    return out.reset_index()

if __name__ == "__main__":
    files = sorted(glob.glob(str(_P.DATA / "raw/agg/*.zip")))
    print(f"processing {len(files)} tick files...")
    parts = []
    for i, f in enumerate(files):
        try:
            parts.append(minute_features(f))
        except Exception as e:
            print("  skip", os.path.basename(f), e); continue
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(files)}")
    m = pd.concat(parts, ignore_index=True).drop_duplicates("dt").sort_values("dt")
    m.to_parquet(str(_P.DATA / "tick_1m.parquet"))
    print(f"\nminute rows: {len(m)}   {m.dt.iloc[0]:%Y-%m-%d} -> {m.dt.iloc[-1]:%Y-%m-%d}")
    print(m[["tot_usd","n_trades","imb","big_frac","lg_imb","sm_imb","run_len","vpin","size_conc"]]
          .describe().T[["mean","std","min","max"]].round(4).to_string())
