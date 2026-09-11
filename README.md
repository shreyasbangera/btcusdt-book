# BTCUSDT book

A quantitative trading system for the Binance USDⓈ-M BTCUSDT perpetual: five
signals netted into a single position every 12 hours, the best three
configurations by trailing Calmar held together, short entries blocked while
price is above a long moving average.

**Backtested 179.0% net annual at a −19.99% drawdown** over 2022-03 → 2026-08,
a window that includes the 2022 bear market. Profit factor 3.18, 1,769 trades,
Sharpe 2.13. That is net of 5 bps commission and 3 bps slippage per side and of
real historical funding.

**It does not meet the target it was built for.** The brief asked for 300% net
annual under a 20% drawdown; this misses by 1.7×. `RESEARCH_LOG.md` records all
91 attempts, including the ones that failed and the several that were wrong
before they were right. `REPORT.html` is the readable version.

## What is here

| | |
|---|---|
| `strategies/` | every strategy version, S1 to S91 |
| `strategies/registry.py` | the eight headline books, kept runnable — `python strategies/registry.py` re-measures them all |
| `research/` | the backtest harness, screens and diagnostics |
| `engine/` | the numba backtest loop |
| `live/` | data collection, the live runner, the paper broker |
| `webapp/` | the dashboard and the strategy plug-in interface |
| `.github/workflows/` | the twice-daily decision |
| `deploy/` | where to run it always-on, and what refuses to |
| `RESEARCH_LOG.md` | every attempt and why it died |

## Running it

Start here: **`webapp/SETUP.md`** — which secret goes where, explained from
scratch. Then:

* `webapp/ACTIONS.md` — the twice-daily bot on GitHub Actions
* `webapp/DEPLOY.md` — putting the dashboard on a URL
* `live/PAPER_TRADING.md` — judging the strategy before risking anything
* `live/V7.md` — how the three-sleeve book works in one account
* `deploy/FREE_HOSTING.md` — **where this can actually run for free**, and the
  one `curl` that decides it. Binance refuses most datacentre ranges, GitHub's
  runners included, which rules out nearly every free tier before specs come
  into it
* `deploy/ANDROID.md` — the phone-in-a-drawer route, which is the one I would
  pick

The bot itself needs **pandas and numpy and nothing else** — not numba, not
pyarrow. `tests/no_heavy_deps.py` blocks both and then makes a real decision, so
the claim stays true rather than becoming folklore.

```bash
pip install -r requirements.txt
python live/fetch.py seed --months 36
python -m webapp.app            # http://127.0.0.1:8000
```

## Risk

Backtested performance is not a forecast.

At the size behind the headline return, this book's own stationary block
bootstrap puts a drawdown **worse than 20% at 98% probability**. The realised
−19.99% was a favourable draw, not an expectation. At 8% risk it returns 86.2%
at −12.3% with a 34% breach probability, and that is the setting to start from.

2022 returned +3%. 2023 returned +392% and 2024 +326% — the target is reachable
in a trending year and not on average, which is the study's central finding
rather than a caveat to it.
