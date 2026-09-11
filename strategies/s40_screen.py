"""
S40 - Broad orthogonal screen.

Going from 3 sleeves to 6 took the portfolio's Sharpe from 1.36 to 2.13 and its
Calmar from 2.09 to 4.5, entirely through decorrelation. So the productive
question is no longer "what is the best signal" but "what else is different".

Every feature in the extended panel is turned into the SAME standard book -
12h decision, 15m execution, 1.0 z threshold, 3 ATR stop, 2R target, 7-day cap -
so nothing is tuned per feature. The sign is chosen in-sample. Then each
candidate's daily returns are correlated against the incumbent 6-sleeve
portfolio, and the marginal contribution measured.

MULTIPLE-TESTING WARNING, stated before the results: roughly 100 features x
2 signs are screened here. At a 5% false-positive rate that is ~10 candidates
that will look good in-sample by chance alone. In-sample rank is therefore
used only to order the queue; the ONLY thing that counts as evidence is
out-of-sample profit factor on a period the screen never saw.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
import strategies.s38_orth as s38
import strategies.s39_five as s39
import strategies.s32_pair as s32

START = "2021-03-01"
SKIP = {"dt", "open", "high", "low", "close", "volume", "quote_volume", "atr14",
        "ema_f", "ema_s", "dc55_hi", "dc55_lo", "oi", "oi_px", "cm_px", "eth",
        "ann", "cm_rate", "count", "taker_buy_base", "taker_buy_quote"}

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

if __name__ == "__main__":
    f = s38.xpanel("12h")
    f = f[f.dt >= START].reset_index(drop=True)
    kw = dict(risk=0.02, max_lev=10.0, max_bars_h=7 * 24)

    # incumbent book, for the correlation column
    inc = s39.clip(s39.sleeves(1, START, OOS_END,
                   ("FLOW", "POSN", "CONVEX", "CMPX", "ETHREL")), START, OOS_END)
    W = s39.weights(("FLOW", "POSN", "CONVEX", "CMPX", "ETHREL"), START)
    base = s32.combine(inc, W)
    bret = pd.Series(base["equity"], index=base["index"]).pct_change().fillna(0.0)

    cands = [c for c in f.columns if c not in SKIP and f[c].dtype.kind == "f"]
    print(f"screening {len(cands)} features x 2 signs on {len(f)} bars, "
          f"IS {START}..{IS_END}, OOS {IS_END}..{OOS_END}\n")
    rows = []
    for col in cands:
        x = f[col].to_numpy(float)
        if not np.isfinite(x).sum() > 500: continue
        sd = np.nanstd(x)
        if sd < 1e-12: continue
        z = (x - np.nanmean(x)) / sd if abs(np.nanmean(x)) > 3 * sd or sd > 5 else x
        best = None
        for sign in (1, -1):
            s = sign * z
            a = dict(entry=np.nan_to_num(np.where(s > 1.0, 1.0, np.where(s < -1.0, -1.0, 0.0))),
                     stop=3.0 * f.atr14.to_numpy(), tp=6.0 * f.atr14.to_numpy(),
                     exit=np.zeros(len(f)))
            I = backtest(f, a, "12h", start=START, end=IS_END, **kw)
            if I["trades"] < 60: continue
            if best is None or I["sharpe"] > best[1]["sharpe"]: best = (sign, I, a)
        if best is None: continue
        sign, I, a = best
        O = backtest(f, a, "12h", start=IS_END, end=OOS_END, **kw)
        A = backtest(f, a, "12h", start=START, end=OOS_END, **kw)
        if O["trades"] < 40: continue
        r = daily(A).reindex(bret.index).fillna(0.0)
        corr = float(np.corrcoef(r, bret)[0, 1])
        rows.append(dict(feat=col, sign=sign, is_cagr=I["cagr"], is_pf=I["profit_factor"],
                         oos_cagr=O["cagr"], oos_pf=O["profit_factor"], oos_n=O["trades"],
                         cagr=A["cagr"], dd=A["max_dd"], pf=A["profit_factor"],
                         shp=A["sharpe"], n=A["trades"], corr=corr))
    df = pd.DataFrame(rows)
    df.to_parquet(str(_P.RESULTS / "s40_screen.parquet"), index=False)
    surv = df[(df.oos_pf > 1.10) & (df.is_pf > 1.05) & (df["corr"] < 0.45)].sort_values("shp", ascending=False)
    print(f"{len(df)} candidates completed; {len(surv)} pass OOS PF>1.10, IS PF>1.05, corr<0.45\n")
    print(f"{'feature':>16}{'sgn':>4}{'corr':>7} | {'IS PF':>6}{'IS CAGR':>8} | "
          f"{'OOS PF':>7}{'OOS CAGR':>9}{'N':>5} | {'ALL CAGR':>9}{'DD':>7}{'PF':>6}{'Shp':>6}{'N':>5}")
    for _, r in surv.head(30).iterrows():
        print(f"{r.feat:>16}{int(r['sign']):>4}{r['corr']:>7.2f} | {r.is_pf:6.2f}{r.is_cagr*100:7.1f}% | "
              f"{r.oos_pf:7.2f}{r.oos_cagr*100:8.1f}%{int(r.oos_n):5d} | "
              f"{r.cagr*100:8.1f}%{r.dd*100:6.1f}%{r.pf:6.2f}{r.shp:6.2f}{int(r.n):5d}")
