"""
S35 - Passive short-term reversal (liquidity provision) on BTCUSDT perp.

The idea the study has not yet tested: stop crossing the spread. Every book so
far paid ~16 bps round turn as a taker, which is why nothing faster than 4h
survived the screen. A resting limit order pays ~3.6 bps round turn instead -
more than four times cheaper - and that is the only thing that can make a
high-frequency-of-bets book viable. Sharpe = IC x sqrt(bets): the sleeves in
this study take ~85 bets a year. A 5-minute book takes thousands.

Signal (all from CLOSED 5m bars):
  z   = k-bar return / rolling sigma of 5m returns
  er  = efficiency ratio over the same window (trend strength)
  after a down-move (z < -thr) in a CHOPPY tape (er < er_max), post a bid
  below the close; after an up-move, post an offer above. Never chase.

Execution: engine/maker.py on 1m bars. Fill requires strict penetration of the
limit, so the model only fills you on moves that first ran against you.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from engine.maker import run

IS_END = "2025-01-01"; OOS_END = "2026-08-31"

_C = {}
def data(dtf="5m"):
    if dtf in _C: return _C[dtf]
    m1 = pd.read_parquet(str(_P.DATA / "fut_1m.parquet"))
    m1 = m1[m1.dt >= "2020-06-01"].reset_index(drop=True)
    d = pd.read_parquet(fstr(_P.DATA / "fut_{dtf}.parquet"))
    d = d[d.dt >= "2020-06-01"].reset_index(drop=True)
    step = int(pd.Timedelta(dtf).total_seconds() // 60)
    # decision bar with open time T closes at T+step -> first actionable minute
    pos = pd.Series(np.arange(len(m1)), index=m1.dt)
    dec = d.dt + pd.Timedelta(minutes=step)
    d["mi"] = dec.map(pos).to_numpy()
    d = d[np.isfinite(d.mi)].reset_index(drop=True); d["mi"] = d.mi.astype(int)
    # funding per minute, charged at the 8h marks
    fu = pd.read_parquet(str(_P.DATA / "funding.parquet"))
    fu.columns = [c.lower() for c in fu.columns]
    tcol = "dt" if "dt" in fu else fu.columns[0]
    rcol = [c for c in fu.columns if "rate" in c or c == "funding"][0]
    fu[tcol] = pd.to_datetime(fu[tcol], utc=True).astype("datetime64[ns, UTC]")
    fmin = pd.Series(0.0, index=m1.dt)
    fu = fu[fu[tcol].isin(fmin.index)]
    fmin.loc[fu[tcol].to_numpy()] = fu[rcol].to_numpy(float)
    _C[dtf] = (m1, d, fmin.to_numpy(float), step)
    return _C[dtf]

def signal(d, k=6, sig_n=288, er_n=24):
    c = d.close.to_numpy(float)
    lr = np.diff(np.log(c), prepend=np.log(c[0]))
    sig = pd.Series(lr).rolling(sig_n).std().to_numpy()
    r = pd.Series(np.log(c)).diff(k).to_numpy()
    z = r / (sig * np.sqrt(k) + 1e-12)
    move = np.abs(pd.Series(c).diff(er_n).to_numpy())
    path = pd.Series(np.abs(np.diff(c, prepend=c[0]))).rolling(er_n).sum().to_numpy()
    er = move / (path + 1e-12)
    return z, sig * c, er

def build(d, z, sp, er, thr=1.2, er_max=0.35, off=0.25, tp_m=1.0, sl_m=1.5,
          ttl=15, hold=180, long_only=False, pol=-1):
    """pol=-1 fade the move (bid after a sell-off); pol=+1 join it
    (bid after a rally, i.e. buy the pullback inside a trend)."""
    n = len(d); c = d.close.to_numpy(float)
    side = np.zeros(n); lim = np.zeros(n); tp = np.zeros(n); sl = np.zeros(n)
    ok = np.isfinite(z) & np.isfinite(sp) & np.isfinite(er) & (er < er_max) & (sp > 0)
    up = ok & (z > thr); dn = ok & (z < -thr)
    lo, sh = (dn, up) if pol < 0 else (up, dn)
    if long_only: sh = np.zeros(n, bool)
    side[lo] = 1.0; side[sh] = -1.0
    d_off = off * sp
    lim = np.where(side > 0, c - d_off, np.where(side < 0, c + d_off, 0.0))
    tp = np.where(side > 0, lim + tp_m * sp, np.where(side < 0, lim - tp_m * sp, 0.0))
    sl = np.where(side > 0, lim - sl_m * sp, np.where(side < 0, lim + sl_m * sp, 0.0))
    return dict(side=side, lim=lim, tp=tp, sl=sl,
                ttl=np.full(n, ttl, int), hold=np.full(n, hold, int))

def evaluate(m1, d, fmin, a, start, end, risk=0.01, **kw):
    mask = (d.dt >= start) & (d.dt < end)
    idx = np.where(mask.to_numpy())[0]
    side = a["side"].copy(); side[~mask.to_numpy()] = 0.0
    r = run(m1, d.mi.to_numpy(), side, a["lim"], a["tp"], a["sl"],
            a["ttl"], a["hold"], fund=fmin, risk=risk, **kw)
    lo = int(d.mi.iloc[idx[0]]); hi = int(min(d.mi.iloc[idx[-1]] + a["hold"][0] + 5, len(m1) - 1))
    eq = np.maximum(r["equity"][lo:hi], 0.0); dt = pd.to_datetime(r["dt"][lo:hi])
    es = pd.Series(eq, index=dt).resample("1D").last().dropna()
    ret = es.pct_change().fillna(0.0)
    yrs = (dt[-1] - dt[0]).days / 365.25
    peak = np.maximum.accumulate(np.maximum(eq, 1e-9)); dd = eq / peak - 1.0
    keep = (r["t_in"] >= lo) & (r["t_in"] < hi)
    pnl = r["pnl"][keep]; kind = r["kind"][keep]
    cagr = (eq[-1] / eq[0]) ** (1 / yrs) - 1 if eq[-1] > 0 else -1.0
    return dict(cagr=cagr, max_dd=float(dd.min()), n=int(len(pnl)),
                pf=float(pnl[pnl > 0].sum() / -pnl[pnl < 0].sum()) if (pnl < 0).any() else np.inf,
                wr=float((pnl > 0).mean()) if len(pnl) else 0.0,
                sharpe=float(ret.mean() / ret.std() * np.sqrt(365.25)) if ret.std() > 0 else 0.0,
                calmar=float(cagr / abs(dd.min())) if dd.min() < 0 else np.inf,
                tp=int((kind == 1).sum()), sl_=int((kind == 2).sum()), to=int((kind == 3).sum()),
                equity=eq, dtx=dt)

if __name__ == "__main__":
    m1, d, fmin, step = data("5m")
    print(f"1m bars {len(m1)}  5m decisions {len(d)}  {d.dt.min()} -> {d.dt.max()}")
    z, sp, er = signal(d)
    hdr = (f"{'cfg':>34} | {'CAGR':>8}{'DD':>8}{'PF':>6}{'N':>7}{'WR':>6}{'Shp':>6}{'Clm':>6}"
           f" | {'tp/sl/to':>16}")
    print(hdr)
    for touch in (False, True):
      print(f"\n########## fill rule: {'TOUCH (optimistic, front of queue)' if touch else 'PENETRATION (conservative)'}")
      for pol in (-1, 1):
        print(f"\n--- polarity {'FADE the move' if pol < 0 else 'JOIN the move (buy the pullback)'}")
        print(hdr)
        for thr in (1.0, 2.0):
          for er_max in (0.30, 1.01):
            for off, tp_m, sl_m in ((0.5, 1.5, 1.5), (1.0, 2.0, 2.0)):
                a = build(d, z, sp, er, thr=thr, er_max=er_max, off=off, tp_m=tp_m,
                          sl_m=sl_m, pol=pol)
                r = evaluate(m1, d, fmin, a, "2020-07-01", OOS_END, risk=0.002,
                             maxlev=5.0, touch=touch)
                print(f"p{pol:+d} thr{thr} er{er_max:.2f} off{off} tp{tp_m} sl{sl_m}".rjust(34) +
                      f" | {r['cagr']*100:7.1f}%{r['max_dd']*100:7.1f}%{r['pf']:6.2f}{r['n']:7d}"
                      f"{r['wr']*100:5.1f}%{r['sharpe']:6.2f}{r['calmar']:6.2f} | "
                      f"{r['tp']:5d}/{r['sl_']:5d}/{r['to']:5d}")
