"""
S5 - Dynamic Funding-Carry (cash-and-carry basis trade)   [market neutral]

Structure: long spot BTCUSDT / short perp BTCUSDT in equal size.  Delta is ~0;
the P&L is (a) the funding the short leg RECEIVES every 8h, plus (b) the change
in the spot-perp basis, minus (c) four legs of fees+slippage per round trip.

Dynamic overlay: only carry the position when the recent funding regime is rich
enough to pay for the round trip, and flip to the reverse carry (short spot /
long perp) when funding is persistently negative.  Reverse carry is charged an
explicit spot borrow cost.

Capital model: the spot leg consumes its full notional; the perp short is
margined at `perp_lev`.  Capital used = N*(1 + 1/perp_lev), so deployable
notional per unit of equity = 1/(1 + 1/perp_lev).
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from engine.data import load

def run(enter_thr=0.00005, exit_thr=0.0, lookback=9, allow_reverse=True,
        fee_bps=5.0, slip_bps=3.0, perp_lev=5.0, borrow_apr=0.03, usdt_apr=0.08,
        gross_lev=1.0, start="2020-01-01", end="2026-09-01", eq0=10_000.0):
    fut = load("fut_1h"); spot = load("spot_1h"); fr = load("funding")
    m = fut[["dt", "close"]].rename(columns={"close": "perp"}).merge(
        spot[["dt", "close"]].rename(columns={"close": "spot"}), on="dt", how="inner")
    m = m[(m.dt >= start) & (m.dt < end)].reset_index(drop=True)
    # funding settled AT each timestamp -> only visible from that hour onward
    fd = fr.dt.to_numpy(); rt = fr.rate.to_numpy()
    idx = np.searchsorted(fd, m.dt.to_numpy(), side="right") - 1
    ok = idx >= 0
    settle = np.zeros(len(m))                       # cash-flow at this bar
    hit = np.searchsorted(m.dt.to_numpy(), fd)
    hv = hit < len(m)
    settle[hit[hv]] = rt[hv]
    trail = pd.Series(rt).rolling(lookback).mean().to_numpy()
    sig_f = np.full(len(m), np.nan); sig_f[ok] = trail[idx[ok]]   # past-only

    cost = (fee_bps + slip_bps) / 1e4
    cap_per_notional = 1.0 + 1.0 / perp_lev
    eq = eq0; pos = 0; N = 0.0; eq0_ref = [eq0]
    eqc = np.empty(len(m)); trades = []; entry_i = 0; fund_tot = 0.0
    S = m.spot.to_numpy(); P = m.perp.to_numpy()
    for i in range(len(m)):
        f = sig_f[i]
        if pos != 0:
            # funding: short perp RECEIVES a positive rate (pos=+1 = carry)
            eq += pos * settle[i] * N * P[i]
            fund_tot += pos * settle[i] * N * P[i]
            if pos == -1:                              # reverse carry borrows spot
                eq -= borrow_apr / (365 * 24) * N * S[i]
            # levered carry borrows USDT to fund the spot leg: equity*(L-1)
            if gross_lev > 1.0:
                eq -= usdt_apr / (365 * 24) * eq0_ref[0] * (gross_lev - 1.0)
        want = 0
        if np.isfinite(f):
            if f > enter_thr: want = 1
            elif allow_reverse and f < -enter_thr: want = -1
            elif abs(f) < exit_thr: want = 0
            else: want = pos if (pos != 0 and np.sign(f) == pos) else 0
        if want != pos:
            if pos != 0:
                b0 = S[entry_i] - P[entry_i]
                eq += pos * ((S[i] - P[i]) - b0) * N    # realise the basis P&L
                eq -= 2 * cost * N * P[i]              # unwind both legs
                trades.append(dict(i0=entry_i, i1=i, side=pos, eq=eq))
            if want != 0:
                eq0_ref[0] = eq
                N = gross_lev * eq / cap_per_notional / P[i]
                eq -= 2 * cost * N * P[i]              # open both legs
                entry_i = i
            else:
                N = 0.0
            pos = want
        # mark to market: basis change only (delta neutral)
        if pos != 0 and entry_i <= i:
            b0 = S[entry_i] - P[entry_i]
            eqc[i] = eq + pos * (-(S[i] - P[i]) + b0) * N * (-1)
        else:
            eqc[i] = eq
    eqc = pd.Series(eqc).ffill().to_numpy()
    yrs = (m.dt.iloc[-1] - m.dt.iloc[0]).total_seconds() / (365.25 * 24 * 3600)
    peak = np.maximum.accumulate(eqc); dd = eqc / peak - 1
    d = pd.Series(eqc, index=m.dt).resample("1D").last().dropna().pct_change().fillna(0)
    tr = pd.DataFrame(trades)
    return dict(cagr=(eqc[-1] / eq0) ** (1 / yrs) - 1, max_dd=float(dd.min()),
                trades=len(tr), sharpe=float(d.mean() / d.std() * np.sqrt(365.25)) if d.std() > 0 else 0,
                final=eqc[-1], funding=fund_tot, equity=eqc, dt=m.dt)

if __name__ == "__main__":
    print("S5 Dynamic Funding Carry (delta-neutral, long spot / short perp)")
    print(f"{'variant':<44}{'CAGR':>8}{'MaxDD':>8}{'Sharpe':>8}{'N':>6}  Calmar")
    for gl in (1.0, 2.0, 3.0):
        for thr, rev in ((0.00003, True), (0.00008, True), (0.00008, False), (0.0, True)):
            r = run(enter_thr=thr, allow_reverse=rev, gross_lev=gl)
            clm = r["cagr"] / abs(r["max_dd"]) if r["max_dd"] < 0 else float("inf")
            print(f"gross{gl:.0f}x thr{thr*1e4:.2f}bps/8h rev{int(rev):d}{'':<14}"
                  f"{r['cagr']*100:7.1f}%{r['max_dd']*100:7.1f}%{r['sharpe']:8.2f}{r['trades']:6d}  {clm:6.2f}")
