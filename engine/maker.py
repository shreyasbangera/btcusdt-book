"""
Passive (maker) execution engine on 1-minute bars.

Every earlier book in this study crossed the spread on both sides: ~4.5 bps fee
+ ~3.5 bps slippage = 16 bps round turn. That cost is what kills every fast
signal at the screen, and the fundamental law says Sharpe = IC x sqrt(bets), so
the only untapped lever left is to trade far more often - which is only possible
if the round turn collapses.

This engine models RESTING LIMIT ORDERS instead:

  place    at the first minute after the decision bar closes, a limit is posted
           away from the market (bid below for a long, offer above for a short)
  fill     only if a later minute trades STRICTLY THROUGH the limit price
           (low < lim for a bid). Touching the level is not enough - that is
           the queue-position haircut, and it is what makes the model honest:
           you are filled exactly on the moves that first went against you,
           which is the adverse selection a maker actually eats.
  ttl      unfilled orders are cancelled after ttl minutes. No chasing.
  exit     target is a resting limit  -> maker fee, no slippage
           stop is a market order     -> taker fee + slippage
           timeout is a market order  -> taker fee + slippage
           if a minute's range covers both stop and target, the STOP is taken.

Funding is charged on open positions at the 8h marks from the real funding
series. One position at a time.
"""
import numpy as np
from numba import njit

@njit(cache=True)
def _mk(o, h, l, c, dec_i, side, lim, tp, sl, ttl, maxhold, fund,
        fee_mk, fee_tk, slip, eq0, risk, maxlev, min_notional, touch):
    n = len(c); nd = len(dec_i)
    eq = eq0
    eq_curve = np.empty(n); eq_curve[:] = eq0
    tr_pnl = np.zeros(nd); tr_kind = np.zeros(nd, np.int64)   # 1 tp 2 sl 3 timeout
    tr_in = np.zeros(nd, np.int64); tr_out = np.zeros(nd, np.int64)
    ntr = 0

    state = 0            # 0 flat, 1 resting, 2 in position
    j = 0                # next decision to consider
    s = 0.0; q = 0.0; ep = 0.0; xlim = 0.0; xstop = 0.0
    t_cancel = 0; t_out = 0; blown = False

    for i in range(n):
        if blown:
            eq_curve[i] = 0.0
            continue

        # ---- funding on open position, charged at the 8h marks
        if state == 2 and fund[i] != 0.0:
            eq -= s * q * c[i] * fund[i]

        # ---- manage an open position on this minute's path
        if state == 2:
            done = 0; px = 0.0
            if s > 0:
                if l[i] <= xstop:
                    px = xstop * (1.0 - slip); done = 2
                elif h[i] >= xlim:
                    px = xlim; done = 1
            else:
                if h[i] >= xstop:
                    px = xstop * (1.0 + slip); done = 2
                elif l[i] <= xlim:
                    px = xlim; done = 1
            if done == 0 and i >= t_out:
                px = c[i] * (1.0 - slip * s); done = 3
            if done > 0:
                fee = fee_mk if done == 1 else fee_tk
                eq += s * q * (px - ep) - q * px * fee
                tr_pnl[ntr] = s * q * (px - ep) - q * px * fee
                tr_kind[ntr] = done; tr_out[ntr] = i; ntr += 1
                state = 0
                if eq <= 0.0:
                    blown = True; eq_curve[i] = 0.0; continue

        # ---- a resting order: fill on strict penetration, else expire
        if state == 1:
            hit = False
            if touch == 1:
                # OPTIMISTIC bound: a touch of the level fills you (front of queue)
                if s > 0 and l[i] <= lim[j - 1]:
                    hit = True
                elif s < 0 and h[i] >= lim[j - 1]:
                    hit = True
            else:
                # CONSERVATIVE bound: the level must trade strictly through
                if s > 0 and l[i] < lim[j - 1]:
                    hit = True
                elif s < 0 and h[i] > lim[j - 1]:
                    hit = True
            if hit:
                ep = lim[j - 1]
                eq -= q * ep * fee_mk
                state = 2
                xlim = tp[j - 1]; xstop = sl[j - 1]
                t_out = i + maxhold[j - 1]
                tr_in[ntr] = i
                if eq <= 0.0:
                    blown = True; eq_curve[i] = 0.0; continue
            elif i >= t_cancel:
                state = 0

        # ---- place a new order if flat and a decision lands on this minute
        while j < nd and dec_i[j] <= i:
            if state == 0 and dec_i[j] == i and side[j] != 0.0:
                d = abs(lim[j] - sl[j])
                if d > 1e-9:
                    qq = (eq * risk) / d
                    mx = (eq * maxlev) / lim[j]
                    if qq > mx: qq = mx
                    if qq * lim[j] >= min_notional:
                        s = side[j]; q = qq
                        t_cancel = i + ttl[j]
                        state = 1
                        j += 1
                        break
            j += 1

        eq_curve[i] = eq if state != 2 else eq + s * q * (c[i] - ep)

    return eq_curve, tr_pnl[:ntr], tr_kind[:ntr], tr_in[:ntr], tr_out[:ntr]


def run(m1, dec_i, side, lim, tp, sl, ttl, maxhold, fund=None,
        fee_mk=0.00018, fee_tk=0.00045, slip=0.00035, eq0=10_000.0,
        risk=0.01, maxlev=10.0, min_notional=100.0, touch=False):
    o = m1["open"].to_numpy(np.float64); h = m1["high"].to_numpy(np.float64)
    l = m1["low"].to_numpy(np.float64);  c = m1["close"].to_numpy(np.float64)
    f = np.zeros(len(c)) if fund is None else np.asarray(fund, np.float64)
    eqc, pnl, kind, tin, tout = _mk(
        o, h, l, c, np.asarray(dec_i, np.int64), np.asarray(side, np.float64),
        np.asarray(lim, np.float64), np.asarray(tp, np.float64),
        np.asarray(sl, np.float64), np.asarray(ttl, np.int64),
        np.asarray(maxhold, np.int64), f,
        fee_mk, fee_tk, slip, eq0, risk, maxlev, min_notional, 1 if touch else 0)
    return dict(equity=eqc, pnl=pnl, kind=kind, t_in=tin, t_out=tout,
                dt=m1["dt"].to_numpy())
