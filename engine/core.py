"""
Production backtester for BTCUSDT (Binance USDT-M perpetual).

Execution model
---------------
The simulation runs on a FINE execution grid (5m or 15m) while signals are
generated on a COARSER decision grid (1h / 4h / 1D).  A value derived from
decision bar t only becomes visible to the simulator at the moment bar t closes,
i.e. at the open of decision bar t+1 (see data.align_to_exec).  Entries fill at
the open of the first execution bar at/after that moment.

Because stops and targets are evaluated on 5m/15m bars rather than on the
decision bar, the "which was hit first" ambiguity is resolved by the actual
price path at fine granularity instead of a guess.  Within a single fine bar
that still straddles both levels, the STOP is assumed to fill first.

Costs
-----
fee_bps   : taker commission per side, on notional.
slip_bps  : slippage per side, adverse, on notional.
funding   : REAL Binance historical funding, applied at 00/08/16 UTC on the open
            notional.  Longs pay a positive rate, shorts receive it (the actual
            exchange mechanic).  Liquidation is modelled as a hard equity stop.
"""
import numpy as np, pandas as pd
from numba import njit
from .data import load

FUND_HOURS = (0, 8, 16)


@njit(cache=True)
def _loop(o, h, l, c, entry, exitf, stopd, tpd, traild, fund,
          fee, slip, eq0, risk, maxlev, be_r, trail_after_r, maxbars, min_notional,
          dd_soft, dd_hard, dd_floor, pyr_max, pyr_step, addf, add_mult, add_max,
          add_mode):
    n = o.shape[0]
    eq = eq0
    eqc = np.empty(n)
    hwm = eq0
    pos = 0
    npyr = 0
    blown = False
    qty = 0.0; epx = 0.0; spx = 0.0; tpx = 0.0; runit = 0.0; ei = 0
    cvcur = 0.0; nadd = 0; tunit = 0.0
    # trade records
    t_ei = np.empty(n, np.int64); t_xi = np.empty(n, np.int64)
    t_side = np.empty(n, np.int64); t_epx = np.empty(n); t_xpx = np.empty(n)
    t_pnl = np.empty(n); t_rsn = np.empty(n, np.int64); t_qty = np.empty(n)
    nt = 0
    expo = 0
    fpaid = 0.0

    for i in range(n):
        # ---- funding on open notional (charged at the funding timestamp) ----
        if pos != 0 and fund[i] != 0.0:
            f = -pos * fund[i] * qty * c[i]
            eq += f
            fpaid += f

        # ---- stop / target on this bar's range ----
        if pos != 0:
            expo += 1
            xpx = 0.0; rsn = 0
            if pos == 1:
                hit_s = l[i] <= spx
                hit_t = (tpx > 0.0) and (h[i] >= tpx)
            else:
                hit_s = h[i] >= spx
                hit_t = (tpx > 0.0) and (l[i] <= tpx)
            if hit_s:
                xpx = spx * (1.0 - pos * slip); rsn = 1     # worst-case ordering
            elif hit_t:
                xpx = tpx * (1.0 - pos * slip); rsn = 2
            if rsn != 0:
                pnl = pos * (xpx - epx) * qty - fee * xpx * qty
                eq += pnl
                t_ei[nt] = ei; t_xi[nt] = i; t_side[nt] = pos
                t_epx[nt] = epx; t_xpx[nt] = xpx; t_pnl[nt] = pnl
                t_rsn[nt] = rsn; t_qty[nt] = qty; nt += 1
                pos = 0; qty = 0.0; tpx = 0.0

        # ---- mark to market ----
        if pos != 0:
            eqc[i] = eq + pos * (c[i] - epx) * qty
        else:
            eqc[i] = eq
        if eqc[i] > hwm:
            hwm = eqc[i]
        if eqc[i] <= 0.0:                       # account blown / liquidated
            for j in range(i, n):
                eqc[j] = 0.0
            eq = 0.0
            blown = True
            break

        # ---- update stop from this CLOSED bar ----
        if pos != 0:
            if runit > 0.0:
                if be_r > 0.0:
                    lvl = epx + pos * be_r * runit
                    if (pos == 1 and h[i] >= lvl) or (pos == -1 and l[i] <= lvl):
                        if pos == 1 and epx > spx:
                            spx = epx
                        elif pos == -1 and epx < spx:
                            spx = epx
            if traild[i] == traild[i] and traild[i] > 0.0:
                ok = True
                if trail_after_r > 0.0 and runit > 0.0:
                    lvl = epx + pos * trail_after_r * runit
                    ok = (pos == 1 and h[i] >= lvl) or (pos == -1 and l[i] <= lvl)
                if ok:
                    if pos == 1:
                        ns = c[i] - traild[i]
                        if ns > spx: spx = ns
                    else:
                        ns = c[i] + traild[i]
                        if ns < spx: spx = ns

        if i + 1 >= n:
            continue
        nxt = o[i + 1]

        # ---- flatten on exit signal / timeout / reversal ----
        if pos != 0:
            want = (exitf[i] == 1.0) or (maxbars > 0 and (i - ei) >= maxbars)
            if entry[i] != 0.0 and entry[i] * pos < 0.0:
                want = True
            if want:
                xpx = nxt * (1.0 - pos * slip)
                pnl = pos * (xpx - epx) * qty - fee * xpx * qty
                eq += pnl
                t_ei[nt] = ei; t_xi[nt] = i + 1; t_side[nt] = pos
                t_epx[nt] = epx; t_xpx[nt] = xpx; t_pnl[nt] = pnl
                t_rsn[nt] = 3; t_qty[nt] = qty; nt += 1
                pos = 0; qty = 0.0; tpx = 0.0

        # ---- conviction top-up: the signal now wants a bigger position ----
        # The composite enters at whatever conviction it had on the entry bar and
        # is then frozen for the life of the trade, even though 37% of trades see
        # their own signal at least double while they are held.  When it does,
        # resize the WHOLE package so that its loss down to the existing stop is
        # exactly the risk budget the new conviction earns - never more.
        if pos != 0 and add_max > 0 and nadd < add_max and runit > 0.0:
            ac = addf[i]
            acv = ac if ac > 0.0 else -ac
            ok_pnl = (add_mode != 2) or (pos * (c[i] - epx) >= 0.0)
            if ac != 0.0 and ac * pos > 0.0 and acv >= add_mult * cvcur and ok_pnl:
                dd_now = eqc[i] / hwm - 1.0
                rm = 1.0
                if dd_now < -dd_soft:
                    rm = (dd_hard + dd_now) / (dd_hard - dd_soft)
                    if rm < dd_floor: rm = dd_floor
                    if rm > 1.0: rm = 1.0
                addpx = nxt * (1.0 + pos * slip)
                budget = eqc[i] * risk * rm * acv
                aq = -1.0
                if add_mode == 1 or add_mode == 2:
                    # conviction-driven only: the package carries the SAME risk
                    # unit a fresh entry at this conviction would, and the stop is
                    # reset to one unit from the new average entry so total risk
                    # is exactly the budget.  No price feedback, so a losing trade
                    # can never manufacture a bigger add.
                    aq = budget / runit - qty
                else:
                    # mode 0: hold the stop and solve for the quantity that brings
                    # the package back to budget.  Kept for the record - the
                    # distance to the stop shrinks as a trade loses, so this adds
                    # hardest into losers.  See S83.
                    de = pos * (epx - spx)
                    da = pos * (addpx - spx)
                    if da > 0.25 * runit:
                        aq = (budget - qty * de) / da
                if aq > 0.0:
                    if (qty + aq) * addpx > eqc[i] * maxlev:
                        aq = eqc[i] * maxlev / addpx - qty
                if aq > 0.0 and aq * addpx >= min_notional:
                    eq -= fee * addpx * aq
                    epx = (epx * qty + addpx * aq) / (qty + aq)
                    qty += aq
                    if add_mode == 1 or add_mode == 2:
                        spx = epx - pos * runit
                        if tpx > 0.0 and tunit > 0.0:
                            tpx = epx + pos * tunit
                    cvcur = acv
                    nadd += 1

        # ---- pyramid: add to a winner that has advanced pyr_step R ----
        if pos != 0 and pyr_max > 0 and npyr < pyr_max and runit > 0.0:
            lvl = epx + pos * (npyr + 1) * pyr_step * runit
            reached = (pos == 1 and h[i] >= lvl) or (pos == -1 and l[i] <= lvl)
            if reached and i + 1 < n:
                dd_now = eqc[i] / hwm - 1.0
                rm = 1.0
                if dd_now < -dd_soft:
                    rm = (dd_hard + dd_now) / (dd_hard - dd_soft)
                    if rm < dd_floor: rm = dd_floor
                    if rm > 1.0: rm = 1.0
                addpx = nxt * (1.0 + pos * slip)
                aq = (eqc[i] * risk * rm) / runit
                if (qty + aq) * addpx > eqc[i] * maxlev:
                    aq = eqc[i] * maxlev / addpx - qty
                if aq > 0.0:
                    eq -= fee * addpx * aq
                    epx = (epx * qty + addpx * aq) / (qty + aq)
                    qty += aq
                    npyr += 1
                    # never let a pyramid put the whole package at risk: stop to breakeven
                    if pos == 1 and epx > spx: spx = epx
                    if pos == -1 and epx < spx: spx = epx

        # ---- new entry ----
        if pos == 0 and entry[i] != 0.0 and eq > 0.0:
            sd = stopd[i]
            if sd == sd and sd > 0.0:
                side = 1 if entry[i] > 0 else -1
                px = nxt * (1.0 + side * slip)
                # high-water-mark throttle: full size until dd_soft, tapering to
                # dd_floor of nominal size at dd_hard.
                dd_now = eq / hwm - 1.0
                rm = 1.0
                if dd_now < -dd_soft:
                    rm = (dd_hard + dd_now) / (dd_hard - dd_soft)
                    if rm < dd_floor: rm = dd_floor
                    if rm > 1.0: rm = 1.0
                # conviction sizing: |entry| scales the risk budget for this trade.
                # Books that emit +/-1 are unaffected (|entry| == 1).
                cv = entry[i] if entry[i] > 0.0 else -entry[i]
                q = (eq * risk * rm * cv) / sd
                if q * px > eq * maxlev:
                    q = eq * maxlev / px
                if q * px >= min_notional:
                    eq -= fee * px * q
                    pos = side; qty = q; epx = px; ei = i + 1; npyr = 0
                    cvcur = cv; nadd = 0
                    runit = sd
                    spx = px - side * sd
                    td = tpd[i]
                    tunit = td if (td == td and td > 0.0) else 0.0
                    tpx = px + side * tunit if tunit > 0.0 else 0.0

    if pos != 0 and not blown:
        xpx = c[n - 1] * (1.0 - pos * slip)
        pnl = pos * (xpx - epx) * qty - fee * xpx * qty
        eq += pnl
        t_ei[nt] = ei; t_xi[nt] = n - 1; t_side[nt] = pos
        t_epx[nt] = epx; t_xpx[nt] = xpx; t_pnl[nt] = pnl
        t_rsn[nt] = 4; t_qty[nt] = qty; nt += 1
        eqc[n - 1] = eq

    return eqc, t_ei[:nt], t_xi[:nt], t_side[:nt], t_epx[:nt], t_xpx[:nt], t_pnl[:nt], t_rsn[:nt], t_qty[:nt], expo, fpaid


