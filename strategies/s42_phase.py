"""
S42 - Phase diversification: the same signal, decided at different clock offsets.

A 12h book decides at 00:00 and 12:00 UTC. Nothing makes those two instants
special - they are an artefact of how the bars were cut. Run the identical
signal on bars cut at 06:00/18:00 instead and you get a different trade
sequence from the same information: different entry prices, different stop
placements, different which-side-of-the-bar luck.

That is TIMING luck, and it is diversifiable at zero cost in signal quality.
Averaging over phases should raise the Sharpe of every sleeve without changing
what any of them believes - the one lever in this study that does not require
finding new information.

Tested on the two strongest single books (S31 FLOW and S36 IVOL) and on the
stablecoin-basis book (CMPX), by rebuilding the panel on offset bar grids.
"""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import numpy as np, pandas as pd
from research.harness import panel, backtest, IS_END, OOS_END, _ctx
import research.harness as H

def shifted_panel(tf, hours):
    """Rebuild the decision panel on a grid offset by `hours`, from 1h bars."""
    import research.features as F
    raw = pd.read_parquet(str(_P.DATA / "fut_1h.parquet"))
    raw["dt"] = pd.to_datetime(raw.dt, utc=True).astype("datetime64[ns, UTC]")
    r = raw.set_index("dt")
    off = pd.Timedelta(hours=hours)
    g = (r.index - off).floor(tf) + off
    agg = r.groupby(g).agg(dict(open="first", high="max", low="min", close="last",
                                volume="sum", quote_volume="sum", count="sum",
                                taker_buy_base="sum", taker_buy_quote="sum"))
    agg.index.name = "dt"
    return agg.reset_index().dropna()

if __name__ == "__main__":
    import strategies.s31_ofi6 as s31
    import strategies.s36_ivmom as s36
    from research.runner import zs

    print("Phase diversification is only meaningful if the phases differ. First,")
    print("how much do the same book's daily returns differ across phases?\n")

    # --- IVOL is the cheapest to rebuild: it needs only close + iv
    bv = pd.read_parquet(str(_P.DATA / "bvol_1m.parquet"))
    bv["dt"] = pd.to_datetime(bv.dt, utc=True).astype("datetime64[ns, UTC]")
    ivm = bv.set_index("dt")["iv"]

    curves = {}
    for ph in (0, 3, 6, 9):
        d = shifted_panel("12h", ph)
        iv = ivm.resample("12h", offset=f"{ph}h").last().rename("iv")
        d = d.merge(iv.reset_index(), on="dt", how="left")
        d = d[d.dt >= s36.START].reset_index(drop=True)
        d["iv"] = d.iv.ffill(limit=4)
        # ATR on the shifted grid
        h, l, c = d.high.to_numpy(), d.low.to_numpy(), d.close.to_numpy()
        pc = np.concatenate([[c[0]], c[:-1]])
        tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
        d["atr14"] = pd.Series(tr).rolling(14).mean().to_numpy()
        s = zs(pd.Series(d.iv.to_numpy(float)).pct_change(6).to_numpy(), 120)
        a = s36.arrays(d, s, thr=0.7, atr_stop=3.0, rr=2.0)
        m = backtest(d, a, "12h", start=s36.START, end=OOS_END,
                     risk=0.02, max_lev=10.0, max_bars_h=7 * 24)
        r = pd.Series(m["equity"], index=pd.to_datetime(m["dt"])
                      ).resample("1D").last().dropna().pct_change().fillna(0.0)
        curves[f"ph{ph}"] = r
        print(f"  IVOL phase {ph:>2}h: CAGR {m['cagr']*100:6.1f}%  DD {m['max_dd']*100:6.1f}%  "
              f"PF {m['profit_factor']:5.2f}  N {m['trades']:4d}  Shp {m['sharpe']:5.2f}")

    R = pd.DataFrame(curves).fillna(0.0)
    print("\n  cross-phase correlation of daily returns:")
    print("  " + R.corr().round(3).to_string().replace("\n", "\n  "))
    avg = R.mean(axis=1)
    e = (1 + avg).cumprod(); yrs = (R.index[-1] - R.index[0]).days / 365.25
    dd = (e / e.cummax() - 1).min()
    print(f"\n  4-phase average: CAGR {((e.iloc[-1])**(1/yrs)-1)*100:6.1f}%  DD {dd*100:6.1f}%  "
          f"Shp {avg.mean()/avg.std()*np.sqrt(365.25):5.2f}   "
          f"(best single phase Shp {max(R[c].mean()/R[c].std()*np.sqrt(365.25) for c in R):5.2f})")
