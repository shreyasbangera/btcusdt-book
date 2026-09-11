"""Options volatility skew as a signal for the BTCUSDT perp.

The 25-delta risk reversal is the most watched sentiment number in any options
market: what traders pay for upside relative to downside. Butterfly prices both
tails at once. Put/call open interest is positioning. Dealer gamma is the
mechanical part - where hedging flow will push price.

Coverage is 2023-05-18 -> 2023-10-23 only (147 days, 3,501 hourly rows), which
can support an information-coefficient measurement and nothing more. The split
is first half vs second half - the nearest available substitute for an
out-of-sample test on a sample this short.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from scipy.stats import spearmanr

def zs(x, w):
    s = pd.Series(np.asarray(x, float))
    return ((s - s.rolling(w).mean()) / (s.rolling(w).std() + 1e-12)).to_numpy()

if __name__ == "__main__":
    o = pd.read_parquet(str(_P.DATA / "opt_1h.parquet"))
    o["dt"] = pd.to_datetime(o.dt, utc=True).astype("datetime64[ns, UTC]")
    f = pd.read_parquet(str(_P.DATA / "fut_1h.parquet"))
    f["dt"] = pd.to_datetime(f.dt, utc=True).astype("datetime64[ns, UTC]")
    d = o.merge(f[["dt", "close"]], on="dt", how="inner").sort_values("dt").reset_index(drop=True)
    print(f"{len(d)} hourly rows  {d.dt.min()} -> {d.dt.max()}")
    print(f"mean ATM IV {d.atm.mean()*100:.1f}%   mean 25d risk reversal {d.rr25.mean()*100:+.2f} vol pts"
          f"   mean butterfly {d.fly25.mean()*100:+.2f}   mean put/call OI {d.pcoi.mean():.2f}")
    W = 24 * 7
    for c in ("rr25", "fly25", "atm", "pcoi", "gex"):
        d[f"z_{c}"] = zs(d[c].to_numpy(float), W)
        d[f"dz_{c}"] = zs(pd.Series(d[c].to_numpy(float)).diff(24).to_numpy(), W)
    c = d.close.to_numpy(float); n = len(c)
    half = n // 2
    feats = [x for x in d.columns if x.startswith(("z_", "dz_"))]
    hors = [4, 12, 24, 72]
    print(f"\n{'feature':>10} | " + " | ".join(f"{'h='+str(h)+'h':>17}" for h in hors))
    print(f"{'':>10} | " + " | ".join(f"{'1st half':>8}{'2nd':>9}" for _ in hors))
    for ft in feats:
        cells = []
        x = d[ft].to_numpy(float)
        for h in hors:
            fwd = np.full(n, np.nan); fwd[:-h] = c[h:] / c[:-h] - 1.0
            g = np.isfinite(x) & np.isfinite(fwd)
            a1 = spearmanr(x[g & (np.arange(n) < half)], fwd[g & (np.arange(n) < half)])[0]
            a2 = spearmanr(x[g & (np.arange(n) >= half)], fwd[g & (np.arange(n) >= half)])[0]
            cells.append(f"{a1:+8.4f}{a2:+9.4f}")
        print(f"{ft:>10} | " + " | ".join(cells))
    print("\ndecile economics at h=24h, against a 16 bps round turn:")
    h = 24; fwd = np.full(n, np.nan); fwd[:-h] = c[h:] / c[:-h] - 1.0
    for ft in feats:
        x = d[ft].to_numpy(float); g = np.isfinite(x) & np.isfinite(fwd)
        if g.sum() < 200: continue
        q = pd.qcut(pd.Series(x[g]), 10, labels=False, duplicates="drop")
        dm = pd.Series(fwd[g]).groupby(q).mean() * 1e4
        print(f"  {ft:>10}  D1 {dm.iloc[0]:+8.1f}  D10 {dm.iloc[-1]:+8.1f}  "
              f"spread {dm.iloc[-1]-dm.iloc[0]:+8.1f} bps")
