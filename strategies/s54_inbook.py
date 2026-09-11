"""
S54 - Re-screening every candidate the right way.

S40 screened 116 features by building each into its own standalone book and
keeping the ones with a decent profit factor and a low correlation to the
incumbent. S53 showed that screen is invalid for a netted single-position
strategy: the criterion it implements has +0.05 correlation with what actually
happens, and two of the five signals carrying the book - BTC dominance and
funding - have standalone Sharpe of 0.01 and -0.04. They would fail any
standalone screen ever written. Their value is in VETOING other signals'
positions, which only exists inside the book.

So this re-screens the same features the only valid way: add each one to the
five-signal net position, one at a time, and measure what the BOOK does.

Selection discipline: the ranking is computed on IN-SAMPLE marginal Sharpe
alone (to 2024-07-01). Out-of-sample is then reported for the top candidates
and never used to choose them.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import backtest, IS_END, OOS_END
from research.runner import zs
import strategies.s45_single as S
import strategies.s46_net as S46
import strategies.s38_orth as s38

START = S.FULL_START
SKIP = {"dt", "open", "high", "low", "close", "volume", "quote_volume", "atr14", "ema_f",
        "ema_s", "dc55_hi", "dc55_lo", "oi", "oi_px", "cm_px", "eth", "ann", "cm_rate",
        "count", "taker_buy_base", "taker_buy_quote", "posn", "iv_mom"}

def panel():
    g = S.grid(START)
    xf = s38.xpanel("12h")
    add = [c for c in xf.columns if c not in g.columns and c != "dt"]
    return g.merge(xf[["dt"] + add], on="dt", how="left")

def cand_unit(g, col, thr=1.0):
    x = g[col].to_numpy(float)
    sd = np.nanstd(x)
    if not np.isfinite(sd) or sd < 1e-12: return None
    z = x if (abs(np.nanmean(x)) < 3 * sd and sd < 5) else zs(x, 120)
    e = np.where(z > thr, 1.0, np.where(z < -thr, -1.0, 0.0))
    u = np.nan_to_num(e * np.clip(np.abs(z) / thr, 1.0, S.CAP))
    return u if (np.abs(u) > 0).sum() > 200 else None

def run(g, v, start, end, risk=0.08):
    a = g.atr14.to_numpy(float)
    arr = dict(entry=np.nan_to_num(v), stop=3.0 * a, tp=6.0 * a,
               exit=(np.abs(np.nan_to_num(v)) <= 0.0).astype(float))
    return backtest(g, arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=21 * 24)

if __name__ == "__main__":
    g = panel()
    U0 = [S.unit(g, n) for n in S46.LONG]
    base = np.column_stack(U0) @ (np.ones(len(U0)) / len(U0))
    bI = run(g, base, START, IS_END); bA = run(g, base, START, OOS_END)
    bO = run(g, base, IS_END, OOS_END)
    print(f"base book   IS Sharpe {bI['sharpe']:.2f}   ALL {bA['sharpe']:.2f}   OOS {bO['sharpe']:.2f}"
          f"   (CAGR {bA['cagr']*100:.1f}%, DD {bA['max_dd']*100:.1f}%)\n")
    cols = [c for c in g.columns if c not in SKIP and not c.startswith("s_")
            and g[c].dtype.kind == "f"]
    print(f"testing {len(cols)} candidates x 2 signs INSIDE the book, ranked on in-sample only\n")
    rows = []
    for c in cols:
        u = cand_unit(g, c)
        if u is None: continue
        for sign in (1, -1):
            U = U0 + [sign * u]
            v = np.column_stack(U) @ (np.ones(len(U)) / len(U))
            m = run(g, v, START, IS_END)
            if m["trades"] < 150: continue
            rows.append(dict(feat=c, sign=sign, d_is=m["sharpe"] - bI["sharpe"],
                             is_sharpe=m["sharpe"], is_cagr=m["cagr"]))
    df = pd.DataFrame(rows).sort_values("d_is", ascending=False)
    df.to_parquet(str(_P.RESULTS / "s54_inbook.parquet"), index=False)
    print(f"{len(df)} completed.  in-sample marginal Sharpe: best {df.d_is.max():+.3f}, "
          f"median {df.d_is.median():+.3f}, worst {df.d_is.min():+.3f}")
    print(f"{(df.d_is > 0).sum()} of {len(df)} improve the book in sample "
          f"({(df.d_is > 0).mean()*100:.0f}%)\n")
    print(f"{'candidate':>18}{'sgn':>4}{'dIS':>8} | {'ALL CAGR':>9}{'DD':>7}{'PF':>6}{'N':>6}{'Shp':>6}"
          f"{'Clm':>6} | {'OOS CAGR':>9}{'PF':>6}{'Shp':>6}")
    for _, r in df.head(12).iterrows():
        u = cand_unit(g, r.feat)
        U = U0 + [int(r["sign"]) * u]
        v = np.column_stack(U) @ (np.ones(len(U)) / len(U))
        A = run(g, v, START, OOS_END); O = run(g, v, IS_END, OOS_END)
        print(f"{r.feat:>18}{int(r['sign']):>4}{r.d_is:+8.3f} | {A['cagr']*100:8.1f}%"
              f"{A['max_dd']*100:6.1f}%{A['profit_factor']:6.2f}{A['trades']:6d}"
              f"{A['sharpe']:6.2f}{A['calmar']:6.2f} | {O['cagr']*100:8.1f}%"
              f"{O['profit_factor']:6.2f}{O['sharpe']:6.2f}")
    print(f"{'BASE (no addition)':>18}{'':>4}{0.0:+8.3f} | {bA['cagr']*100:8.1f}%"
          f"{bA['max_dd']*100:6.1f}%{bA['profit_factor']:6.2f}{bA['trades']:6d}"
          f"{bA['sharpe']:6.2f}{bA['calmar']:6.2f} | {bO['cagr']*100:8.1f}%"
          f"{bO['profit_factor']:6.2f}{bO['sharpe']:6.2f}")
