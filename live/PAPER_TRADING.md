# Paper trading V7 — start here

Written for someone who has never run a trading bot. Nothing below places a real
order or spends real money.

## The thing that trips everyone up

**Binance testnet cannot produce this strategy's signals.**

V7 reads five things. Testnet has one of them:

| the strategy needs | testnet has it? |
|---|---|
| BTCUSDT price bars | yes |
| taker-buy volume split | partly, but from testnet's own thin book |
| `BTCUSD_PERP` (coin-margined) for the stablecoin basis | **no** |
| turnover of 15 alt perps for BTC dominance | **no** |
| top-trader positioning metrics | **no** |
| the funding-rate series | testnet's own, which is not the real one |

So the correct shape is **split-brain**:

```
  REAL Binance public data  ──►  signals  ──►  orders  ──►  testnet OR paper broker
  (no API key needed)                                       (fake money)
```

You compute signals from production market data — which is free, public and
needs no key — and send the resulting orders somewhere harmless.

## Two harmless places to send them

**Option A — the paper broker in this repo (`live/paper.py`). Recommended.**
It charges exactly what the backtest charged: 5 bps commission and 3 bps adverse
slippage per side, marked against the real price. So your paper numbers and the
backtest numbers are in the same units and can be compared directly. That
comparison is the entire point of paper trading, and testnet destroys it.

**Option B — Binance USDⓈ-M Futures testnet.**
Real order plumbing, fake money. Worth doing *once*, to rehearse the mechanics:
placing a market order, placing reduce-only stops, seeing them fire. But its
order book is thin and its prices drift from production, so a fill there tells
you nothing about what the trade would really have cost.

**Do both, for different reasons.** Testnet teaches you the plumbing. The paper
broker tells you whether the strategy works.

---

## Part 1 — Get the data working (do this first)

```bash
pip install pandas numpy pyarrow
export BOOK_STORE=~/quant/data/live          # put this in your shell profile

python live/fetch.py seed --months 36        # pulls years of history, takes a while
python live/fetch.py update
```

Then check the signals are alive:

```bash
python live/runner.py verify
```

You should see five components and a net signal. If `posn` is `nan` or looks
frozen, your positioning panel is too short — see the runway note at the end.

**Do not go further until `verify` prints five real numbers.** Everything else
is downstream of this.

## Part 2 — Choose this quarter's three configurations

```bash
python live/v7_select.py
```

This ranks 200 configurations on the trailing twelve months and writes the best
three to `v7_plan.json`. It takes a few minutes. Re-run it on 1 January,
1 April, 1 July and 1 October — never in between, because re-choosing whenever
you feel like it is how a walk-forward rule turns into hindsight.

## Part 3 — Open the paper book

```bash
python live/paper.py init --equity 10000
```

Start at **8% risk**, not the 14.4% that produced the 179% headline. At 14.4%
the bootstrap says a drawdown worse than 20% is 98% likely. At 8% it is 34%, and
the backtest returns 86.2% at −12.3%.

## Part 4 — The twice-daily routine

At **00:05 and 12:05 UTC** — just after each 12h bar closes:

```bash
python live/fetch.py update
python live/v7.py orders --equity 10000 --risk 0.08
```

It prints something like:

```
NET TARGET   LONG 0.0186 BTC   (notional 1,940 USDT, 0.19x equity)
order        BUY 0.0186 BTC  (market, at the next 15m open)
```

Record that fill in the paper book, using the real BTCUSDT price at the time:

```bash
python live/paper.py fill --side BUY --qty 0.0186 --price 104250 --note "sleeve entry"
```

Then look at the stop ladder so you know where each sleeve exits:

```bash
python live/v7.py stops --equity 10000 --risk 0.08
```

If price later trades through one of those stops, record that too:

```bash
python live/paper.py fill --side SELL --qty 0.0062 --price 101800 --note "sleeve 2 stop"
```

And once a day, mark the book:

```bash
python live/paper.py mark --price 104900
python live/paper.py report
```

That is the whole loop. Two commands twice a day, one mark daily.

## Part 5 — Automate it, once it is boring

Only after you have done it by hand for two weeks and understand every line it
prints:

```cron
5 0,12 * * *  cd ~/quant && BOOK_STORE=~/quant/data/live python live/fetch.py update && python live/v7.py orders --equity 10000 --risk 0.08 >> ~/quant/paper.log 2>&1
```

Read the log each morning. Automating something you do not yet understand just
means the mistakes happen faster.

## Part 6 — Rehearsing the plumbing on testnet

Separately, and only to learn the mechanics:

1. Go to the Binance **futures testnet** site and sign in (it uses a GitHub
   login). Check the current URL on Binance's own docs rather than trusting a
   link pasted anywhere, including here.
2. Generate an API key and secret. **These are testnet-only keys — they cannot
   touch real money, and they are not your production keys.**
3. Install a client: `pip install python-binance`
4. Point it at testnet, place one small market order, then place a reduce-only
   `STOP_MARKET` against it and watch it sit there in the order list.

That fourth step is the one that matters for V7, because the whole design rests
on placing **three** reduce-only stops against one netted position. Do it once by
hand and you will understand `live/v7.py stops` immediately.

Never put a production API key in a script you are still writing. When you do
eventually go live, create a key with **futures trading enabled, withdrawals
disabled, and an IP allowlist**.

---

## How to tell whether it is working

Give it a full quarter, including one quarterly re-selection. V7 averages one to
two trades a week, so twenty closed trades is about three months. Before that,
your sample is too small to mean anything — a good week proves nothing and a bad
week disproves nothing.

Then compare against the backtest, in this order:

1. **Did the signals match?** Run `strategies/s87_combined.py` over the same
   dates and check the sleeve entries line up. If the signals disagree, nothing
   downstream matters. This is the check that actually finds bugs.
2. **Profit factor**, which is size-independent. Backtest V7: 3.18.
3. **Drawdown**, against −12.3% at 8% risk.
4. **Return**, last. It is the noisiest number over one quarter and the one you
   will be most tempted to read first.

## Two things that will go wrong

**The positioning runway.** `s_posn` uses 80 days of 4-hour history and the REST
endpoint serves about 30. Until you have backfilled from the archive's
`futures/um/daily/metrics` files, that signal is quietly wrong — not missing,
*wrong*, which is worse. Check `runner.py verify` shows a plausible `posn` before
trusting anything.

**Missed bars.** If your machine is asleep at 00:05 UTC you miss a decision. The
backtest never misses one. A week of missed bars makes the comparison
meaningless, so log every run and check for gaps.

## Risk

Everything here is paper. When you eventually consider real money: V7's own
bootstrap puts a worse-than-20% drawdown at **34% probability** at 8% risk and
**98%** at the size that produced the headline. The backtest's realised −19.99%
was a favourable draw, not an expectation. 2022 was roughly flat and 2025
returned a fraction of 2023. Size for the bad year, because you do not get to
choose which one you start in.
