"""Look-ahead audit for the new sleeves (S36 IVOL, S38/S39 CMPX and ETHREL).

Three tests, all on the same harness the strategies use:

  1. ORACLE   feed the engine a signal that is literally next-bar return. If the
              lag is wired correctly this still cannot be free money, but it MUST
              be enormously profitable - if it is not, the harness is broken.
  2. SHIFTED  shift each real signal one bar into the FUTURE. If a strategy is
              clean, peeking one bar ahead should make it much better. If it
              barely changes, the strategy was already peeking.
  3. LAGGED   shift each real signal one bar into the PAST (delay it). A clean
              strategy should degrade smoothly, not collapse or improve.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from research.harness import backtest, OOS_END
import strategies.s36_ivmom as s36
import strategies.s38_orth as s38

KW = dict(risk=0.02, max_lev=10.0, max_bars_h=7 * 24)

def mk(f, s, thr=1.0):
    a = f.atr14.to_numpy()
    return dict(entry=np.nan_to_num(np.where(s > thr, 1.0, np.where(s < -thr, -1.0, 0.0))),
                stop=3.0 * a, tp=6.0 * a, exit=np.zeros(len(f)))

def line(tag, f, s, start, thr=1.0):
    m = backtest(f, mk(f, s, thr), "12h", start=start, end=OOS_END, **KW)
    print(f"  {tag:>26} CAGR {m['cagr']*100:8.1f}%  DD {m['max_dd']*100:6.1f}%  "
          f"PF {m['profit_factor']:5.2f}  N {m['trades']:4d}  Shp {m['sharpe']:5.2f}")
    return m

if __name__ == "__main__":
    fi = s36.ivpanel("12h")
    fx = s38.xpanel("12h"); fx = fx[fx.dt >= "2021-03-01"].reset_index(drop=True)

    for name, f, s, start in (
            ("IVOL  (S36 iv_mom)", fi, s36.signal(fi, use_res=False), s36.START),
            ("CMPX  (S39 f_cmpx)", fx, fx.f_cmpx.to_numpy(float), "2021-03-01"),
            ("ETHREL (S39 f_ethrel, -1)", fx, -fx.f_ethrel.to_numpy(float), "2021-03-01")):
        print(f"\n=== {name}")
        base = line("as traded", f, s, start)
        line("shifted 1 bar EARLIER (peek)", f, np.roll(s, -1), start)
        line("delayed 1 bar (lagged)", f, np.roll(s, 1), start)

    print("\n=== control: oracle signal (next-bar return) on the same harness")
    c = fx.close.to_numpy(float)
    orc = np.zeros(len(c)); orc[:-1] = np.sign(np.diff(c)) * 3.0
    line("oracle", fx, orc, "2021-03-01")
    print("\n(An oracle that is not hugely profitable would mean the harness is broken;")
    print(" a real signal that barely improves when shifted earlier was already peeking.)")

def extra():
    import strategies.s38_orth as s38
    fx = s38.xpanel("12h"); fx = fx[fx.dt >= "2021-03-01"].reset_index(drop=True)
    for name, s in (("BTCDOM (btc_dom_z, +1)", fx.btc_dom_z.to_numpy(float)),
                    ("FUNDZ  (fund_z, -1)", -fx.fund_z.to_numpy(float))):
        print(f"\n=== {name}")
        line("as traded", fx, s, "2021-03-01")
        line("shifted 1 bar EARLIER (peek)", fx, np.roll(s, -1), "2021-03-01")
        line("delayed 1 bar (lagged)", fx, np.roll(s, 1), "2021-03-01")
