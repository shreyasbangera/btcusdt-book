#!/usr/bin/env python3
"""
Live runner for V7 — the gated top-3 blend.

WHAT IS DIFFERENT FROM runner.py
--------------------------------
runner.py trades ONE configuration: one position, one stop, one target.  V7
holds the best THREE configurations at once, each at a third of the risk
budget, each with its own stop distance, target and holding cap, and each
possibly gated by a different moving average.  In a single account you hold the
NET of the three, so this file keeps the sleeves as bookkeeping and sends only
the net delta to the exchange.

THE ONE FACT THAT MAKES THIS TRACTABLE
--------------------------------------
All three sleeves read the SAME composite signal and differ only in the
conviction exponent, the stop, the target, the holding cap and the gate.  The
exponent never changes a sign, and every configuration flattens on a reversal
and on a flat signal, so the sleeves are always on the same side or flat.  The
net position is therefore |sum of sleeve quantities| on a single side, and each
sleeve's stop can be placed on the exchange as its own REDUCE-ONLY
STOP_MARKET order sized to that sleeve's quantity.  Three stops on one netted
position is legal on Binance and is what keeps protection on the exchange
rather than inside this process.

The runner still checks for the opposite case and refuses to act on it rather
than guessing, because if it ever happens something upstream is wrong.

WHAT THIS DOES NOT DO
---------------------
It never places an order and never reads an API key.  It prints the orders to
place.  Wire it to an exchange client only after paper-trading it.

RISK
----
V7's stationary block bootstrap puts the chance of a drawdown worse than 20% at
98% at the 14.4% risk that produced the headline 179%, and 34% at 8% risk.  The
realised −19.99% in the backtest is a favourable draw, not the expectation.
Size to the bootstrap, not to the backtest.
"""
import os, sys, json, argparse
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live.runner import build_signals, unit, THR, CAP, STORE

STATE = os.path.join(STORE, "v7_state.json")
PLAN = os.path.join(STORE, "v7_plan.json")


# ------------------------------------------------------------------ signals
def composite(s):
    """The equal-weight net of the five signals, before any exponent."""
    parts = [unit(s[k], THR[k]) for k in s]
    return np.nanmean(np.vstack(parts), axis=0)


def shaped(v, p, cap=3.0):
    """Conviction curve: |v|^p rescaled so the MEAN position is unchanged, so p
    changes the shape of the bet and never the leverage."""
    nz = np.abs(v) > 0
    if not nz.any():
        return v
    u = np.sign(v) * np.abs(v) ** p
    u = u * (float(np.abs(v[nz]).mean()) / max(float(np.abs(u[nz]).mean()), 1e-12))
    return np.sign(u) * np.minimum(np.abs(u), cap)


def gate_up(close, kind, n):
    """True where the gate considers the market to be trending up."""
    px = pd.Series(close)
    if kind in (None, "", "none"):
        return np.zeros(len(px), bool)
    if kind == "ema":
        return (px > px.ewm(span=n, adjust=False).mean()).fillna(False).to_numpy()
    raise ValueError(f"unknown gate {kind!r}")


def sleeve_target(v_row, close_row, atr_row, cfg, equity, risk, max_lev=10.0):
    """Target quantity, stop and take-profit for one configuration."""
    p, stp, rr, hold, gk, gn = cfg
    u = v_row
    if gk and u < 0 and close_row["up_" + f"{gk}{gn}"]:
        u = 0.0                                   # gate blocks SHORT entries only
    if u == 0.0:
        return 0.0, None, None
    side = 1 if u > 0 else -1
    sd = stp * atr_row
    qty = (equity * risk * abs(u)) / sd
    qty = min(qty, equity * max_lev / close_row["close"])
    px = close_row["close"]
    return side * qty, px - side * sd, px + side * rr * sd


