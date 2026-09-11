"""Strategy harness: builds signals on a decision timeframe, executes on 15m,
reports IS / OOS / full-period results, and appends to the results store."""
import sys, os, json, numpy as np, pandas as pd
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
from engine.data import load, agg, align_to_exec
from engine.core import Engine, fmt
from research.features import build, add_basis, add_funding, add_metrics

IS_START = "2020-01-01"
IS_END   = "2024-07-01"     # in-sample  : 2020-01-01 .. 2024-06-30  (4.50y)
OOS_END  = "2026-09-01"     # out-of-sample: 2024-07-01 .. 2026-08-31 (2.17y)

_cache = {}

def panel(tf="1h"):
    """Decision-timeframe feature panel (perp) + basis + funding + OFI residuals."""
    if tf in _cache: return _cache[tf]
    fut5 = load("fut_5m"); spot5 = load("spot_15m")
    fut = load("fut_1h") if tf == "1h" else agg(fut5, tf)
    spot = load("spot_1h") if tf == "1h" else agg(spot5, tf)
    f = build(fut)
    f = add_basis(f, fut, spot)
    f = add_funding(f, load("funding"))
    try:
        f = add_metrics(f, pd.read_parquet(str(_P.DATA / "metrics_1h.parquet")))
    except FileNotFoundError:
        pass
    # Order flow orthogonalised to past returns (EFMA 2025 construction).
    # The projection coefficients are estimated on an EXPANDING window and are
    # refreshed periodically, so the residual at bar t never uses future data.
    ctrl = np.column_stack([f[f"mom{k}"].to_numpy(float) for k in (1, 2, 4, 6, 12, 24)])
    bars_per_month = max(1, int(720 / (pd.Series(f.dt).diff().median().total_seconds() / 3600)))
    warm = bars_per_month * 6
    for n in (6, 24, 96):
        x = f[f"ofi{n}"].to_numpy(float)
        good = np.isfinite(x) & np.isfinite(ctrl).all(1)
        b = np.full(len(x), np.nan)
        coef = None
        for i0 in range(warm, len(x), bars_per_month):
            hist = good.copy(); hist[i0:] = False          # strictly past
            if hist.sum() > 200:
                A = np.column_stack([np.ones(hist.sum()), ctrl[hist]])
                coef = np.linalg.lstsq(A, x[hist], rcond=None)[0]
            if coef is None:
                continue
            j1 = min(i0 + bars_per_month, len(x))
            sl = slice(i0, j1)
            gm = good[sl]
            Ax = np.column_stack([np.ones(gm.sum()), ctrl[sl][gm]])
            seg = np.full(j1 - i0, np.nan)
            seg[gm] = x[sl][gm] - Ax @ coef
            b[sl] = seg
        f[f"ofi{n}_res"] = b
        f[f"ofi{n}_resz"] = pd.Series(b).rolling(bars_per_month * 4).apply(
            lambda v: (v[-1] - v.mean()) / (v.std() + 1e-12), raw=True).to_numpy()
    _cache[tf] = (fut, f)
    return _cache[tf]

EXEC_TF = ["fut_15m"]          # execution grid; swap to "fut_1m" for finer stop resolution

def exec_grid():
    return load(EXEC_TF[0])

def slice_period(df, start=None, end=None):
    m = np.ones(len(df), bool)
    if start: m &= (df.dt >= start).to_numpy()
    if end:   m &= (df.dt <  end).to_numpy()
    return df[m].reset_index(drop=True), m

_ctxc = {}

