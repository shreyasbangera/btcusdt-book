"""
S46 - The net-signal book.  One account, one position, no portfolio.

FINAL SPECIFICATION.

Five signals, each reading a different market, are reduced to a single number
every 12 hours. The account holds at most one BTCUSDT perpetual position at a
time, with one stop and one target. There are no sub-accounts, no sleeve
bookkeeping and no rebalancing.

  s_flow    6-bar taker-buy imbalance orthogonalised to past returns (S31),
            z-scored over 480 bars           -> aggressive order flow
  s_cmpx    log(BTCUSD_PERP / BTCUSDT_PERP) differenced 6 bars, z-scored over
            120                              -> the implied USDT/USD rate
  s_btcdom  BTC quote volume / (BTC + 15 alts quote volume), z-scored over 120
                                             -> rotation across the complex
  s_fundz   MINUS the funding-rate z-score    -> fade crowded leverage
  s_posn    top-trader vs retail positioning composite (S7), computed on 4h
            bars and carried to the 12h grid  -> who is positioned how
  (s_ivol)  3-day change in the BVOL implied-volatility index, z-scored over
            120. Only available from 2023-06-20, so it is a sixth signal on the
            short window and absent on the long one.

Each signal contributes 0 inside its threshold band and +/-1 outside, scaled by
|z| / threshold and capped at 2. The contributions are averaged with EQUAL
weights - in-sample-fitted inverse-volatility weights were tested and are worse.
Opposing signals cancel before anything is traded, which is where most of the
gain over the sub-account version comes from: profit factor 1.51 -> 2.09,
because offsetting positions are never opened and never pay a round turn.

  entry   net != 0, size = account risk x |net| / stop distance
  stop    3 x ATR(14)
  target  2R
  exit    ALSO close whenever the net signal goes flat - i.e. when no signal is
          past its threshold any more. Holding a position the model no longer
          believes in costs 3.6 points of CAGR and 2.2 points of drawdown, and
          it is most of the in-sample/out-of-sample gap: with the exit the two
          halves read 54.1% and 55.7% instead of 54.1% and 46.5%.
  cap     21 days (rarely binds; 21, 30 and 45 give identical results)
  exec    signal from the closed 12h bar, filled on the next 15m bar
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END
from research.robust import bootstrap_dd
from strategies.s45_single import grid, unit, composite, book, THR, CAP, FULL_START, BV_START

LONG = ["flow", "cmpx", "btcdom", "fundz", "posn"]              # 2021-03 -> 2026-08
SHORT = ["flow", "ivol", "cmpx", "btcdom", "fundz", "posn"]     # 2023-06 -> 2026-08

def run(names, start, risk=0.08, hold=21, stp=3.0, rr=2.0, fee=5.0, slip=3.0,
        end=OOS_END, since=None, flat_exit=True):
    """The panel is ALWAYS built from `start` so that rolling z-score windows warm
    up before the tested period. `since` selects a sub-period of that panel - it is
    what makes the out-of-sample slice honest. Rebuilding the panel from the OOS
    boundary instead would let every window warm up inside the test period."""
    g = grid(start)
    net = composite(g, names)
    a = book(g, net, stp=stp, rr=rr)
    if flat_exit:
        a["exit"] = (np.abs(np.nan_to_num(net)) <= 0.0).astype(float)
    return backtest(g, a, "12h", start=since or start, end=end, risk=risk, max_lev=10.0,
                    max_bars_h=hold * 24, fee=fee, slip=slip)

def report(names, start, risk, label, flat_exit=True):
    A = run(names, start, risk, flat_exit=flat_exit)
    I = run(names, start, risk, end=IS_END, flat_exit=flat_exit)
    O = run(names, start, risk, since=IS_END, flat_exit=flat_exit)
    r = pd.Series(A["equity"], index=pd.to_datetime(A["dt"])).resample("1D").last(
        ).dropna().pct_change().fillna(0).to_numpy()
    b = bootstrap_dd(r, n=3000)
    print(f"\n### {label}")
    print(f"  CAGR {A['cagr']*100:.1f}%   MaxDD {A['max_dd']*100:.1f}%   PF {A['profit_factor']:.2f}"
          f"   N {A['trades']}   WR {A['win_rate']*100:.1f}%   Sharpe {A['sharpe']:.2f}"
          f"   Calmar {A['calmar']:.2f}")
    print(f"  IS {I['cagr']*100:.1f}% / PF {I['profit_factor']:.2f}"
          f"    OOS {O['cagr']*100:.1f}% / PF {O['profit_factor']:.2f} / N {O['trades']}")
    print(f"  bootstrap  median DD {b['dd_median']*100:.1f}%   5th pct {b['dd_p05']*100:.1f}%"
          f"   P(DD>20%) {b['p_dd_worse_than_20']*100:.0f}%")
    print("  yearly " + " ".join(f"{y}:{v*100:+.0f}%" for y, v in A["yearly"].items()))
    return A

if __name__ == "__main__":
    report(LONG, FULL_START, 0.08, "LONG WINDOW, 5 signals, risk 8%, NO flat exit (control)",
           flat_exit=False)
    report(LONG, FULL_START, 0.06, "LONG WINDOW 2021-03 -> 2026-08, 5 signals, risk 6%")
    report(LONG, FULL_START, 0.08, "LONG WINDOW 2021-03 -> 2026-08, 5 signals, risk 8%  [HEADLINE]")
    report(LONG, FULL_START, 0.10, "LONG WINDOW 2021-03 -> 2026-08, 5 signals, risk 10%")
    report(SHORT, BV_START, 0.09, "SHORT WINDOW 2023-06 -> 2026-08, 6 signals, risk 9%")
    report(SHORT, BV_START, 0.15, "SHORT WINDOW 2023-06 -> 2026-08, 6 signals, risk 15%")

    print("\n### robustness of the headline configuration")
    g = grid(FULL_START); net = composite(g, LONG)
    print("  look-ahead audit")
    for tag, v in (("as traded", net), ("shifted 1 bar earlier (peek)", np.roll(net, -1)),
                   ("delayed 1 bar", np.roll(net, 1))):
        a = book(g, v); a["exit"] = (np.abs(np.nan_to_num(v)) <= 0.0).astype(float)
        m = backtest(g, a, "12h", start=FULL_START, end=OOS_END,
                     risk=0.08, max_lev=10.0, max_bars_h=21 * 24)
        print(f"    {tag:>30}  CAGR {m['cagr']*100:7.1f}%  PF {m['profit_factor']:5.2f}"
              f"  Sharpe {m['sharpe']:5.2f}")
    print("  cost ladder")
    for fee, slip, t in ((0, 0, "zero"), (5, 3, "base 16 bps"), (10, 6, "double 32 bps"),
                         (15, 9, "triple 48 bps"), (20, 12, "quadruple 64 bps")):
        m = run(LONG, FULL_START, 0.08, fee=fee, slip=slip)
        print(f"    {t:>30}  CAGR {m['cagr']*100:7.1f}%  PF {m['profit_factor']:5.2f}"
              f"  Sharpe {m['sharpe']:5.2f}")
    print("  leave one signal out")
    for d in LONG:
        keep = [n for n in LONG if n != d]
        m = run(keep, FULL_START, 0.08)
        print(f"    {'without ' + d:>30}  CAGR {m['cagr']*100:7.1f}%  DD {m['max_dd']*100:6.1f}%"
              f"  PF {m['profit_factor']:5.2f}  Sharpe {m['sharpe']:5.2f}")
