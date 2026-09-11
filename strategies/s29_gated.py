"""
S29 - Conditionally Gated Positioning (CGP)   [BTCUSDT perp only]

Two separate results point the same way. Equal-weight AVERAGING of signals
diluted the strongest one, twice (S2: PF 1.30 -> 1.19; S28 breadth blend: IC
0.108 -> 0.070). But CONDITIONAL GATING - requiring a second, weakly-correlated
signal to agree before taking the primary's trade - worked in S1, lifting PF
from 1.04 to 1.30.

Averaging moves the primary signal toward the weaker one. Gating leaves the
primary untouched and only removes trades the confirmer disputes. This applies
gating to the strongest signal in the study, using the market-wide flow breadth
built from 15 alt perps as the confirmer (correlation with the primary: 0.22).
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.runner import evaluate, line
from engine.indicators import zscore
import strategies.s07_smart as s07

START = "2021-01-03"

def confirmer(f, col="flow_breadth96"):
    F = pd.read_parquet(str(_P.DATA / "breadth.parquet"))
    F = F.reindex(pd.to_datetime(f.dt)).reset_index(drop=True)
    return zscore(F[col].to_numpy(float), 480)

def arrays(f, comp, conf, thr=0.7, gate=0.0, mode="agree", atr_stop=3.5, rr=2.5):
    a = f.atr14.to_numpy()
    lng = comp > thr
    sht = comp < -thr
    if mode == "agree":            # confirmer must not oppose
        lng = lng & (conf > -gate)
        sht = sht & (conf < gate)
    elif mode == "strict":         # confirmer must actively agree
        lng = lng & (conf > gate)
        sht = sht & (conf < -gate)
    elif mode == "veto":           # only veto when the confirmer strongly opposes
        lng = lng & ~(conf < -gate)
        sht = sht & ~(conf > gate)
    e = np.where(np.nan_to_num(lng), 1.0, np.where(np.nan_to_num(sht), -1.0, 0.0))
    return dict(entry=e, stop=atr_stop * a, tp=atr_stop * rr * a, exit=np.zeros(len(f)))

if __name__ == "__main__":
    fut, f = panel("4h")
    f = f[f.dt >= START].reset_index(drop=True)
    comp = s07.composite(f); conf = confirmer(f)
    print("S29 Conditionally Gated Positioning — BTCUSDT perp, 4h / 15m")
    print(f"{'variant':<32}{'CAGR':>9}{'DD':>8}{'PF':>6}{'N':>6}{'WR':>6}{'Shp':>6}{'Clm':>7}"
          f"   {'IS':>8}{'OOS':>8}{'OOSPF':>7}")
    base = s07.arrays(f, comp, thr=0.7, atr_stop=3.5, rr=2.5)
    r = evaluate("x", f, base, "4h", verbose=False, risk=0.025, max_lev=10.0,
                 max_bars_h=10*24, since=START)
    m = r["ALL"]
    print(f"{'UNGATED baseline':<32}{m['cagr']*100:8.1f}%{m['max_dd']*100:7.1f}%{m['profit_factor']:6.2f}"
          f"{m['trades']:6d}{m['win_rate']*100:5.1f}%{m['sharpe']:6.2f}{m['calmar']:7.2f}"
          f"   {r['IS']['cagr']*100:7.1f}%{r['OOS']['cagr']*100:7.1f}%{r['OOS']['profit_factor']:7.2f}")
    for mode in ("agree", "strict", "veto"):
        for gate in (0.0, 0.3, 0.6, 1.0):
            if mode == "agree" and gate == 0.0 and False: continue
            a = arrays(f, comp, conf, thr=0.7, gate=gate, mode=mode)
            r = evaluate("x", f, a, "4h", verbose=False, risk=0.025, max_lev=10.0,
                         max_bars_h=10*24, since=START)
            m = r["ALL"]
            if m["trades"] < 80: continue
            print(f"{'gate '+mode+' '+str(gate):<32}{m['cagr']*100:8.1f}%{m['max_dd']*100:7.1f}%"
                  f"{m['profit_factor']:6.2f}{m['trades']:6d}{m['win_rate']*100:5.1f}%{m['sharpe']:6.2f}"
                  f"{m['calmar']:7.2f}   {r['IS']['cagr']*100:7.1f}%{r['OOS']['cagr']*100:7.1f}%"
                  f"{r['OOS']['profit_factor']:7.2f}")
