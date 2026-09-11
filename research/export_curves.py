"""Downsample equity curves to weekly points and emit compact JSON for the report."""
import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
import pandas as pd, numpy as np, json

df = pd.read_parquet(str(_P.RESULTS / "curves.parquet"))
df.index = pd.to_datetime(df.index, utc=True)
w = df.resample("1W").last().dropna(how="all")
out = {"dates": [d.strftime("%Y-%m-%d") for d in w.index]}
for c in w.columns:
    s = w[c].astype(float)
    out[c] = [None if not np.isfinite(v) else round(float(v), 1) for v in s]

# BTC spot buy & hold on the same weekly grid, normalised to 10k
from engine.data import load
sp = load("spot_1h")
sp = sp[(sp.dt >= w.index[0]) & (sp.dt <= w.index[-1])]
b = sp.set_index("dt").close.resample("1W").last().reindex(w.index).ffill()
out["BTC"] = [None if not np.isfinite(v) else round(float(v), 1)
              for v in (10_000.0 * b / b.dropna().iloc[0])]
json.dump(out, open(str(_P.RESULTS / "curves.json"), "w"))
print("weeks:", len(w), "series:", [c for c in out if c != "dates"])
for c in w.columns:
    print(f"  {c:<14} final {w[c].dropna().iloc[-1]:>12,.0f}")
print(f"  {'BTC':<14} final {10_000.0*b.dropna().iloc[-1]/b.dropna().iloc[0]:>12,.0f}")
