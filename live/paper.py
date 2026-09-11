#!/usr/bin/env python3
"""
A paper broker that charges what the backtest charged.

Why not just use Binance testnet for everything?  Because testnet has its own
order book, its own thin liquidity and its own prices, so a fill there tells you
nothing about what a fill would have cost in the real market.  This broker marks
every fill against the REAL Binance price and applies the same costs the
backtest applied - 5 bps commission and 3 bps adverse slippage per side - so the
paper record and the backtest are measured in the same units and can be compared
directly.

Use testnet to rehearse the plumbing (keys, order types, reduce-only stops).
Use this to judge the strategy.

    python live/paper.py init   --equity 10000
    python live/paper.py fill   --side BUY --qty 0.0123 --price 104250 --note "sleeve 1 entry"
    python live/paper.py mark   --price 105100
    python live/paper.py report

Every command writes to $BOOK_STORE/paper.json.  Nothing here touches an
exchange or reads an API key.
"""
import os, sys, json, argparse, datetime as dt
import numpy as np

STORE = os.environ.get("BOOK_STORE", os.path.expanduser("~/quant/data/live"))
BOOK = os.path.join(STORE, "paper.json")
FEE_BPS, SLIP_BPS = 5.0, 3.0


def load():
    if not os.path.exists(BOOK):
        print(f"no paper book at {BOOK} — run `init` first", file=sys.stderr)
        sys.exit(1)
    return json.load(open(BOOK))


def save(b):
    os.makedirs(os.path.dirname(BOOK), exist_ok=True)
    json.dump(b, open(BOOK, "w"), indent=1)


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def do_fill(b, side, qty, price, note):
    """Apply one fill at `price`, charging slippage against you and a taker fee."""
    sgn = 1.0 if side == "BUY" else -1.0
    fill = price * (1.0 + sgn * SLIP_BPS / 1e4)      # slippage always adverse
    fee = abs(qty) * fill * FEE_BPS / 1e4
    pos, entry = b["position"], b["entry"]
    realised = 0.0

    closing = min(abs(qty), abs(pos)) if pos * sgn < 0 else 0.0
    if closing > 0:
        realised = np.sign(pos) * (fill - entry) * closing
        b["equity"] += realised
        pos_after = pos + sgn * qty
        if abs(pos_after) < 1e-12:
            entry = 0.0
        elif np.sign(pos_after) != np.sign(pos):     # flipped through zero
            entry = fill
        pos = pos_after
    else:
        new = pos + sgn * qty
        entry = fill if abs(pos) < 1e-12 else (entry * abs(pos) + fill * abs(qty)) / abs(new)
        pos = new

    b["equity"] -= fee
    b["position"], b["entry"] = pos, entry
    b["ledger"].append(dict(t=now(), side=side, qty=qty, px=price, fill=round(fill, 2),
                            fee=round(fee, 4), realised=round(realised, 2),
                            pos=round(pos, 6), equity=round(b["equity"], 2), note=note))
    return realised, fee, fill


def mtm(b, price):
    return b["equity"] + b["position"] * (price - b["entry"]) if b["position"] else b["equity"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["init", "fill", "mark", "report"])
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--side", choices=["BUY", "SELL"])
    ap.add_argument("--qty", type=float)
    ap.add_argument("--price", type=float)
    ap.add_argument("--note", default="")
    a = ap.parse_args()

    if a.cmd == "init":
        save(dict(started=now(), equity=a.equity, start_equity=a.equity,
                  position=0.0, entry=0.0, ledger=[], marks=[]))
        print(f"paper book created at {BOOK} with {a.equity:,.2f} USDT")
        return

    b = load()

    if a.cmd == "fill":
        if not (a.side and a.qty and a.price):
            print("fill needs --side, --qty and --price", file=sys.stderr); sys.exit(1)
        r, fee, fill = do_fill(b, a.side, abs(a.qty), a.price, a.note)
        save(b)
        print(f"{a.side} {abs(a.qty):.6f} BTC  quoted {a.price:,.1f}  filled {fill:,.2f} "
              f"(slippage {SLIP_BPS} bps)  fee {fee:,.2f}")
        if r:
            print(f"realised    {r:+,.2f} USDT")
        print(f"position    {b['position']:+.6f} BTC @ {b['entry']:,.2f}")
        print(f"cash equity {b['equity']:,.2f} USDT")
        return

    if a.cmd == "mark":
        if not a.price:
            print("mark needs --price", file=sys.stderr); sys.exit(1)
        e = mtm(b, a.price)
        b["marks"].append(dict(t=now(), px=a.price, equity=round(e, 2)))
        save(b)
        peak = max([m["equity"] for m in b["marks"]] + [b["start_equity"]])
        print(f"mark {a.price:,.1f}   equity {e:,.2f} USDT   "
              f"({e / b['start_equity'] - 1:+.2%} since start, "
              f"{e / peak - 1:+.2%} from peak)")
        return

    # ---- report ----
    led, marks = b["ledger"], b["marks"]
    closes = [x["realised"] for x in led if x["realised"]]
    fees = sum(x["fee"] for x in led)
    eq = np.array([m["equity"] for m in marks], float)
    print(f"paper book opened {b['started']}")
    print(f"  fills        {len(led)}   closing trades {len(closes)}")
    print(f"  fees paid    {fees:,.2f} USDT")
    print(f"  position     {b['position']:+.6f} BTC @ {b['entry']:,.2f}")
    print(f"  cash equity  {b['equity']:,.2f} USDT  "
          f"({b['equity'] / b['start_equity'] - 1:+.2%})")
    if closes:
        w = [c for c in closes if c > 0]; l = [-c for c in closes if c < 0]
        print(f"  win rate     {len(w)}/{len(closes)} = {len(w)/len(closes):.0%}")
        pf = f"{sum(w)/sum(l):.2f}" if l else "no losses yet"
        print(f"  profit factor {pf:>13}   (backtest V7: 3.18)")
    if len(eq) > 1:
        dd = float((eq / np.maximum.accumulate(eq) - 1).min())
        print(f"  max drawdown {dd:.2%}   on {len(eq)} marks   "
              f"(backtest V7 at 8% risk: −12.3%)")
    print("\n  A quarter of marks is the minimum before any of this means anything.")
    print("  V7 averages roughly 1-2 trades a week, so 20 trades is about three months.")


if __name__ == "__main__":
    main()