def funding_array(exec_df, real=True, funding_df=None):
    """Funding rate to apply at each execution bar (0 elsewhere).

    `funding_df` supplies the instrument's own settlements. Without it this
    loaded BTCUSDT funding for every instrument, which is harmless while the
    study is BTCUSDT-only and wrong the moment it is not.
    """
    n = len(exec_df)
    out = np.zeros(n)
    if not real:
        return out
    fr = load("funding") if funding_df is None else funding_df
    ed = exec_df.dt.to_numpy()
    fd = fr.dt.to_numpy()
    idx = np.searchsorted(ed, fd)
    ok = (idx < n)
    out[idx[ok]] = fr.rate.to_numpy()[ok]
    return out


class Engine:
    """fee_bps/slip_bps are PER SIDE."""
    def __init__(self, exec_df, fee_bps=5.0, slip_bps=3.0, eq0=10_000.0,
                 max_leverage=5.0, real_funding=True, min_notional=100.0,
                 funding_df=None):
        self.df = exec_df.reset_index(drop=True)
        self.fee = fee_bps / 1e4
        self.slip = slip_bps / 1e4
        self.eq0 = eq0
        self.maxlev = max_leverage
        self.min_notional = min_notional
        self.fund = funding_array(self.df, real_funding, funding_df)
        self.bar_h = pd.Series(self.df.dt).diff().median().total_seconds() / 3600.0

    def run(self, entry, exit_flag=None, stop_dist=None, tp_dist=None,
            trail_dist=None, risk=0.01, be_r=0.0, trail_after_r=0.0, max_bars=0,
            dd_soft=1.0, dd_hard=1.0, dd_floor=0.0, pyramid=0, pyramid_step=1.0,
            add_signal=None, add_mult=0.0, add_max=0, add_mode=0):
        """dd_soft / dd_hard / dd_floor implement a high-water-mark throttle:
        full nominal risk while the drawdown is shallower than `dd_soft`, tapering
        linearly to `dd_floor` x nominal at `dd_hard`. Defaults disable it.
        `pyramid` adds up to N extra units to a winning position, each after a
        further `pyramid_step` R of favourable movement, with the stop pulled to
        the new average entry so the package is never risking more than the
        original unit."""
        n = len(self.df)
        z = lambda x, d=0.0: (np.full(n, d) if x is None else
                              np.nan_to_num(np.asarray(x, float), nan=d))
        o = self.df.open.to_numpy(float); h = self.df.high.to_numpy(float)
        l = self.df.low.to_numpy(float);  c = self.df.close.to_numpy(float)
        traild = np.asarray(trail_dist, float) if trail_dist is not None else np.full(n, np.nan)
        stopd = np.asarray(stop_dist, float) if stop_dist is not None else np.full(n, np.nan)
        tpd = np.asarray(tp_dist, float) if tp_dist is not None else np.full(n, np.nan)
        res = _loop(o, h, l, c, z(entry), z(exit_flag), stopd, tpd, traild, self.fund,
                    self.fee, self.slip, self.eq0, risk, self.maxlev,
                    be_r, trail_after_r, int(max_bars), self.min_notional,
                    dd_soft, dd_hard, dd_floor, int(pyramid), pyramid_step,
                    z(add_signal), add_mult, int(add_max), int(add_mode))
        return self._metrics(*res)

    def _metrics(self, eqc, ei, xi, side, epx, xpx, pnl, rsn, qty, expo, fpaid):
        d = self.df
        dt = d.dt.to_numpy()
        years = (d.dt.iloc[-1] - d.dt.iloc[0]).total_seconds() / (365.25 * 24 * 3600)
        final = float(eqc[-1])
        cagr = (final / self.eq0) ** (1 / years) - 1 if final > 0 else -1.0
        peak = np.maximum.accumulate(eqc)
        dd = np.where(peak > 0, eqc / peak - 1.0, -1.0)
        maxdd = float(dd.min())
        tr = pd.DataFrame(dict(entry_dt=dt[ei], exit_dt=dt[xi], side=side, entry=epx,
                               exit=xpx, qty=qty, pnl=pnl, reason=rsn,
                               bars=(xi - ei)))
        if len(tr):
            gp = tr.loc[tr.pnl > 0, "pnl"].sum(); gl = -tr.loc[tr.pnl < 0, "pnl"].sum()
            pf = float(gp / gl) if gl > 0 else float("inf")
            wr = float((tr.pnl > 0).mean())
        else:
            pf, wr = 0.0, 0.0
        eqs = pd.Series(eqc, index=d.dt)
        dly = eqs.resample("1D").last().dropna()
        r = dly.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        sharpe = float(r.mean() / r.std() * np.sqrt(365.25)) if r.std() > 0 else 0.0
        dn = r[r < 0].std()
        sortino = float(r.mean() / dn * np.sqrt(365.25)) if dn and dn > 0 else 0.0
        yearly = {}
        prev = self.eq0
        for y, g in eqs.groupby(eqs.index.year):
            yearly[int(y)] = float(g.iloc[-1] / prev - 1) if prev > 0 else float("nan")
            prev = g.iloc[-1]
        return dict(final_equity=final, total_return=final / self.eq0 - 1, cagr=float(cagr),
                    max_dd=maxdd, profit_factor=pf, trades=int(len(tr)), win_rate=wr,
                    sharpe=sharpe, sortino=sortino,
                    calmar=float(cagr / abs(maxdd)) if maxdd < 0 else float("inf"),
                    exposure=float(expo / len(d)), funding_paid=float(fpaid),
                    years=float(years), yearly=yearly, equity=eqc, trades_df=tr,
                    dt=d.dt.to_numpy())


REASON = {1: "stop", 2: "target", 3: "signal", 4: "eod"}


def fmt(name, m):
    y = " ".join(f"{k}:{v*100:+.0f}%" for k, v in m["yearly"].items())
    return (f"{name:<30} CAGR {m['cagr']*100:8.1f}% | DD {m['max_dd']*100:6.1f}% | "
            f"PF {m['profit_factor']:5.2f} | N {m['trades']:5d} | WR {m['win_rate']*100:4.1f}% | "
            f"Shp {m['sharpe']:5.2f} | Clm {m['calmar']:6.2f} | Exp {m['exposure']*100:4.1f}%\n"
            f"{'':30} {y}")
