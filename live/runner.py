#!/usr/bin/env python3
"""
Live runner for the S60 adaptive-conviction book.  BTCUSDT perpetual, one
account, one position at a time.

WHY THIS EXISTS AND NOT A PINESCRIPT
------------------------------------
Three of the five signals cannot be expressed on TradingView at all:

  s_flow    needs Binance's taker-buy volume split per bar, then a regression
            against past returns whose coefficients are refit monthly on an
            expanding window.  Pine exposes neither.
  s_fundz   needs the funding-rate series.  Not available as a Pine series.
  s_posn    needs top-trader position ratio and retail account ratio from
            Binance's futures-data endpoints.  Not on TradingView in any form.

and the adaptive layer re-optimises 40 configurations quarterly, which Pine
cannot do at all.  A Pine version would be a different, much weaker strategy.

WHAT THIS DOES
--------------
  seed     bootstrap local history from the Binance public data archive
           (data.binance.vision).  Needed because the positioning endpoints
           only serve ~30 days, while the signals need 240-day z-scores.
  update   top the local store up from the REST API
  signal   print the current net signal, the conviction exponent in force,
           and the target position
  orders   print the order that moves you from your current position to target

Read-only by default.  It never places an order and never reads an API key.

RISK
----
Backtested performance is not a forecast.  The book's own bootstrap puts a 21%
chance of a drawdown worse than 20% at the 8% risk setting, and 46% at 10%.
Size accordingly, and paper-trade it first.
"""
import os, sys, io, json, time, zipfile, argparse, subprocess
import numpy as np, pandas as pd

FAPI = "https://fapi.binance.com"
DAPI = "https://dapi.binance.com"
ARCHIVE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
STORE = os.environ.get("BOOK_STORE", os.path.expanduser("~/quant/data/live"))
ALTS = ["ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT",
        "AVAXUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "ATOMUSDT", "FILUSDT", "NEARUSDT",
        "TRXUSDT"]
TF = "12h"
BARS_PER_MONTH = 60          # 12h bars in ~30 days
THR = dict(flow=1.0, cmpx=1.0, btcdom=1.0, fundz=1.0, posn=0.7)
CAP = 2.0

