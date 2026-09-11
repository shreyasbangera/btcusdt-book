"""
S38 - Orthogonal sleeve search.

The single most reliable finding of this study, now confirmed three times, is
that a sleeve's CORRELATION to what you already hold matters more than its
standalone quality. S33 showed a book with almost no edge (PF 1.13) at 0.08
correlation beating a strong book at 0.71. S37 showed the weakest standalone
book in the study (IVOL, 15.6% CAGR) being worth +40% of portfolio return at
matched drawdown, purely because it correlates 0.09-0.23 with the rest.

So stop looking for a better signal and look for a DIFFERENT one. Four input
families the study has data for but never built a sleeve from, each reading a
population or a market the existing books do not:

  CMDIV   coin-margined (BTCUSD_PERP) funding minus USDT-perp funding.
          Different collateral, different users - crypto-native holders and
          miners hedging in BTC terms versus stablecoin leverage. The gap
          measures WHICH population is paying to be long.
  TERM    annualised basis of the front quarterly future over the perp.
          Term expectations, not spot flow.
  BREADTH how much of the alt complex is participating, and alt strength
          relative to BTC. Risk appetite in the tail of the market.
  ETHREL  ETH minus BTC return. The single largest cross-asset flow in crypto.

Signs are chosen in-sample and verified out-of-sample; where a sign does not
hold, that is reported rather than flipped.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.runner import zs
import strategies.s32_pair as s32
import strategies.s36_ivmom as s36

FULL_START = "2021-03-01"        # quarterly + CM data both live from here
BV_START   = "2023-06-21"
D = str(_P.DATA)

_P = {}
def xpanel(tf="12h"):
    if tf in _P: return _P[tf]
    fut, f = panel(tf)
    f["dt"] = pd.to_datetime(f.dt, utc=True).astype("datetime64[ns, UTC]")
    idx = f.dt

    def joinres(df, tcol="dt"):
        df[tcol] = pd.to_datetime(df[tcol], utc=True).astype("datetime64[ns, UTC]")
        return df.set_index(tcol).resample(tf).last()

    # --- CMDIV: coin-margined funding vs USDT funding, and CM/USDT price gap
    cmf = joinres(pd.read_parquet(f"{D}/cm_funding.parquet"))["cm_rate"]
    cm = joinres(pd.read_parquet(f"{D}/cm_1h.parquet"))["close"].rename("cm_px")
    f = f.merge(cmf.reset_index(), on="dt", how="left").merge(cm.reset_index(), on="dt", how="left")
    f["cm_rate"] = f.cm_rate.ffill(limit=6)
    f["cm_px"] = f.cm_px.ffill(limit=6)
    f["f_cmdiv"] = zs((f.cm_rate - f.fund).to_numpy(float), 120)
    f["f_cmpx"] = zs(pd.Series(np.log(f.cm_px / f.close)).diff(6).to_numpy(), 120)

    # --- TERM: annualised front-quarterly basis over the perp
    q = pd.read_parquet(f"{D}/quarterly_front.parquet")
    q["dt"] = pd.to_datetime(q.dt, utc=True).astype("datetime64[ns, UTC]")
    q["ann"] = (q.basis / q.perp) * (365.0 / np.maximum(q.dte, 1.0))
    qq = q.set_index("dt")["ann"].resample(tf).last()
    f = f.merge(qq.reset_index(), on="dt", how="left")
    f["ann"] = f.ann.ffill(limit=6)
    f["f_term"] = zs(f.ann.to_numpy(float), 120)
    f["f_dterm"] = zs(pd.Series(f.ann.to_numpy(float)).diff(6).to_numpy(), 120)

    # --- BREADTH: alt participation and alt strength vs BTC
    b = pd.read_parquet(f"{D}/breadth.parquet")
    if not isinstance(b.index, pd.DatetimeIndex): b.index = pd.to_datetime(b.index, utc=True)
    b.index = b.index.tz_convert("UTC") if b.index.tz else b.index.tz_localize("UTC")
    b = b.resample(tf).last()
    b.index.name = "dt"
    f = f.merge(b.reset_index(), on="dt", how="left")
    for c in ("breadth24", "altrel24", "flow_breadth24"):
        f[c] = f[c].ffill(limit=6)
    f["f_breadth"] = zs(f.breadth24.to_numpy(float), 120)
    f["f_altrel"] = zs(f.altrel24.to_numpy(float), 120)
    f["f_flowbr"] = zs(f.flow_breadth24.to_numpy(float), 120)

    # --- ETHREL: ETH minus BTC return
    e = joinres(pd.read_parquet(f"{D}/eth_1h.parquet"))["close"].rename("eth")
    f = f.merge(e.reset_index(), on="dt", how="left")
    f["eth"] = f.eth.ffill(limit=6)
    f["f_ethrel"] = zs((pd.Series(np.log(f.eth)).diff(6)
                        - pd.Series(np.log(f.close)).diff(6)).to_numpy(), 120)
    _P[tf] = f
    return f

FAM = {"cmdiv": "CMDIV", "cmpx": "CMDIV", "term": "TERM", "dterm": "TERM",
       "breadth": "BREADTH", "altrel": "BREADTH", "flowbr": "BREADTH",
       "ethrel": "ETHREL"}

def book(f, col, sign, thr=1.0, stp=3.0, rr=2.0, **kw):
    s = sign * f[col].to_numpy(float)
    a = dict(entry=np.nan_to_num(np.where(s > thr, 1.0, np.where(s < -thr, -1.0, 0.0))),
             stop=stp * f.atr14.to_numpy(), tp=stp * rr * f.atr14.to_numpy(),
             exit=np.zeros(len(f)))
    return a

if __name__ == "__main__":
    f = xpanel("12h")
    f = f[f.dt >= FULL_START].reset_index(drop=True)
    kw = dict(risk=0.02, max_lev=10.0, max_bars_h=7 * 24)
    print(f"panel {len(f)} bars  {f.dt.min().date()} -> {f.dt.max().date()}   IS ends {IS_END}\n")
    print(f"{'feature':>10}{'fam':>9}{'sgn':>5} | {'IS CAGR':>8}{'PF':>6}{'N':>5} | "
          f"{'OOS CAGR':>9}{'PF':>6}{'N':>5} | {'ALL CAGR':>9}{'DD':>7}{'PF':>6}{'Shp':>6}{'N':>5}")
    keep = {}
    for col in [c for c in f.columns if c.startswith("f_")]:
        best = None
        for sign in (1, -1):
            a = book(f, col, sign)
            I = backtest(f, a, "12h", start=FULL_START, end=IS_END, **kw)
            if I["trades"] < 40: continue
            if best is None or I["sharpe"] > best[1]["sharpe"]: best = (sign, I, a)
        if best is None: continue
        sign, I, a = best
        O = backtest(f, a, "12h", start=IS_END, end=OOS_END, **kw)
        A = backtest(f, a, "12h", start=FULL_START, end=OOS_END, **kw)
        nm = col[2:]
        print(f"{nm:>10}{FAM.get(nm,'?'):>9}{sign:>5} | {I['cagr']*100:7.1f}%{I['profit_factor']:6.2f}"
              f"{I['trades']:5d} | {O['cagr']*100:8.1f}%{O['profit_factor']:6.2f}{O['trades']:5d} | "
              f"{A['cagr']*100:8.1f}%{A['max_dd']*100:6.1f}%{A['profit_factor']:6.2f}"
              f"{A['sharpe']:6.2f}{A['trades']:5d}")
        keep[nm] = (sign, a, I, O, A)
    import json, pickle
    pickle.dump({k: (v[0],) for k, v in keep.items()}, open(str(_P.RESULTS / "s38_signs.pkl"), "wb"))