def _ctx(start, end, fee, slip, eq0, max_lev, sig_df, exec_df=None, exec_key=None,
         funding_df=None):
    """Cache the sliced execution grid, the Engine (funding array) and the
    first-bar-of-decision-bar mask; these depend only on the period + costs.

    `exec_df` supplies the execution bars for instruments other than BTCUSDT.
    Without it every backtest executed against the BTCUSDT grid regardless of
    which instrument's signals it was given - silently, and catastrophically
    for anything else.
    """
    tfd = pd.Series(sig_df.dt).diff().median()
    key = (start, end, fee, slip, eq0, max_lev, str(tfd),
           exec_key or EXEC_TF[0])
    if key not in _ctxc:
        ex_s, _ = slice_period(exec_grid() if exec_df is None else exec_df, start, end)
        eng = Engine(ex_s, fee_bps=fee, slip_bps=slip, eq0=eq0, max_leverage=max_lev,
                     funding_df=funding_df)
        dec_id = ((pd.Series(ex_s.dt) - pd.Series(sig_df.dt).iloc[0]) // tfd).to_numpy()
        first = np.r_[True, np.diff(dec_id) != 0]
        _ctxc[key] = (ex_s, eng, first)
    return _ctxc[key]

def backtest(sig_df, arrays, tf, period=("all"), risk=0.01, max_lev=5.0,
             fee=5.0, slip=3.0, be_r=0.0, trail_after_r=0.0, max_bars_h=0,
             start=None, end=None, eq0=10_000.0,
             dd_soft=1.0, dd_hard=1.0, dd_floor=0.0, pyramid=0, pyramid_step=1.0,
             exec_df=None, exec_key=None, funding_df=None, add_mult=0.0, add_max=0, add_mode=0):
    """
    arrays: dict with keys 'entry','exit','stop','tp','trail' on the DECISION grid.
    Values from decision bar t become active at the open of decision bar t+1.
    """
    ex_s, eng, first = _ctx(start, end, fee, slip, eq0, max_lev, sig_df,
                            exec_df=exec_df, exec_key=exec_key, funding_df=funding_df)
    al = align_to_exec(sig_df, ex_s, arrays, lag=1)
    entry = np.nan_to_num(al["entry"]) * first
    bar_h = pd.Series(ex_s.dt).diff().median().total_seconds() / 3600.0
    return eng.run(entry,
                   exit_flag=np.nan_to_num(al.get("exit", np.zeros(len(ex_s)))),
                   stop_dist=al.get("stop"), tp_dist=al.get("tp"),
                   trail_dist=al.get("trail"),
                   risk=risk, be_r=be_r, trail_after_r=trail_after_r,
                   max_bars=int(max_bars_h / bar_h) if max_bars_h else 0,
                   dd_soft=dd_soft, dd_hard=dd_hard, dd_floor=dd_floor,
                   pyramid=pyramid, pyramid_step=pyramid_step,
                   add_signal=(np.nan_to_num(al["add"]) * first
                               if "add" in al else None),
                   add_mult=add_mult, add_max=add_max, add_mode=add_mode)

def report(name, sig_df, arrays, tf, **kw):
    out = {}
    for lab, s, e in [("IS ", IS_START, IS_END), ("OOS", IS_END, OOS_END), ("ALL", IS_START, OOS_END)]:
        out[lab.strip()] = backtest(sig_df, arrays, tf, start=s, end=e, **kw)
    print(f"### {name}")
    for lab in ("IS", "OOS", "ALL"):
        m = out[lab]
        print(f"  {lab:<4} CAGR {m['cagr']*100:9.1f}% | DD {m['max_dd']*100:6.1f}% | PF {m['profit_factor']:5.2f} | "
              f"N {m['trades']:5d} | WR {m['win_rate']*100:4.1f}% | Shp {m['sharpe']:5.2f} | "
              f"Clm {m['calmar']:6.2f} | Exp {m['exposure']*100:4.1f}%")
    y = out["ALL"]["yearly"]
    print("       yearly:", " ".join(f"{k}:{v*100:+.0f}%" for k, v in y.items()))
    return out

def qualifies(m):
    return (m["cagr"] > 3.0 and m["trades"] >= 100 and
            m["profit_factor"] > 1.10 and m["max_dd"] > -0.20)
