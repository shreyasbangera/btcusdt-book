"""
S64 - Learning the combination instead of assuming it.

Every version of this book has combined the five signals by ADDING them, then
raising the sum to a power. That is one functional form out of infinitely many,
and it cannot express interactions: it has no way to say "flow only matters when
funding is not already stretched", or "dominance and positioning agreeing is
worth more than the sum of the two".

A gradient-boosted tree on the five signal values can express those. Five
inputs and ~4,000 rows is a small enough problem that overfitting is
controllable, and the guard rails are the ones this study already uses:

  PURGED WALK-FORWARD  train on the trailing 24 months, predict the next 3, and
                       purge the 2 bars either side of the boundary so the
                       forward-return label of a training row can never overlap
                       a test row.
  SHALLOW TREES        depth 3, 200 leaves-worth of capacity at most, heavy
                       regularisation - the point is interactions, not memory.
  SAME EXECUTION       the model's output is mapped to a position exactly as
                       the net signal was, and traded through the same engine
                       with the same stop, target, flat-exit and costs.

Controls: the linear book, and the identical pipeline trained on SHUFFLED
labels, which is what this machinery scores when there is nothing to learn.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, OOS_END
from research.robust import bootstrap_dd
import strategies.s45_single as S
import strategies.s46_net as S46

try:
    from lightgbm import LGBMRegressor
    HAVE_LGB = True
except Exception:
    from sklearn.ensemble import GradientBoostingRegressor
    HAVE_LGB = False

LOOK, STEP, PURGE = 24, 3, 2
HZ = 2          # forward horizon in 12h bars = 1 day

def model():
    if HAVE_LGB:
        return LGBMRegressor(n_estimators=250, max_depth=3, num_leaves=8,
                             learning_rate=0.03, subsample=0.7, subsample_freq=1,
                             colsample_bytree=0.8, reg_lambda=5.0, min_child_samples=40,
                             verbose=-1)
    return GradientBoostingRegressor(n_estimators=250, max_depth=3, learning_rate=0.03,
                                     subsample=0.7, min_samples_leaf=40)

def data():
    g = S.grid(S.FULL_START)
    X = np.column_stack([g[f"s_{n}"].to_numpy(float) for n in S46.LONG])
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    c = g.close.to_numpy(float)
    y = np.full(len(c), np.nan); y[:-HZ] = c[HZ:] / c[:-HZ] - 1.0
    return g, X, y

def predict_forward(g, X, y, shuffle=False, seed=0):
    """Purged walk-forward predictions; every row predicted by a model that saw only its past."""
    dts = pd.to_datetime(g.dt.to_numpy())
    pred = np.full(len(X), np.nan)
    rng = np.random.default_rng(seed)
    t0 = dts[0]; t = t0 + pd.DateOffset(months=LOOK)
    end = dts[-1]
    while t < end:
        te = min(t + pd.DateOffset(months=STEP), end)
        tr = (dts >= t - pd.DateOffset(months=LOOK)) & (dts < t)
        te_m = (dts >= t) & (dts < te)
        # purge: drop training rows whose label window reaches into the test block
        idx = np.where(tr)[0]
        if len(idx): tr[idx[-PURGE:]] = False
        ok = tr & np.isfinite(y)
        if ok.sum() > 300:
            yy = y[ok].copy()
            if shuffle: rng.shuffle(yy)
            m = model(); m.fit(X[ok], yy)
            pred[te_m] = m.predict(X[te_m])
        t = te
    return pred

def to_position(pred, g, thr_q=0.55, cap=3.0):
    """Map predictions to a position with the same shape the net signal uses."""
    p = pd.Series(pred)
    # standardise on a trailing window so the scale is causal
    z = ((p - p.rolling(240, min_periods=60).mean())
         / (p.rolling(240, min_periods=60).std() + 1e-12)).to_numpy()
    z = np.nan_to_num(z)
    e = np.where(z > 1.0, 1.0, np.where(z < -1.0, -1.0, 0.0))
    return np.nan_to_num(e * np.clip(np.abs(z), 1.0, cap))

def run(g, v, risk, start=None, end=OOS_END, hold=14, stp=3.0, rr=2.0):
    a = g.atr14.to_numpy(float)
    arr = dict(entry=np.nan_to_num(v), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(v)) <= 0.0).astype(float))
    return backtest(g, arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24)

def stats(tag, g, v, risk, start):
    A = run(g, v, risk, start=start)
    r = pd.Series(A["equity"], index=pd.to_datetime(A["dt"])).resample("1D").last(
        ).dropna().pct_change().fillna(0).to_numpy()
    b = bootstrap_dd(r, n=2500)
    print(f"{tag:>28}{risk*100:5.0f}% | {A['cagr']*100:7.1f}%{A['max_dd']*100:7.1f}%"
          f"{A['profit_factor']:6.2f}{A['trades']:6d}{A['sharpe']:6.2f}{A['calmar']:6.2f} | "
          f"{b['dd_median']*100:6.1f}%{b['p_dd_worse_than_20']*100:5.0f}%")
    return A

if __name__ == "__main__":
    print("learner:", "lightgbm" if HAVE_LGB else "sklearn GradientBoosting")
    g, X, y = data()
    start = str((pd.to_datetime(g.dt.iloc[0]) + pd.DateOffset(months=LOOK)).date())
    print(f"purged walk-forward from {start}, {LOOK}m train / {STEP}m test, purge {PURGE} bars\n")
    print(f"{'variant':>28}{'risk':>6} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>6}{'Shp':>6}{'Clm':>6}"
          f" | {'medDD':>7}{'P>20%':>5}")
    pr = predict_forward(g, X, y)
    for risk in (0.06, 0.08, 0.10):
        stats("LEARNED combiner", g, to_position(pr, g), risk, start)
    lin = S.composite(g, S46.LONG)
    for risk in (0.06, 0.08):
        stats("LINEAR sum (control)", g, lin, risk, start)
    for sd in (0, 1):
        ps = predict_forward(g, X, y, shuffle=True, seed=sd)
        stats(f"SHUFFLED labels seed {sd}", g, to_position(ps, g), 0.08, start)
