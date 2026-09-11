"""Cache the quarterly selection plans.  Recomputing plan(12) is 720 backtests
and every experiment since S77 has paid for it again from scratch."""
import sys, json, os; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import paths as _P
CACHE = str(_P.RESULTS / "plans.json")

def cached_plan(lookback=12):
    d = {}
    if os.path.exists(CACHE):
        d = json.load(open(CACHE))
    k = str(lookback)
    if k not in d:
        from strategies.s77_lookback import plan
        d[k] = [[s, e, list(cfg)] for s, e, cfg in plan(lookback)]
        json.dump(d, open(CACHE, "w"), indent=1)
    return [(s, e, tuple(cfg)) for s, e, cfg in d[k]]

if __name__ == "__main__":
    for lb in (12, 24):
        p = cached_plan(lb)
        print(f"lookback {lb}m: {len(p)} quarters, first {p[0]}, last {p[-1]}")