# ---------------------------------------------------------------- http helpers
def get(url, params=None, timeout=20):
    q = "" if not params else "?" + "&".join(f"{k}={v}" for k, v in params.items())
    r = subprocess.run(["curl", "-sS", "--max-time", str(timeout), url + q],
                       capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        raise RuntimeError(f"request failed: {url}{q}\n{r.stderr[:300]}")
    return json.loads(r.stdout)

# ---------------------------------------------------------------- indicators
def zscore(x, w):
    s = pd.Series(np.asarray(x, float))
    return ((s - s.rolling(w).mean()) / (s.rolling(w).std() + 1e-12)).to_numpy()

def atr(h, l, c, n=14):
    """Wilder's ATR: RMA of true range, i.e. ewm(alpha=1/n, adjust=False).
    A simple rolling mean here diverges from the backtest by up to 1,100 USDT."""
    pc = pd.Series(c).shift(1).to_numpy()
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return pd.Series(tr).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()

# ---------------------------------------------------------------- signals
def ofi_residual(ofi6, mom, warm_months=6):
    """Orthogonalise flow to past returns; coefficients refit monthly on an
    EXPANDING window of strictly past data, exactly as in the backtest."""
    x = np.asarray(ofi6, float)
    good = np.isfinite(x) & np.isfinite(mom).all(1)
    out = np.full(len(x), np.nan); coef = None
    for i0 in range(BARS_PER_MONTH * warm_months, len(x), BARS_PER_MONTH):
        hist = good.copy(); hist[i0:] = False
        if hist.sum() > 200:
            A = np.column_stack([np.ones(hist.sum()), mom[hist]])
            coef = np.linalg.lstsq(A, x[hist], rcond=None)[0]
        if coef is None: continue
        j1 = min(i0 + BARS_PER_MONTH, len(x)); sl = slice(i0, j1); gm = good[sl]
        seg = np.full(j1 - i0, np.nan)
        seg[gm] = x[sl][gm] - np.column_stack([np.ones(gm.sum()), mom[sl][gm]]) @ coef
        out[sl] = seg
    return out

def posn_composite(df4):
    """The positioning composite, computed on 4h bars exactly as the backtest does.

    Two details matter and both were wrong in the first draft of this file:
    the z-windows are 480 *4-hour* bars (80 days, not 240), and tt_vs_retail is
    itself clipped to +/-3 before the three parts are summed with NaN treated
    as zero.  Getting either wrong drops sign agreement with the backtest from
    100% to 69%.
    """
    tt_pos = df4.tt_pos.to_numpy(float)
    tt_acct = df4.tt_acct.to_numpy(float)
    retail = df4.retail_acct.to_numpy(float)
    parts = np.column_stack([
        np.clip(zscore(np.log(tt_pos / np.maximum(retail, 1e-6)), 480), -3, 3),
        -np.clip(zscore(retail, 480), -3, 3),
        -np.clip(zscore(tt_acct, 480), -3, 3)])
    return np.nansum(parts, axis=1) / 3.0

def build_signals(df, df4):
    """df:  12h panel with open/high/low/close/volume/taker_buy_base, cm_px,
            btc_dom_z, fund
       df4: 4h panel with tt_pos, tt_acct, retail_acct
    Returns the five signals and atr14."""
    c = df.close.to_numpy(float)
    imb = (2 * df.taker_buy_base.to_numpy(float) - df.volume.to_numpy(float)) \
          / np.maximum(df.volume.to_numpy(float), 1e-12)
    ofi6 = pd.Series(imb).rolling(6).mean().to_numpy()
    lc = np.log(c)
    mom = np.column_stack([pd.Series(lc).diff(k).to_numpy() for k in (1, 2, 4, 6, 12, 24)])
    s = {}
    s["flow"] = zscore(ofi_residual(ofi6, mom), 480)
    s["cmpx"] = zscore(pd.Series(np.log(df.cm_px.to_numpy(float) / c)).diff(6).to_numpy(), 120)
    s["btcdom"] = df.btc_dom_z.to_numpy(float)          # 480-HOUR z, computed upstream
    s["fundz"] = -zscore(df.fund.to_numpy(float), 240)
    comp4 = pd.Series(posn_composite(df4),
                      index=pd.to_datetime(df4.dt)).resample(TF).last()
    s["posn"] = comp4.reindex(pd.to_datetime(df.dt)).to_numpy(float)
    a = atr(df.high.to_numpy(float), df.low.to_numpy(float), c, 14)
    return s, a

def unit(z, thr):
    e = np.where(z > thr, 1.0, np.where(z < -thr, -1.0, 0.0))
    return np.nan_to_num(e * np.clip(np.abs(z) / thr, 1.0, CAP))

def net_signal(s, exponent=1.0, cap=3.0):
    U = np.column_stack([unit(s[k], THR[k]) for k in ("flow", "cmpx", "btcdom", "fundz", "posn")])
    v = U @ (np.ones(U.shape[1]) / U.shape[1])
    nz = np.abs(v) > 0
    if nz.sum() < 50 or exponent == 1.0: return v
    u = np.sign(v) * np.abs(v) ** exponent
    u = u * (np.abs(v[nz]).mean() / max(np.abs(u[nz]).mean(), 1e-12))
    return np.sign(u) * np.minimum(np.abs(u), cap)

# ---------------------------------------------------------------- position
def target_position(equity, net, atr14, price, risk=0.08, stop_atr=3.0, max_lev=10.0):
    """Contracts to hold.  Sign is direction; magnitude is risk-based."""
    if not np.isfinite(net) or net == 0 or not np.isfinite(atr14) or atr14 <= 0:
        return 0.0, None, None
    stop_dist = stop_atr * atr14
    qty = (equity * risk * abs(net)) / stop_dist
    qty = min(qty, equity * max_lev / price)
    side = 1 if net > 0 else -1
    stop = price - side * stop_dist
    tp = price + side * 2.0 * stop_dist
    return side * qty, stop, tp

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["signal", "orders", "seed", "update", "verify"])
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--risk", type=float, default=0.08)
    ap.add_argument("--exponent", type=float, default=1.0,
                    help="conviction exponent currently in force (see `verify`)")
    ap.add_argument("--position", type=float, default=0.0, help="contracts currently held")
    ap.add_argument("--panel", default=os.path.join(STORE, "panel_12h.parquet"))
    ap.add_argument("--panel4", default=os.path.join(STORE, "panel_4h.parquet"))
    a = ap.parse_args()

    if a.cmd in ("seed", "update"):
        print("Data collection lives in live/fetch.py — see live/README.md.\n"
              "Seeding pulls full history from the public archive; updating tops up\n"
              "from the REST API, which only serves ~30 days of positioning data.")
        return

    if not os.path.exists(a.panel):
        print(f"no panel at {a.panel}; run `seed` first (see live/README.md)", file=sys.stderr)
        sys.exit(1)
    df = pd.read_parquet(a.panel)
    df4 = pd.read_parquet(a.panel4)
    s, atr14 = build_signals(df, df4)
    v = net_signal(s, a.exponent)
    i = len(df) - 1
    px = float(df.close.iloc[i])

    if a.cmd == "verify":
        for k in s: print(f"  {k:8s} {s[k][i]:+.3f}   unit {unit(s[k], THR[k])[i]:+.3f}")
        print(f"  net {v[i]:+.4f}   atr14 {atr14[i]:.1f}   close {px:.1f}")
        return

    qty, stop, tp = target_position(a.equity, v[i], atr14[i], px, a.risk)
    print(f"bar closed   {pd.to_datetime(df.dt.iloc[i])}")
    print(f"net signal   {v[i]:+.4f}   (exponent {a.exponent})")
    print(f"components   " + "  ".join(f"{k}={s[k][i]:+.2f}" for k in s))
    if qty == 0:
        print("target       FLAT")
    else:
        print(f"target       {'LONG' if qty > 0 else 'SHORT'} {abs(qty):.4f} BTC "
              f"(notional {abs(qty)*px:,.0f} USDT, {abs(qty)*px/a.equity:.2f}x equity)")
        print(f"stop         {stop:,.1f}      take-profit {tp:,.1f}")
    if a.cmd == "orders":
        delta = qty - a.position
        if abs(delta) * px < 100:
            print("order        none (within minimum notional)")
        else:
            print(f"order        {'BUY' if delta > 0 else 'SELL'} {abs(delta):.4f} BTC")
        print("\nAlso exit if the net signal reaches exactly 0 on any close, or after 21 days.")

if __name__ == "__main__":
    main()
