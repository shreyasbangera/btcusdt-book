# Running the book live

BTCUSDT perpetual, one account, one position at a time.

## Why there is no PineScript

Three of the five signals cannot be expressed on TradingView:

| signal | needs | Pine |
|---|---|---|
| `s_cmpx` | `BTCUSD_PERP ÷ BTCUSDT.P` | ✅ two `request.security()` calls |
| `s_btcdom` | BTC ÷ (BTC + 15 alts) turnover | ⚠️ 16 security calls, near Pine's limit |
| `s_flow` | Binance **taker-buy volume split** per bar, then a regression against past returns refit monthly on an expanding window | ❌ not exposed |
| `s_fundz` | the funding-rate series | ❌ not available as a Pine series |
| `s_posn` | top-trader position ratio + retail account ratio | ❌ not on TradingView at all |
| adaptive exponent | quarterly re-optimisation over 40 configurations | ❌ Pine cannot self-optimise |

A Pine version would be a different, much weaker strategy wearing this one's name,
and its backtest would look nothing like the published one. Hence this runner.

## Verification

`runner.py` was checked against the backtest on 4,020 identical bars:

| signal | correlation | max abs diff | sign agreement |
|---|---|---|---|
| flow | 1.0000 | 0.0000 | 100.00% |
| cmpx | 1.0000 | 0.0000 | 100.00% |
| btcdom | 1.0000 | 0.0000 | 100.00% |
| fundz | 1.0000 | 0.0258 | 99.98% |
| posn | 1.0000 | 0.0030 | 99.88% |
| **net signal** | **0.9947** | 0.4005 | **99.28%** |
| atr14 | 1.0000 | 0.0000 | — |

End to end, a backtest driven by this file's signals returns **53.9% / −14.9% /
PF 2.04 / Sharpe 2.16** against the published **54.9% / −14.9% / PF 2.03 /
Sharpe 2.20**. The one-point gap is the 0.7% of bars where resample edge
alignment flips the net sign.

Two bugs the verification caught, both of which would have silently changed the
strategy: ATR must be Wilder's RMA (a rolling mean diverges by up to 1,100
USDT), and the positioning composite must be computed on **4-hour** bars and
sampled to 12h — computing it on 12h bars stretches its z-windows from 80 days
to 240 and drops sign agreement to 69%.

## Setup

```bash
pip install pandas numpy pyarrow
export BOOK_STORE=~/quant/data/live

python live/fetch.py seed --months 36     # bootstrap from the public archive
python live/fetch.py update               # top up from REST; run this daily
```

The seed/update split exists because the positioning endpoints only return
about 30 days, while the signals need 240-day z-scores. **After a fresh seed the
4h positioning panel is too short**; either run `update` daily for a few months
before trading, or backfill it from the archive's `futures/um/daily/metrics`
files the way `research/altmetrics.py` does.

## Daily use

Run after each 12h close (00:00 and 12:00 UTC):

```bash
python live/fetch.py update
python live/runner.py signal --equity 10000 --risk 0.08
python live/runner.py orders --equity 10000 --risk 0.08 --position 0.031
```

`signal` prints the net signal, its five components, and the target position
with its stop and take-profit. `orders` prints the delta from what you hold.

Rules the runner does not place for you:
- **exit whenever the net signal reaches exactly 0** on a close, not only on stop or target
- 21-day maximum hold
- stop is 3 × ATR(14); take-profit 2R

## The conviction exponent

The published book re-chooses the exponent quarterly from the trailing 18
months. `runner.py` takes it as `--exponent` rather than choosing it for you, so
that the choice stays explicit and auditable. Re-run `strategies/s60_adaptive.py`
each quarter and pass the exponent it selects. `--exponent 1.0` is the plain
linear book, which is what the 5.5-year 54.9% figure refers to.

## Risk

Backtested performance is not a forecast. The book's own bootstrap puts the
chance of a drawdown worse than 20% at **21%** at the 8% risk setting and
**46%** at 10%. 2022 was negative in every variant tested. Paper-trade it first,
and size it as though the bootstrap is right rather than the backtest.

## What is not tested here

The Binance REST endpoints are unreachable from the environment this was
developed in, so `fetch.py`'s live paths (`rest_klines`, `rest_metrics`,
`rest_funding`) are written against the documented API but have **not** been
executed. The archive path and all of `runner.py` are verified against real
data. Check the first `update` output carefully.
