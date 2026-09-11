"""
Does top-of-book imbalance predict BTCUSDT perp returns, and by enough to trade?

bookTicker daily files exist only for roughly 2023-06 .. early 2024, entirely
inside this study's in-sample window, so a true out-of-sample test is impossible.
Instead the 24 sampled days fall in four separate month-blocks; IC is measured on
the first two blocks and validated on the last two, which is the best available
approximation of the stability screen used everywhere else.

Economic significance is judged the same way as every other signal here: the
top-decile forward move against a 16 bps round turn.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from scipy import stats
from engine.data import load
pd.set_option("display.width", 210)

bk = pd.read_parquet(str(_P.DATA / "book_1m.parquet"))
bk["dt"] = pd.to_datetime(bk.dt, utc=True)
k1 = load("fut_1m")[["dt", "close", "volume", "taker_buy_base"]]
k1["dt"] = pd.to_datetime(k1.dt, utc=True)
m = bk.merge(k1, on="dt", how="inner").sort_values("dt").reset_index(drop=True)
m["kline_imb"] = np.where(m.volume > 0,
                          2 * (m.taker_buy_base / m.volume.replace(0, np.nan) - 0.5), np.nan)
m["blk"] = (m.dt.diff().dt.total_seconds().fillna(60) > 3 * 86400).cumsum()
nblk = m.blk.nunique()
print(f"minutes: {len(m)}   blocks: {nblk}   {m.dt.iloc[0]:%Y-%m-%d} -> {m.dt.iloc[-1]:%Y-%m-%d}")
print(f"mean spread {m.spread_bps.mean():.3f} bps   mean top-of-book depth "
      f"${m.depth_usd.mean():,.0f}   quotes/min {m.n_quotes.mean():,.0f}")

c = m.close.to_numpy()
def fwd(h):
    f = (np.log(pd.Series(c).shift(-h)) - np.log(pd.Series(c))).to_numpy()
    same = (m.blk.shift(-h) == m.blk).to_numpy()
    return np.where(same, f, np.nan)

early = m.blk.isin(sorted(m.blk.unique())[:nblk // 2]).to_numpy()
late = ~early
FEATS = ["obi", "obi_last", "obi_vol", "micro_dev", "spread_bps", "depth_usd",
         "n_quotes", "kline_imb"]
print(f"\n{'feature':<14}" + "".join(f"{'E h='+str(h):>10}{'L h='+str(h):>10}" for h in (1, 5, 15, 60)))
for col in FEATS:
    x = m[col].to_numpy(float); row = f"{col:<14}"
    for h in (1, 5, 15, 60):
        y = fwd(h)
        me = np.isfinite(x) & np.isfinite(y) & early
        ml = np.isfinite(x) & np.isfinite(y) & late
        re_, _ = stats.spearmanr(x[me], y[me]) if me.sum() > 500 else (np.nan, 1)
        rl, _ = stats.spearmanr(x[ml], y[ml]) if ml.sum() > 500 else (np.nan, 1)
        row += f"{re_:+10.4f}{rl:+10.4f}"
    print(row)
print("  (E = first two month-blocks, L = last two)")

print("\n=== economic significance: top/bottom decile forward move vs a 16 bps round turn ===")
COST = 16.0
for col in ["obi", "micro_dev"]:
    x = m[col].to_numpy(float)
    for h in (1, 5, 15, 60):
        y = fwd(h); msk = np.isfinite(x) & np.isfinite(y)
        b = pd.qcut(pd.Series(x[msk]), 10, labels=False, duplicates="drop")
        g = pd.DataFrame({"b": b, "y": y[msk]}).groupby("b").y.agg(["mean", "count", "std"])
        g["bps"] = g["mean"] * 1e4
        g["t"] = g["mean"] / (g["std"] / np.sqrt(g["count"]))
        lo, hi = g.index.min(), g.index.max()
        print(f"  {col:<10} h={h:3d}m | D1 {g.loc[lo,'bps']:+7.2f}(t{g.loc[lo,'t']:+5.1f}) "
              f"D10 {g.loc[hi,'bps']:+7.2f}(t{g.loc[hi,'t']:+5.1f}) | spread "
              f"{g.loc[hi,'bps']-g.loc[lo,'bps']:+7.2f}bps vs {COST} cost")
