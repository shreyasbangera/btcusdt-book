"""
S17 - Meta-Labelled Convex Trend (MLCT)   [BTCUSDT perp, single strategy]

Lopez de Prado's meta-labelling: keep the primary signal exactly as it is, and
train a SECOND model whose only job is to predict whether a given primary signal
will win. The secondary model never chooses direction - it chooses whether to
take the trade and, optionally, how large. That is a much easier learning problem
than predicting returns, which is why the direct return-forecasting attempt (S6)
failed while this can work.

Protocol
  * primary   : the S15 convex entry (positioning composite + trend agreement)
  * label     : did that trade close positive, from the actual simulator
  * features  : the full panel as of the decision bar
  * model     : LightGBM classifier, expanding window, refit every 3 months,
                with a purge gap equal to the maximum holding period so no
                training label overlaps the block being predicted
  * execution : take the trade only when P(win) exceeds a threshold chosen on
                in-sample data
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd, lightgbm as lgb
from research.harness import panel, backtest, IS_START, IS_END, OOS_END
import strategies.s07_smart as s07
import strategies.s15_convex as s15

DROP = {"dt", "close", "ema_f", "ema_s", "atr14", "dc55_hi", "dc55_lo", "oi", "oi_px"}
MAXHOLD_BARS = 60          # purge gap, in 4h decision bars

def trade_labels(f, comp, **kw):
    """Run the primary strategy once and label every entry by its realised P&L."""
    a = s15.arrays(f, comp=comp, **kw)
    m = backtest(f, a, "4h", start="2021-01-03", end=OOS_END,
                 risk=0.02, max_lev=10.0, trail_after_r=1.0)
    tr = m["trades_df"]
    if not len(tr):
        return None
    # map each trade's entry timestamp back to its decision bar
    fdt = pd.to_datetime(f.dt).to_numpy()
    ent = pd.to_datetime(tr.entry_dt).to_numpy()
    idx = np.searchsorted(fdt, ent, side="right") - 1
    lab = pd.DataFrame({"bar": idx, "win": (tr.pnl.to_numpy() > 0).astype(int),
                        "side": tr.side.to_numpy()})
    return lab.drop_duplicates("bar").set_index("bar")

def walk_forward_proba(f, lab, refit=540, warm=1800, seed=0):
    cols = [c for c in f.columns if c not in DROP]
    X = f[cols].to_numpy(np.float32)
    y = np.full(len(f), np.nan)
    y[lab.index.to_numpy()] = lab.win.to_numpy()
    has = np.isfinite(y) & np.isfinite(X).all(1)
    proba = np.full(len(f), np.nan)
    for t0 in range(warm, len(f), refit):
        tr = has.copy()
        tr[max(0, t0 - MAXHOLD_BARS):] = False        # purge overlapping labels
        if tr.sum() < 120 or len(np.unique(y[tr])) < 2:
            continue
        mdl = lgb.LGBMClassifier(n_estimators=220, learning_rate=0.035, num_leaves=7,
                                 min_child_samples=30, subsample=0.85, subsample_freq=1,
                                 colsample_bytree=0.6, reg_lambda=8.0,
                                 random_state=seed, verbose=-1)
        mdl.fit(X[tr], y[tr])
        t1 = min(t0 + refit, len(f))
        seg = np.isfinite(X[t0:t1]).all(1)
        p = np.full(t1 - t0, np.nan)
        if seg.any():
            p[seg] = mdl.predict_proba(X[t0:t1][seg])[:, 1]
        proba[t0:t1] = p
    return proba

if __name__ == "__main__":
    fut, f = panel("4h")
    f = f[f.dt >= "2021-01-03"].reset_index(drop=True)
    comp = s07.composite(f)
    base = dict(trail_atr=3.0, stop_atr=2.5)
    lab = trade_labels(f, comp, **base)
    print(f"primary trades labelled: {len(lab)}  base win rate {lab.win.mean()*100:.1f}%")

    proba = walk_forward_proba(f, lab)
    got = np.isfinite(proba) & np.isfinite(pd.Series(np.nan, index=f.index).to_numpy(), where=True)
    print(f"walk-forward probabilities produced for {np.isfinite(proba).sum()} bars")

    # discrimination check on the labelled subset
    li = lab.index.to_numpy()
    ok = np.isfinite(proba[li])
    if ok.sum() > 40:
        from scipy import stats
        pv = proba[li][ok]; wv = lab.win.to_numpy()[ok]
        dt = pd.to_datetime(f.dt).to_numpy()[li][ok]
        for tag, msk in (("in-sample ", dt < np.datetime64(IS_END)),
                         ("out-sample", dt >= np.datetime64(IS_END))):
            if msk.sum() < 20: continue
            hi = pv[msk] > np.median(pv[msk])
            print(f"  {tag}: n={msk.sum():4d}  win rate low-P {wv[msk][~hi].mean()*100:5.1f}%  "
                  f"high-P {wv[msk][hi].mean()*100:5.1f}%  "
                  f"AUC-ish gap {(wv[msk][hi].mean()-wv[msk][~hi].mean())*100:+5.1f}pp")

    print(f"\n{'threshold':<12}{'risk':>6}{'pyr':>5}{'CAGR':>9}{'DD':>8}{'PF':>6}{'N':>6}{'WR':>6}"
          f"{'Shp':>6}{'Clm':>7}   {'OOS CAGR':>9}{'OOS DD':>8}{'OOS PF':>7}")
    a0 = s15.arrays(f, comp=comp, **base)
    for thr in (0.0, 0.45, 0.52, 0.58, 0.64):
        gate = np.where(np.isfinite(proba), (proba >= thr).astype(float), 0.0) if thr > 0 else 1.0
        ent = a0["entry"] * gate
        for risk, pyr in ((0.03, 3), (0.06, 3), (0.10, 4)):
            a = dict(a0); a["entry"] = ent
            kw = dict(risk=risk, max_lev=10.0, trail_after_r=1.0, pyramid=pyr, pyramid_step=1.0)
            al = backtest(f, a, "4h", start="2021-01-03", end=OOS_END, **kw)
            o = backtest(f, a, "4h", start=IS_END, end=OOS_END, **kw)
            if al["trades"] < 40: continue
            print(f"P>={thr:<9.2f}{int(risk*100):>5}%{pyr:>5}{al['cagr']*100:8.1f}%{al['max_dd']*100:7.1f}%"
                  f"{al['profit_factor']:6.2f}{al['trades']:6d}{al['win_rate']*100:5.1f}%"
                  f"{al['sharpe']:6.2f}{al['calmar']:7.2f}   {o['cagr']*100:8.1f}%{o['max_dd']*100:7.1f}%"
                  f"{o['profit_factor']:7.2f}")
