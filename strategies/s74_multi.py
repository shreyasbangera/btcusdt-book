"""
S74 - Five instruments in one account.

The correlation ceiling that caps this study at Sharpe ~3 is a SINGLE-INSTRUMENT
limit: every signal available on BTCUSDT is ultimately a view on the same price,
so the average pairwise correlation between them floors around 0.10 and
Sharpe -> s/sqrt(rho) has nowhere further to go.

A cross-section escapes that only if the INSTRUMENTS decorrelate, which is not
obvious in crypto - BTC and ETH returns correlate around 0.85, and if the books
inherit that, five instruments is one instrument with extra fees.  That is the
question this file exists to answer, and it is answerable directly: build the
identical book on each instrument and measure the correlation between the
resulting equity curves.

Per instrument the signals are the ones natively available to it:

  flow    taker-buy imbalance orthogonalised to past returns          all five
  fundz   fade the funding z-score                                    all five
  posn    top-trader vs retail positioning composite                  all five
  cmpx    log(coin-margined / USDT-margined) momentum                 BTC ETH SOL XRP
  btcdom  BTC's share of complex turnover                             BTC only

ZEC has no coin-margined perpetual, so it runs on three signals.  btcdom is a
BTC-specific read and is not transplanted onto the alts - any gain measured here
is therefore from the instruments, not from smuggling a signal across.

One account: each instrument's position is sized off TOTAL account equity with
the risk budget split equally, and margin is shared.  This is five concurrent
positions in one account, not five accounts.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
from research.runner import zs
import strategies.s45_single as S
import strategies.s46_net as S46

D = str(_P.DATA / "multi")
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT", "XRPUSDT"]
HAS_CM = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"}
START = "2022-01-01"          # positioning metrics begin 2021-12
THR = dict(flow=1.0, cmpx=1.0, btcdom=1.0, fundz=1.0, posn=0.7)
CAP = 2.0

def ofi_residual(ofi6, mom, bpm=60, warm=6):
    x = np.asarray(ofi6, float)
    good = np.isfinite(x) & np.isfinite(mom).all(1)
    out = np.full(len(x), np.nan); coef = None
    for i0 in range(bpm * warm, len(x), bpm):
        hist = good.copy(); hist[i0:] = False
        if hist.sum() > 200:
            A = np.column_stack([np.ones(hist.sum()), mom[hist]])
            coef = np.linalg.lstsq(A, x[hist], rcond=None)[0]
        if coef is None: continue
        j1 = min(i0 + bpm, len(x)); sl = slice(i0, j1); gm = good[sl]
        seg = np.full(j1 - i0, np.nan)
        seg[gm] = x[sl][gm] - np.column_stack([np.ones(gm.sum()), mom[sl][gm]]) @ coef
        out[sl] = seg
    return out

def atr14(h, l, c):
    pc = pd.Series(c).shift(1).to_numpy()
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return pd.Series(tr).ewm(alpha=1/14, adjust=False).mean().to_numpy()

_P = {}
def panel(sym):
    if sym in _P: return _P[sym]
    if sym == "BTCUSDT":
        g = S.grid(S.FULL_START)
        g = g[g.dt >= START].reset_index(drop=True)
        _P[sym] = g
        return g
    k = pd.read_parquet(f"{D}/{sym}_12h.parquet")
    k["dt"] = pd.to_datetime(k.dt, utc=True).astype("datetime64[ns, UTC]")
    fu = pd.read_parquet(f"{D}/{sym}_funding.parquet")
    fu["dt"] = pd.to_datetime(fu.dt, utc=True).astype("datetime64[ns, UTC]")
    me = pd.read_parquet(f"{D}/{sym}_metrics.parquet")
    me["dt"] = pd.to_datetime(me.dt, utc=True).astype("datetime64[ns, UTC]")
    me4 = me.set_index("dt").resample("4h").last()
    g = k.copy()
    # funding: most recent strictly-past settlement
    i = np.searchsorted(fu.dt.to_numpy(), g.dt.to_numpy(), side="right") - 1
    g["fund"] = np.where(i >= 0, fu.rate.to_numpy()[np.maximum(i, 0)], np.nan)
    # positioning composite on 4h, sampled to 12h (as in the BTC book)
    tt = me4.tt_pos.to_numpy(float); ta = me4.tt_acct.to_numpy(float)
    rt = me4.retail_acct.to_numpy(float)
    parts = np.column_stack([
        np.clip(zs(np.log(tt / np.maximum(rt, 1e-6)), 480), -3, 3),
        -np.clip(zs(rt, 480), -3, 3), -np.clip(zs(ta, 480), -3, 3)])
    comp = pd.Series(np.nansum(parts, axis=1) / 3.0, index=me4.index).resample("12h").last()
    g["posn"] = comp.reindex(g.dt).to_numpy()
    if sym in HAS_CM:
        cm = pd.read_parquet(f"{D}/{sym}_cm.parquet")
        cm["dt"] = pd.to_datetime(cm.dt, utc=True).astype("datetime64[ns, UTC]")
        g["cm_px"] = cm.set_index("dt")["close"].reindex(g.dt).ffill(limit=2).to_numpy()
    c = g.close.to_numpy(float)
    imb = (2 * g.taker_buy_base.to_numpy(float) - g.volume.to_numpy(float)) \
          / np.maximum(g.volume.to_numpy(float), 1e-12)
    ofi6 = pd.Series(imb).rolling(6).mean().to_numpy()
    lc = np.log(c)
    mom = np.column_stack([pd.Series(lc).diff(k_).to_numpy() for k_ in (1,2,4,6,12,24)])
    g["s_flow"] = zs(ofi_residual(ofi6, mom), 480)
    g["s_fundz"] = -zs(g.fund.to_numpy(float), 240)
    g["s_posn"] = g.posn
    if sym in HAS_CM:
        g["s_cmpx"] = zs(pd.Series(np.log(g.cm_px.to_numpy(float) / c)).diff(6).to_numpy(), 120)
    g["atr14"] = atr14(g.high.to_numpy(float), g.low.to_numpy(float), c)
    g = g[g.dt >= START].reset_index(drop=True)
    _P[sym] = g
    return g

def signals_for(sym):
    base = ["flow", "fundz", "posn"]
    if sym in HAS_CM: base.append("cmpx")
    if sym == "BTCUSDT": base.append("btcdom")
    return base

def net(sym, exp=1.0, cap=3.0):
    g = panel(sym); names = signals_for(sym)
    U = []
    for n in names:
        z = g[f"s_{n}"].to_numpy(float); t = THR[n]
        e = np.where(z > t, 1.0, np.where(z < -t, -1.0, 0.0))
        U.append(np.nan_to_num(e * np.clip(np.abs(z) / t, 1.0, CAP)))
    v = np.column_stack(U) @ (np.ones(len(U)) / len(U))
    if exp == 1.0: return v
    nz = np.abs(v) > 0
    if nz.sum() < 50: return v
    u = np.sign(v) * np.abs(v) ** exp
    u = u * (np.abs(v[nz]).mean() / max(np.abs(u[nz]).mean(), 1e-12))
    return np.sign(u) * np.minimum(np.abs(u), cap)

_X = {}
def exec_for(sym):
    """Execution bars and funding for THIS instrument. Passing these is what the
    harness needed: without them every instrument executed against BTCUSDT."""
    if sym in _X: return _X[sym]
    if sym == "BTCUSDT":
        _X[sym] = (None, None)
        return _X[sym]
    e = pd.read_parquet(f"{D}/{sym}_15m.parquet")
    e["dt"] = pd.to_datetime(e.dt, utc=True).astype("datetime64[ns, UTC]")
    f = pd.read_parquet(f"{D}/{sym}_funding.parquet")
    f["dt"] = pd.to_datetime(f.dt, utc=True).astype("datetime64[ns, UTC]")
    _X[sym] = (e, f)
    return _X[sym]

def book(sym, risk, exp=1.0, stp=3.0, rr=2.0, hold=21, start=START, end=OOS_END):
    g = panel(sym); v = net(sym, exp); a = g.atr14.to_numpy(float)
    ex, fu = exec_for(sym)
    arr = dict(entry=np.nan_to_num(v), stop=stp * a, tp=stp * rr * a,
               exit=(np.abs(np.nan_to_num(v)) <= 0.0).astype(float))
    return backtest(g, arr, "12h", start=start, end=end, risk=risk,
                    max_lev=10.0, max_bars_h=hold * 24,
                    exec_df=ex, exec_key=sym, funding_df=fu)

def daily(m):
    return pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                     ).resample("1D").last().dropna().pct_change().fillna(0.0)

def stats(r, tag, extra=""):
    e = np.cumprod(1 + r.to_numpy()); yrs = (r.index[-1] - r.index[0]).days / 365.25
    dd = float((e / np.maximum.accumulate(e) - 1).min()); cagr = e[-1] ** (1/yrs) - 1
    b = bootstrap_dd(r.to_numpy(), n=2000)
    print(f"{tag:>28} | CAGR {cagr*100:7.1f}%  DD {dd*100:6.1f}%  "
          f"Sharpe {r.mean()/r.std()*np.sqrt(365.25):5.2f}  Calmar {cagr/abs(dd):5.2f}"
          f" | med {b['dd_median']*100:6.1f}%  P>20% {b['p_dd_worse_than_20']*100:3.0f}% {extra}")
    return cagr, dd

if __name__ == "__main__":
    print(f"window {START} -> {OOS_END}\n")
    R = {}
    for s in SYMS:
        g = panel(s)
        m = book(s, 0.08)
        R[s] = daily(m)
        print(f"{s:>10} {len(g):5d} bars  signals {','.join(signals_for(s)):<32} "
              f"CAGR {m['cagr']*100:7.1f}%  DD {m['max_dd']*100:6.1f}%  PF {m['profit_factor']:5.2f}"
              f"  N {m['trades']:4d}  Shp {m['sharpe']:5.2f}")
    df = pd.DataFrame(R).dropna(how="all")
    print("\ncorrelation between the instrument books' daily returns:")
    print(df.corr().round(3).to_string())
    off = df.corr().to_numpy()[np.triu_indices(len(SYMS), 1)]
    print(f"\nmean pairwise correlation: {off.mean():.3f}   (single-instrument signals: 0.10)")
    # align on a common calendar first: summing Series with different indices
    # yields NaN wherever one is missing, which silently poisons the curve
    A = pd.DataFrame(R).fillna(0.0)
    A = A[(A.index >= pd.Timestamp(START, tz="UTC"))]
    print("\nequal-weight, one account, risk split across the five:")
    for k in (1, 2, 3, 4, 5):
        stats(A.mean(axis=1) * k, f"5 instruments, x{k}")
    print("\nBTCUSDT alone at matched sizes, for comparison:")
    for k in (1, 2, 3):
        stats(A["BTCUSDT"] * k, f"BTC only, x{k}")
    print("\nalts only (no BTC):")
    for k in (1, 2, 3):
        stats(A[[c for c in A.columns if c != "BTCUSDT"]].mean(axis=1) * k, f"4 alts, x{k}")
