"""
S12 - ETH -> BTC Lead-Lag / Risk-Appetite (ELL)

ETH is the higher-beta major. When ETH order flow and relative strength turn up
before BTC does, it signals broad risk appetite returning to the complex; the
reverse marks risk-off. This is genuinely orthogonal information to anything in
the BTC book itself, so it is a candidate diversifying sleeve.

Signal (all on closed 4h bars):
  ethbtc_mom  = ETH/BTC relative return over n bars
  eth_ofi     = ETH taker-buy imbalance, z-scored
  divergence  = ETH strength while BTC is flat/lagging
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from engine.data import load, agg
from engine.indicators import zscore, atr
from research.harness import panel
from research.runner import evaluate, line

def build_eth(tf="4h"):
    eth = pd.read_parquet(str(_P.DATA / "eth_1h.parquet"))
    if tf != "1h":
        eth = agg(eth, tf)
    return eth

def signals(f, tf="4h", n_rel=12, z_n=240, thr=1.0, atr_stop=3.0, rr=2.0):
    eth = build_eth(tf)
    m = pd.DataFrame({"dt": f.dt}).merge(
        eth[["dt", "close", "volume", "taker_buy_base"]].rename(
            columns={"close": "e_c", "volume": "e_v", "taker_buy_base": "e_tb"}),
        on="dt", how="left")
    ec = m.e_c.to_numpy(float)
    bc = f.close.to_numpy(float)
    rel = np.log(ec / bc)
    rel_mom = pd.Series(rel).diff(n_rel).to_numpy()
    rel_z = zscore(rel_mom, z_n)
    e_imb = np.where(m.e_v.to_numpy() > 0,
                     2 * (m.e_tb.to_numpy() / np.maximum(m.e_v.to_numpy(), 1e-9) - 0.5), 0.0)
    e_ofi = zscore(pd.Series(e_imb).rolling(6).mean().to_numpy(), z_n)
    comp = np.nanmean(np.column_stack([np.clip(rel_z, -3, 3), np.clip(e_ofi, -3, 3)]), axis=1)
    a = f.atr14.to_numpy()
    e = np.where(comp > thr, 1.0, np.where(comp < -thr, -1.0, 0.0))
    return dict(entry=np.nan_to_num(e), stop=atr_stop * a,
                tp=atr_stop * rr * a, exit=np.zeros(len(f))), comp

if __name__ == "__main__":
    for tf in ("4h", "12h"):
        fut, f = panel(tf)
        print(f"\n===== S12 ELL {tf} =====")
        for n_rel in (6, 12, 24):
            for thr in (0.7, 1.1):
                for hold_d in (3, 7):
                    a, comp = signals(f, tf=tf, n_rel=n_rel, thr=thr)
                    r = evaluate("x", f, a, tf, verbose=False, risk=0.01, max_lev=5.0,
                                 max_bars_h=hold_d * 24)
                    print("  " + line(f"nrel{n_rel} thr{thr} {hold_d}d [ALL]", r["ALL"]) +
                          f" | OOS CAGR{r['OOS']['cagr']*100:7.1f}% PF{r['OOS']['profit_factor']:5.2f}")
