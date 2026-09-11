"""
S6 - Walk-Forward Gradient-Boosted Ensemble (WFGB)

Instead of hand-crafting one rule, let a gradient-boosted tree combine the whole
feature panel (price structure, order flow, basis, funding, volatility regime,
calendar).  Strict walk-forward:

  * expanding training window, refit every `refit` bars
  * a PURGE GAP of `h` bars between the end of training and the start of the
    test block, because the label at bar t spans t..t+h and would otherwise
    overlap the test period (Lopez de Prado purging)
  * every prediction is therefore made by a model that never saw any bar whose
    label extends into the predicted period.

The label is the h-bar forward return divided by current ATR (vol-normalised),
which stops high-volatility regimes from dominating the fit.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats
from research.harness import panel, IS_END

DROP = {"dt", "close", "ema_f", "ema_s", "atr14", "dc55_hi", "dc55_lo"}

def walk_forward(f, h=6, refit=180, warm=3000, seed=0, n_est=300, lr=0.03,
                 leaves=15, min_leaf=200, feat_frac=0.7):
    cols = [c for c in f.columns if c not in DROP]
    X = f[cols].to_numpy(np.float32)
    c = f.close.to_numpy()
    atrp = (f.atr14.to_numpy() / c)
    fwd = (np.log(pd.Series(c).shift(-h)) - np.log(pd.Series(c))).to_numpy()
    y = fwd / np.maximum(atrp, 1e-6)                    # vol-normalised label
    y = np.clip(y, -6, 6)
    pred = np.full(len(f), np.nan)
    ok = np.isfinite(X).all(1) & np.isfinite(y)
    for t0 in range(warm, len(f), refit):
        tr = ok.copy()
        tr[max(0, t0 - h):] = False                     # purge the overlap
        if tr.sum() < 1000:
            continue
        m = lgb.LGBMRegressor(n_estimators=n_est, learning_rate=lr, num_leaves=leaves,
                              min_child_samples=min_leaf, subsample=0.8, subsample_freq=1,
                              colsample_bytree=feat_frac, reg_lambda=5.0,
                              random_state=seed, verbose=-1)
        m.fit(X[tr], y[tr])
        t1 = min(t0 + refit, len(f))
        seg = np.isfinite(X[t0:t1]).all(1)
        p = np.full(t1 - t0, np.nan)
        if seg.any():
            p[seg] = m.predict(X[t0:t1][seg])
        pred[t0:t1] = p
    return pred, y, cols

if __name__ == "__main__":
    for tf, h in (("4h", 6), ("4h", 12), ("1h", 24)):
        fut, f = panel(tf)
        pred, y, cols = walk_forward(f, h=h)
        c = f.close.to_numpy()
        fwd = (np.log(pd.Series(c).shift(-h)) - np.log(pd.Series(c))).to_numpy()
        m = np.isfinite(pred) & np.isfinite(fwd)
        oos = m & (f.dt >= IS_END).to_numpy()
        ins = m & (f.dt < IS_END).to_numpy()
        print(f"\n=== {tf} h={h} ({h*int(tf[:-1])}h horizon) | walk-forward preds n={m.sum()} ===")
        for lab, mm in (("2020-2024 (early WF)", ins), ("2024-07+ (late WF)", oos), ("all WF", m)):
            if mm.sum() < 300: continue
            rho, p = stats.spearmanr(pred[mm], fwd[mm])
            q = pd.qcut(pd.Series(pred[mm]), 10, labels=False, duplicates="drop")
            g = pd.DataFrame({"q": q, "y": fwd[mm]}).groupby("q").y.mean() * 1e4
            print(f"  {lab:<22} IC {rho:+.4f} (p={p:.1e})  D1 {g.iloc[0]:+8.1f}bps  "
                  f"D10 {g.iloc[-1]:+8.1f}bps  spread {g.iloc[-1]-g.iloc[0]:+8.1f}bps")
        np.save(fstr(_P.RESULTS / "pred_{tf}_{h}.npy"), pred)
