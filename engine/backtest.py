"""
Event-driven bar-by-bar backtester for BTCUSDT.

Look-ahead discipline
---------------------
* Every indicator/signal for bar t uses ONLY data from bars <= t (closed bars).
* An entry signal produced at the close of bar t is executed at the OPEN of bar t+1.
* Stops / targets are evaluated from bar t+1 onwards using that bar's high/low.
* If a bar's range contains BOTH the stop and the target, the STOP is assumed to
  fill first (conservative / worst-case intrabar ordering).
* Exit signals produced at close of bar t are executed at the OPEN of bar t+1.

Costs
-----
* fee_bps   : exchange commission charged on notional, per side.
* slip_bps  : slippage charged on notional, per side (adverse direction).
* funding_bps_per_8h : perpetual funding, charged on notional per 8h held.
                       Charged to LONGS only by default (conservative: BTC funding
                       has been positive the large majority of the time, and we
                       never credit a short with positive funding).
"""
import numpy as np, pandas as pd

LONG, SHORT, FLAT = 1, -1, 0


class Backtest:
    def __init__(self, df, fee_bps=5.0, slip_bps=3.0, funding_bps_per_8h=1.0,
                 bar_hours=1.0, initial_equity=10_000.0, max_leverage=5.0,
                 charge_funding_to_shorts=False):
        self.df = df.reset_index(drop=True)
        self.fee = fee_bps / 1e4
        self.slip = slip_bps / 1e4
        self.fund = funding_bps_per_8h / 1e4
        self.bar_hours = bar_hours
        self.eq0 = initial_equity
        self.max_lev = max_leverage
        self.fund_shorts = charge_funding_to_shorts

    def run(self, signal, stop_dist, tp_dist=None, risk_frac=0.01,
            trail_atr=None, max_bars=None, exit_signal=None,
            be_at_r=None, partial_at_r=None, partial_frac=0.5):
        """
        signal     : int array, +1 long / -1 short / 0 flat, decided at CLOSE of bar t
        stop_dist  : float array, stop distance in PRICE units, decided at close of bar t
        tp_dist    : float array or None, take-profit distance in price units
        risk_frac  : fraction of equity risked per trade (distance to stop)
        trail_atr  : float array or None -> trailing stop distance in price units
        max_bars   : max holding period in bars
        exit_signal: int array, 1 = flatten at next open
        be_at_r    : move stop to break-even once trade reaches this many R
        partial_at_r: take `partial_frac` of position off at this R multiple
        """
        d = self.df
        o = d.open.to_numpy(float); h = d.high.to_numpy(float)
        l = d.low.to_numpy(float);  c = d.close.to_numpy(float)
        dt = d.dt.to_numpy()
        n = len(d)

        sig = np.asarray(signal, dtype=float)
        sd = np.asarray(stop_dist, dtype=float)
        tp = None if tp_dist is None else np.asarray(tp_dist, dtype=float)
        tr = None if trail_atr is None else np.asarray(trail_atr, dtype=float)
        ex = None if exit_signal is None else np.asarray(exit_signal, dtype=float)

        equity = self.eq0
        eq_curve = np.full(n, np.nan)
        pos = FLAT; qty = 0.0; entry_px = 0.0; stop_px = 0.0; tgt_px = 0.0
        entry_i = -1; r_unit = 0.0; trail_on = False; took_partial = False
        trades = []
        exposure_bars = 0

        for i in range(n):
            # ---------- manage an OPEN position using bar i's range ----------
            if pos != FLAT:
                exposure_bars += 1
                exit_px = None; reason = None

                # trailing stop update uses PREVIOUS bars only (set at end of bar i-1)
                if pos == LONG:
                    hit_stop = l[i] <= stop_px
                    hit_tgt = (tgt_px > 0) and (h[i] >= tgt_px)
                else:
                    hit_stop = h[i] >= stop_px
                    hit_tgt = (tgt_px > 0) and (l[i] <= tgt_px)

                # partial take-profit at R multiple (checked before full TP)
                if partial_at_r and not took_partial and r_unit > 0:
                    plvl = entry_px + pos * partial_at_r * r_unit
                    reached = (h[i] >= plvl) if pos == LONG else (l[i] <= plvl)
                    if reached and not hit_stop:
                        px = plvl - pos * self.slip * plvl
                        cut = qty * partial_frac
                        pnl = pos * (px - entry_px) * cut - self.fee * px * cut
                        equity += pnl
                        qty -= cut
                        took_partial = True

                if hit_stop:
                    exit_px = stop_px - pos * self.slip * stop_px  # adverse slip
                    reason = "stop"
                elif hit_tgt:
                    exit_px = tgt_px - pos * self.slip * tgt_px
                    reason = "target"

                if exit_px is not None:
                    pnl = pos * (exit_px - entry_px) * qty
                    pnl -= self.fee * exit_px * qty
                    hrs = (i - entry_i) * self.bar_hours
                    if pos == LONG or self.fund_shorts:
                        pnl -= self.fund * (hrs / 8.0) * entry_px * qty
                    equity += pnl
                    trades.append(dict(entry_dt=dt[entry_i], exit_dt=dt[i], side=pos,
                                       entry=entry_px, exit=exit_px, qty=qty,
                                       pnl=pnl, bars=i - entry_i, reason=reason,
                                       equity=equity))
                    pos = FLAT; qty = 0.0; tgt_px = 0.0

            # mark-to-market equity at bar close
            if pos != FLAT:
                mtm = pos * (c[i] - entry_px) * qty
                eq_curve[i] = equity + mtm
            else:
                eq_curve[i] = equity

            if equity <= 0:
                eq_curve[i:] = 0.0
                break

            # ---------- update trailing stop / BE using CLOSED bar i ----------
            if pos != FLAT:
                if be_at_r and r_unit > 0:
                    be_lvl = entry_px + pos * be_at_r * r_unit
                    reached = (h[i] >= be_lvl) if pos == LONG else (l[i] <= be_lvl)
                    if reached:
                        stop_px = max(stop_px, entry_px) if pos == LONG else min(stop_px, entry_px)
                if tr is not None and np.isfinite(tr[i]) and tr[i] > 0:
                    if pos == LONG:
                        stop_px = max(stop_px, c[i] - tr[i])
                    else:
                        stop_px = min(stop_px, c[i] + tr[i])
                if max_bars and (i - entry_i) >= max_bars:
                    # flag: close at next open
                    pos_timeout = True
                else:
                    pos_timeout = False
            else:
                pos_timeout = False

            # ---------- decide action for NEXT bar's open ----------
            if i + 1 >= n:
                continue
            nxt_open = o[i + 1]

            want_flat = pos_timeout or (ex is not None and pos != FLAT and ex[i] == 1)
            # signal reversal / exit
            if pos != FLAT and not want_flat:
                if sig[i] == 0 or (sig[i] != 0 and np.sign(sig[i]) != pos):
                    want_flat = True

            if pos != FLAT and want_flat:
                px = nxt_open * (1 - pos * self.slip)
                pnl = pos * (px - entry_px) * qty - self.fee * px * qty
                hrs = (i + 1 - entry_i) * self.bar_hours
                if pos == LONG or self.fund_shorts:
                    pnl -= self.fund * (hrs / 8.0) * entry_px * qty
                equity += pnl
                trades.append(dict(entry_dt=dt[entry_i], exit_dt=dt[i + 1], side=pos,
                                   entry=entry_px, exit=px, qty=qty, pnl=pnl,
                                   bars=i + 1 - entry_i, reason="signal", equity=equity))
                pos = FLAT; qty = 0.0; tgt_px = 0.0

            # entry
            if pos == FLAT and sig[i] != 0 and np.isfinite(sd[i]) and sd[i] > 0 and equity > 0:
                side = int(np.sign(sig[i]))
                px = nxt_open * (1 + side * self.slip)   # adverse slip on entry
                risk_amt = equity * risk_frac
                q = risk_amt / sd[i]
                notional = q * px
                if notional > equity * self.max_lev:
                    q = equity * self.max_lev / px
                if q <= 0:
                    continue
                equity -= self.fee * px * q
                pos = side; qty = q; entry_px = px; entry_i = i + 1
                r_unit = sd[i]
                stop_px = px - side * sd[i]
                tgt_px = (px + side * tp[i]) if (tp is not None and np.isfinite(tp[i]) and tp[i] > 0) else 0.0
                took_partial = False

        # close any residual position at last close
        if pos != FLAT:
            px = c[n - 1] * (1 - pos * self.slip)
            pnl = pos * (px - entry_px) * qty - self.fee * px * qty
            equity += pnl
            trades.append(dict(entry_dt=dt[entry_i], exit_dt=dt[n - 1], side=pos,
                               entry=entry_px, exit=px, qty=qty, pnl=pnl,
                               bars=n - 1 - entry_i, reason="eod", equity=equity))
            eq_curve[n - 1] = equity

        eq_curve = pd.Series(eq_curve).ffill().fillna(self.eq0).to_numpy()
        return self._metrics(eq_curve, trades, exposure_bars)

    def _metrics(self, eq, trades, exposure_bars):
        d = self.df
        n = len(eq)
        years = (d.dt.iloc[-1] - d.dt.iloc[0]).total_seconds() / (365.25 * 24 * 3600)
        tr = pd.DataFrame(trades)
        final = eq[-1]
        tot_ret = final / self.eq0 - 1
        cagr = (final / self.eq0) ** (1 / years) - 1 if final > 0 and years > 0 else -1.0
        peak = np.maximum.accumulate(eq)
        dd = np.where(peak > 0, eq / peak - 1.0, 0.0)
        maxdd = float(dd.min())
        if len(tr):
            gp = tr.loc[tr.pnl > 0, "pnl"].sum(); gl = -tr.loc[tr.pnl < 0, "pnl"].sum()
            pf = gp / gl if gl > 0 else np.inf
            wr = float((tr.pnl > 0).mean())
            avg_w = tr.loc[tr.pnl > 0, "pnl"].mean() if (tr.pnl > 0).any() else 0.0
            avg_l = tr.loc[tr.pnl < 0, "pnl"].mean() if (tr.pnl < 0).any() else 0.0
            avg_bars = float(tr.bars.mean())
        else:
            gp = gl = 0.0; pf = 0.0; wr = 0.0; avg_w = avg_l = 0.0; avg_bars = 0.0
        rets = pd.Series(eq).pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        ppy = (365.25 * 24) / self.bar_hours
        sharpe = float(rets.mean() / rets.std() * np.sqrt(ppy)) if rets.std() > 0 else 0.0
        dn = rets[rets < 0].std()
        sortino = float(rets.mean() / dn * np.sqrt(ppy)) if dn and dn > 0 else 0.0
        # per calendar year
        eqs = pd.Series(eq, index=d.dt)
        yearly = {}
        for y, g in eqs.groupby(eqs.index.year):
            start = self.eq0 if y == eqs.index.year[0] else eqs[eqs.index.year < y].iloc[-1]
            yearly[int(y)] = float(g.iloc[-1] / start - 1) if start > 0 else float("nan")
        return dict(
            final_equity=float(final), total_return=float(tot_ret), cagr=float(cagr),
            max_dd=maxdd, profit_factor=float(pf), trades=int(len(tr)), win_rate=wr,
            sharpe=sharpe, sortino=sortino, calmar=float(cagr / abs(maxdd)) if maxdd < 0 else np.inf,
            avg_win=float(avg_w), avg_loss=float(avg_l), avg_bars=avg_bars,
            exposure=float(exposure_bars / n), years=float(years),
            yearly=yearly, equity=eq, trade_df=tr)


def summary(name, m, extra=""):
    y = " ".join(f"{k}:{v*100:.0f}%" for k, v in m["yearly"].items())
    return (f"{name:<34} CAGR {m['cagr']*100:8.1f}%  MaxDD {m['max_dd']*100:6.1f}%  "
            f"PF {m['profit_factor']:5.2f}  N {m['trades']:4d}  WR {m['win_rate']*100:4.1f}%  "
            f"Sharpe {m['sharpe']:5.2f}  Calmar {m['calmar']:6.2f}  [{y}] {extra}")