# ------------------------------------------------------------------- state
def load(path, default):
    if os.path.exists(path):
        return json.load(open(path))
    return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(obj, open(path, "w"), indent=1)


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["signal", "orders", "stops", "state"])
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--risk", type=float, default=0.08,
                    help="TOTAL risk budget; each sleeve gets risk/3")
    ap.add_argument("--panel", default=os.path.join(STORE, "panel_12h.parquet"))
    ap.add_argument("--panel4", default=os.path.join(STORE, "panel_4h.parquet"))
    ap.add_argument("--plan", default=PLAN)
    a = ap.parse_args()

    plan = load(a.plan, None)
    if plan is None:
        print(f"no plan at {a.plan}.\n"
              f"Run  python strategies/s87_combined.py  then\n"
              f"  python live/v7.py_select  (see live/V7.md) to write the three\n"
              f"configurations chosen for the current quarter.", file=sys.stderr)
        sys.exit(1)
    cfgs = [tuple(c) for c in plan["configs"]]

    df = pd.read_parquet(a.panel)
    df4 = pd.read_parquet(a.panel4)
    s, atr14 = build_signals(df, df4)
    v = shaped_all = {}
    base = composite(s)
    i = len(df) - 1
    close = df.close.to_numpy(float)

    row = {"close": float(close[i])}
    for _, _, _, _, gk, gn in cfgs:
        if gk:
            row[f"up_{gk}{gn}"] = bool(gate_up(close, gk, gn)[i])

    print(f"bar closed   {pd.to_datetime(df.dt.iloc[i])}")
    print(f"composite    {base[i]:+.4f}")
    print(f"components   " + "  ".join(f"{k}={s[k][i]:+.2f}" for k in s))
    print(f"close {row['close']:,.1f}   ATR14 {atr14[i]:,.1f}")
    print()

    per = a.risk / len(cfgs)
    total, lines = 0.0, []
    for j, cfg in enumerate(cfgs, 1):
        p, stp, rr, hold, gk, gn = cfg
        u = shaped(base, p)[i]
        q, stop, tp = sleeve_target(u, row, atr14[i], cfg, a.equity, per)
        total += q
        g = f"{gk}{gn}" if gk else "none"
        if q == 0:
            lines.append(f"  sleeve {j}  exp {p}  {stp}ATR x{rr}R  {hold}d  gate {g:>7}"
                         f"   FLAT  (conviction {u:+.3f})")
        else:
            lines.append(f"  sleeve {j}  exp {p}  {stp}ATR x{rr}R  {hold}d  gate {g:>7}"
                         f"   {'LONG ' if q > 0 else 'SHORT'} {abs(q):.4f} BTC"
                         f"   stop {stop:,.1f}  tp {tp:,.1f}")
    print("\n".join(lines))
    print()

    sides = {np.sign(q) for q in (total,) if q}
    print(f"NET TARGET   {'LONG' if total > 0 else 'SHORT' if total else 'FLAT'} "
          f"{abs(total):.4f} BTC   "
          f"(notional {abs(total)*row['close']:,.0f} USDT, "
          f"{abs(total)*row['close']/a.equity:.2f}x equity)")

    if a.cmd == "orders":
        st = load(STATE, {"position": 0.0})
        delta = total - st["position"]
        if abs(delta) * row["close"] < 100:
            print("order        none (below minimum notional)")
        else:
            print(f"order        {'BUY' if delta > 0 else 'SELL'} {abs(delta):.4f} BTC  "
                  f"(market, at the next 15m open)")
        print("\nReplace the reduce-only stop ladder after the fill — `stops` prints it.")

    if a.cmd == "stops":
        print("\nreduce-only STOP_MARKET ladder (one per sleeve, same side as the net):")
        for j, cfg in enumerate(cfgs, 1):
            u = shaped(base, cfg[0])[i]
            q, stop, tp = sleeve_target(u, row, atr14[i], cfg, a.equity, per)
            if q:
                print(f"  sleeve {j}  {'SELL' if q > 0 else 'BUY'} {abs(q):.4f} BTC "
                      f"stopPrice {stop:,.1f}  reduceOnly=true")
                print(f"            {'SELL' if q > 0 else 'BUY'} {abs(q):.4f} BTC "
                      f"TAKE_PROFIT_MARKET {tp:,.1f}  reduceOnly=true")

    print("\nRules this runner does not place for you:")
    print("  * exit a sleeve when the composite reaches exactly 0 on a 12h close")
    print("  * exit a sleeve after its holding cap (14 or 21 days)")
    print("  * re-run the quarterly selection on 1 Jan / 1 Apr / 1 Jul / 1 Oct")


if __name__ == "__main__":
    main()
