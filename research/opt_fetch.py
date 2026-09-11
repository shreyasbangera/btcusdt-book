import paths as _P
"""Binance options end-of-hour summary -> hourly volatility-skew features.

Per strike per hour the file carries mark IV, delta, gamma, vega, open interest.
From that the classic options sentiment measures can be built:

  rr25   25-delta risk reversal: IV(25d call) - IV(25d put). The single most
         watched options sentiment number - positive means calls are bid.
  fly25  (IV(25d call) + IV(25d put))/2 - ATM IV. The price of both tails.
  atm    ATM implied volatility (|delta| nearest 0.5)
  pcoi   put open interest / call open interest, in USDT
  gex    dealer gamma exposure proxy: sum(gamma x OI x sign), calls positive

Coverage is only 2023-05-18 -> 2023-10-23 (147 days), so this can support an
information-coefficient measurement and nothing more.
"""
import os, io, zipfile, subprocess
import numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor

B = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/data/option/daily/EOHSummary/BTCUSDT"
OUT = str(_P.DATA / "opt")

def one(day):
    p = f"{OUT}/{day}.parquet"
    if os.path.exists(p): return day, "cached"
    r = subprocess.run(["curl", "-s", "--max-time", "90", f"{B}/BTCUSDT-EOHSummary-{day}.zip"],
                       capture_output=True)
    if r.returncode or len(r.stdout) < 500: return day, "miss"
    try:
        z = zipfile.ZipFile(io.BytesIO(r.stdout))
        with z.open(z.namelist()[0]) as fh:
            d = pd.read_csv(fh)
    except Exception as e:
        return day, f"bad:{e}"
    d = d[["date", "hour", "type", "mark_iv", "delta", "gamma", "openinterest_usdt"]].copy()
    for c in ("mark_iv", "delta", "gamma", "openinterest_usdt"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["mark_iv", "delta"])
    rows = []
    for (dt_, hr), gp in d.groupby(["date", "hour"]):
        c = gp[gp.type == "C"]; pu = gp[gp.type == "P"]
        if len(c) < 3 or len(pu) < 3: continue
        def near(fr, target, col="delta"):
            i = (fr[col].abs() - target).abs().idxmin()
            return fr.loc[i]
        try:
            c25, p25 = near(c, 0.25), near(pu, 0.25)
            catm, patm = near(c, 0.50), near(pu, 0.50)
        except Exception:
            continue
        atm = 0.5 * (catm.mark_iv + patm.mark_iv)
        coi = c.openinterest_usdt.sum(); poi = pu.openinterest_usdt.sum()
        gex = float((c.gamma * c.openinterest_usdt).sum() - (pu.gamma * pu.openinterest_usdt).sum())
        rows.append(dict(dt=pd.Timestamp(f"{dt_} {int(hr):02d}:00:00", tz="UTC"),
                         rr25=c25.mark_iv - p25.mark_iv,
                         fly25=0.5 * (c25.mark_iv + p25.mark_iv) - atm,
                         atm=atm, pcoi=poi / max(coi, 1.0), gex=gex,
                         oi_total=coi + poi, nstrike=len(gp)))
    if not rows: return day, "empty"
    pd.DataFrame(rows).to_parquet(p, index=False)
    return day, f"ok:{len(rows)}"

if __name__ == "__main__":
    days = pd.date_range("2023-05-18", "2023-10-23", freq="D").strftime("%Y-%m-%d").tolist()
    todo = [d for d in days if not os.path.exists(f"{OUT}/{d}.parquet")]
    print(f"{len(todo)} days", flush=True)
    ok = miss = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        for i, (d, s) in enumerate(ex.map(one, todo)):
            if s.startswith("ok") or s == "cached": ok += 1
            else: miss += 1
            if i % 25 == 0: print(f"  {i}/{len(todo)} ok={ok} miss={miss} {d}:{s}", flush=True)
    fs = sorted(f for f in os.listdir(OUT) if f.endswith(".parquet"))
    big = pd.concat([pd.read_parquet(f"{OUT}/{f}") for f in fs]).sort_values("dt").reset_index(drop=True)
    big.to_parquet(str(_P.DATA / "opt_1h.parquet"), index=False)
    print(f"done ok={ok} miss={miss}  merged {len(big)} hourly rows "
          f"{big.dt.min()} -> {big.dt.max()}", flush=True)
