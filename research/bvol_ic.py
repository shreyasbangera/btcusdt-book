"""Implied volatility (Binance BVOL index) as a signal for the BTCUSDT perp.

BVOL is Binance's 30-day forward-looking implied volatility index for BTC - a
VIX analogue. It is the one data class this study had not touched: everything
until now was realised (prices, flow, positioning, open interest). Implied vol
is the market's PRICE of future risk, and the gap between it and subsequent
realised vol - the variance risk premium - is one of the most durable anomalies
in any asset class.

Signals tested, all from closed bars:
  iv        level, z-scored on a trailing window
  d_iv      change in IV
  vrp       IV - trailing realised vol (the premium)
  vrp_z     z-scored premium
  iv_rv     ratio
  iv_mom    IV momentum
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from scipy.stats import spearmanr

IS_END = "2025-01-01"

def zs(x, w):
    s = pd.Series(x)
    return ((s - s.rolling(w).mean()) / (s.rolling(w).std() + 1e-12)).to_numpy()

def build(tf="4h"):
    bv = pd.read_parquet(str(_P.DATA / "bvol_1m.parquet"))
    bv["dt"] = pd.to_datetime(bv.dt, utc=True).astype("datetime64[ns, UTC]")
    b = bv.set_index("dt")["iv"].resample(tf).last().dropna()
    f = pd.read_parquet(str(_P.DATA / "fut_1h.parquet"))
    f["dt"] = pd.to_datetime(f.dt, utc=True).astype("datetime64[ns, UTC]")
    f = f.set_index("dt").resample(tf).agg(
        dict(open="first", high="max", low="min", close="last", volume="sum")).dropna()
    df = f.join(b.rename("iv"), how="inner").dropna(subset=["iv"]).reset_index()
    bars_day = int(pd.Timedelta("1D") / pd.Timedelta(tf))
    c = df.close.to_numpy(float)
    lr = np.diff(np.log(c), prepend=np.log(c[0]))
    # trailing realised vol, annualised, in the same units as IV (percent)
    rv = pd.Series(lr).rolling(7 * bars_day).std().to_numpy() * np.sqrt(365 * bars_day) * 100
    rv30 = pd.Series(lr).rolling(30 * bars_day).std().to_numpy() * np.sqrt(365 * bars_day) * 100
    iv = df.iv.to_numpy(float)
    w = 30 * bars_day
    df["f_iv"] = zs(iv, w)
    df["f_d_iv"] = zs(pd.Series(iv).diff(bars_day).to_numpy(), w)
    df["f_vrp"] = iv - rv
    df["f_vrp_z"] = zs(iv - rv, w)
    df["f_vrp30"] = zs(iv - rv30, w)
    df["f_iv_rv"] = zs(iv / (rv + 1e-9), w)
    df["f_iv_mom"] = zs(pd.Series(iv).pct_change(3 * bars_day).to_numpy(), w)
    df["rv"] = rv
    return df, bars_day

if __name__ == "__main__":
    for tf in ("4h", "12h"):
        df, bd = build(tf)
        c = df.close.to_numpy(float)
        print(f"\n===== {tf}   {len(df)} bars  {df.dt.min().date()} -> {df.dt.max().date()}"
              f"   mean IV {df.iv.mean():.1f}%  mean RV(7d) {np.nanmean(df.rv):.1f}%"
              f"   mean VRP {np.nanmean(df.f_vrp):+.1f}pp")
        feats = [c_ for c_ in df.columns if c_.startswith("f_")]
        hors = [1, bd, 3 * bd, 7 * bd]
        print(f"{'feature':>10} | " + " | ".join(
            f"{'h='+str(h//bd)+'d' if h >= bd else 'h=1':>18}" for h in hors))
        print(f"{'':>10} | " + " | ".join(f"{'IS':>8}{'OOS':>10}" for h in hors))
        isf = (df.dt < IS_END).to_numpy()
        for ft in feats:
            row = f"{ft[2:]:>10} | "
            cells = []
            for h in hors:
                fwd = np.full(len(c), np.nan)
                fwd[:-h] = c[h:] / c[:-h] - 1.0
                x = df[ft].to_numpy(float)
                g = np.isfinite(x) & np.isfinite(fwd)
                a = spearmanr(x[g & isf], fwd[g & isf])[0] if (g & isf).sum() > 100 else np.nan
                b = spearmanr(x[g & ~isf], fwd[g & ~isf])[0] if (g & ~isf).sum() > 100 else np.nan
                cells.append(f"{a:+8.4f}{b:+10.4f}")
            print(row + " | ".join(cells))
