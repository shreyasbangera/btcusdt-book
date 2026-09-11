# BTCUSDT Systematic Strategy Research Log

## Market & data
| item | value |
|---|---|
| Exchange / market | **Binance USDⓈ-M Perpetual `BTCUSDT`** (spot `BTCUSDT` used for basis) |
| Source | Official Binance public archive (`data.binance.vision`, S3 origin) |
| Decision data | perp 1h / 4h klines (aggregated from 5m) |
| Execution data | perp **15m** klines (intrabar stop/target resolution) |
| Period | 2020-01-01 → 2026-08-31 (perp), spot back to 2017-08-17 |
| Bars | 58,440 × 1h · 233,760 × 15m · 701,280 × 5m — **zero gaps, zero OHLC violations** |
| Funding | real Binance historical funding (7,305 settlements, mean 0.0108%/8h ≈ 12.5%/yr, positive 85.9% of the time) |

## Trading assumptions (applied to every result below)
* Taker fee **5 bps per side**, slippage **3 bps per side** → **16 bps round-turn**.
* Real funding cash-flows at 00/08/16 UTC on open notional (longs pay a positive rate, shorts receive it).
* Signals from **closed** bars only; entry fills at the **open of the next execution bar**.
* Stops/targets resolved on 15m bars; if one bar spans both levels the **stop** fills first.
* Position size = `risk_fraction × equity / stop_distance`, capped by a max-leverage limit.
* Equity compounds; account is marked to market every 15m; equity ≤ 0 = liquidated.

## Validation of the engine
| test | result |
|---|---|
| Frictionless 1x long vs BTC price return | 994.3% vs 992.1% (diff = 1 bar of execution lag) ✔ |
| Random signals, zero cost | PF 0.991 (≈1.0) ✔ |
| Random signals, costs on | PF 0.77 → 0.58 as costs rise ✔ |
| Signal that peeks 1h ahead | CAGR 3034%, PF 4.28 (detector fires) ✔ |
| Same signal, past-only | CAGR −56%, PF 0.53 ✔ |

## Benchmarks (2020-01-01 → 2026-08-31)
| strategy | CAGR | MaxDD | Sharpe |
|---|---|---|---|
| BTC spot buy & hold | 43.2% | −77.2% | 0.90 |

## In-sample signal screen (2020-01 → 2024-06, 1h bars)
Rank-IC and decile economics vs a 16 bps round-turn.

**Rejected — edge smaller than costs**
* Short-horizon price reversion (`rsi4`, `mom2-6`, `clv`): IC ≈ −0.07 at h=1 but decile spread < 0 net of costs.
* 15m sign-reversal (arXiv 2608.21888): reversal spread only **+1.54 bps** over 30 min (t=5.8) vs 16 bps cost. Statistically real, economically dead.
* Raw order-flow imbalance: contaminated by short-horizon reversal (IC −0.04 at h=1).

**Accepted — survives costs in the tails**
| signal | horizon | top-decile fwd ret | net of cost | note |
|---|---|---|---|---|
| `-funding_z` (contrarian funding) | 96h | +109.5 bps (t 10.8) | +93.5 | long side strong |
| `-basis_z` (perp discount to spot) | 96h | +139.8 bps (t 13.6) | +123.8 | **two-sided**: D1 −42.9 bps |
| `ofi96_res` (order flow ⟂ past returns) | 96h | +252.6 bps (t 23.2) | +236.6 | long-biased |
| `ofi24_res` | 96h | +246.1 bps (t 23.6) | +230.1 | long-biased |

Unconditional mean 96h return in-sample ≈ +47 bps, so these are genuine discriminators, not just beta.

---
# Attempts

## S1 — Positioning-Reversal with Flow Confirmation (PRFC)
**Idea.** Perp basis measures how crowded *levered* positioning is; spot taker order flow
orthogonalised to recent returns measures what *unlevered* flow is doing. When they
disagree, the derivatives crowd gets squeezed.
**Rules.** 4h bars. Long if `basis_z < −1.2` and `ofi24_resz > 0`; short if `basis_z > +1.8`
and `ofi24_resz < 0`. Stop 2.0×ATR(14), target 3.5×ATR, time-stop 7 days, risk 1%/trade,
max leverage 5.

| period | CAGR | MaxDD | PF | N | WR | Sharpe |
|---|---|---|---|---|---|---|
| IS 2020-01→2024-06 | 5.8% | −14.6% | 1.28 | 190 | 45.3% | 0.72 |
| OOS 2024-07→2026-08 | 10.6% | −7.8% | 1.32 | 151 | 47.0% | 1.02 |
| ALL | 7.3% | −14.6% | 1.30 | 341 | 46.0% | 0.83 |

**Verdict: FAILS** (CAGR 7.3% ≪ 300%). Edge is real and *holds up out-of-sample*, and the
flow filter is what makes it work (PF 1.04 → 1.30 when added). But the per-trade
expectancy (~0.14% of equity on 51 trades/yr) is two orders of magnitude too small.
On 1h bars the same idea loses money — costs dominate.

## Seasonality screen — REJECTED
Hour-of-day: best hour (20:00 UTC) +4.5 bps, t=2.39; day-of-week best (Wed) +2.2 bps, t=2.14.
Neither survives a multiple-testing correction across 24 hours / 7 days. Funding-settlement
hours are slightly *negative* (−0.83 bps vs +0.75 bps). No tradable calendar effect.

## S2 — Crowding-Reversal Ensemble (CRE)
Equal-weight z-score blend of −funding, −basis, +ofi24_res, +ofi96_res (pairwise
correlations 0.05–0.49, so genuinely additive). Trade the tails; ATR stop/target; time-stop.
Swept 3 timeframes × 3 thresholds × 3 holding periods (27 variants).
**Best:** 4h, thr 0.5, 4-day hold — ALL: CAGR 9.0%, DD −16.8%, PF 1.19, N 684; OOS CAGR 1.6%.
**Verdict: FAILS.** Blending *reduced* per-trade edge vs S1 (PF 1.19 vs 1.30) because the
weakest component (funding) dilutes the strongest. Max Calmar across all 27 variants: **0.59**.

## S3 — Orthogonal Order-Flow Swing (OFS)
Long when spot taker-buy pressure orthogonal to recent returns is in its top decile,
optionally gated by a 100-period EMA trend filter. 32 variants.
**Best:** 4h, `ofi24_resz > 0.75`, 10-day hold, trend filter on — ALL: CAGR 4.9%, DD −9.3%,
**PF 1.75**, N 113; OOS CAGR 3.7%, PF 1.43.
**Verdict: FAILS.** Highest profit factor of any directional idea and it holds up OOS, but
only ~17 trades/yr at 1% risk. Max Calmar **0.58**.

## S4 — Adaptive Volatility-Regime Trend (AVT)
Donchian breakout gated by ADX + efficiency ratio, ATR trailing stop, optional
volatility-regime scaling of the trail. 36 variants.
**Best:** 4h, dc40, ADX>20, ER>0.3, fixed trail — ALL: CAGR 8.0%, DD −9.5%, PF 1.53, N 251;
OOS CAGR 9.6%, PF 1.57 (good IS/OOS agreement).
**Negative result worth recording:** scaling the trailing stop by the volatility regime
*hurt* in 11 of 12 pairings (e.g. Calmar 0.97 → 0.75). Wider trails in high vol give back
too much; the ATR already carries the regime information.
**Verdict: FAILS.** Max Calmar **0.97**.

## S5 — Dynamic Funding Carry (delta-neutral) — best risk-adjusted result so far
Long spot BTCUSDT / short perp BTCUSDT in equal size; collect funding while the trailing
9-settlement funding average exceeds a threshold; flat otherwise. Costs: 4 legs × 8 bps per
round trip, **USDT borrow at 8% APR on the levered portion**, spot borrow 3% APR for reverse carry.

| variant | CAGR | MaxDD | Sharpe | N | Calmar |
|---|---|---|---|---|---|
| gross 1x, thr 0.8 bps/8h, no reverse | 15.4% | −3.9% | **6.72** | 29 | 3.97 |
| gross 2x, thr 0.8 bps/8h, no reverse | 22.8% | −6.7% | 5.55 | 29 | 3.41 |
| gross 3x, thr 0.8 bps/8h, no reverse | 29.0% | −8.8% | 5.09 | 29 | 3.29 |
| gross 3x, always on | 12.4% | −37.1% | 1.77 | 137 | 0.34 |

**Verdict: FAILS** — on trade count (29 < 100) and on CAGR. But Sharpe 5–6.7 and Calmar ~4 are
by far the best risk-adjusted numbers in this study. Two corrections mattered a lot: realising
basis P&L at unwind, and charging USDT borrow on the levered spot leg (that alone cut the
3x variant from 41.5% to 29.0% CAGR).

## S6 — Walk-Forward Gradient Boosting (WFGB)
LightGBM on the full ~75-feature panel, expanding window, refit every 180 bars, with an
h-bar **purge gap** so no training label overlaps the test block. Label = h-bar forward
return / ATR%.
| horizon | early-WF IC | late-WF IC |
|---|---|---|
| 24h | +0.013 | +0.009 |
| 48h | +0.037 | **−0.033** |

**Verdict: FAILS.** The model does not beat the hand-built signals and its IC flips sign out
of sample — the classic overfitting failure mode for ML on a single noisy series.

## New data source added mid-study — Binance futures *metrics*
`data/futures/um/daily/metrics/BTCUSDT/` publishes, every 5 minutes since 2021-01-01:
open interest, the long/short **account** ratio of top traders by margin balance, their
long/short **position** ratio, the long/short account ratio of all accounts (retail), and
the taker long/short volume ratio. 595,268 rows, 604 missing bars (0.1%).

IC screen (IS 2021-01 → 2024-06, 1h bars):
| feature | h=24 | h=48 | h=96 |
|---|---|---|---|
| `tt_vs_retail` = z(log(top-trader position ratio ÷ retail account ratio)) | +0.067 | +0.101 | **+0.108** |
| `tt_acct_z` (crowded count of top accounts) | −0.054 | −0.081 | **−0.102** |
| `retail_acct_z` (fade the crowd) | −0.041 | −0.064 | −0.054 |
| `oi_rank` | −0.023 | −0.030 | −0.041 |

`tt_vs_retail` at IC +0.108 is the **strongest single predictor found in this study** — 50%
above the best price/flow feature. Top decile earned +374 bps over 96h vs +26 bps
unconditional.

## S7 — Smart-Money vs Retail Positioning Divergence (SMRD) — best single directional book
4h bars. Composite = z(log(tt_pos/retail_acct)) − z(tt_acct) − z(retail_acct), each clipped
to ±3. Long if composite > 0.7, short if < −0.7. Stop 3.5×ATR(14), target 2.5R,
time-stop 10 days, risk 1%/trade. 36 variants swept.

| period | CAGR | MaxDD | PF | N | WR | Sharpe | Calmar |
|---|---|---|---|---|---|---|---|
| ALL 2021-01→2026-08 | 9.1% | −7.8% | 1.54 | 229 | 46.3% | 1.13 | **1.17** |
| OOS 2024-07→2026-08 | 9.7% | — | 1.49 | 108 | — | — | — |

**Verdict: FAILS on CAGR**, but the IS and OOS numbers are nearly identical (9.1% vs 9.7%
CAGR, PF 1.54 vs 1.49) — the most convincing single-strategy edge found.

## S10 — Volatility-Managed Trend (VMT)
Exposure = target_vol / realised_vol, gated by a 200-EMA trend filter, on the continuous-
weight simulator (turnover-costed, real funding). 54 variants.
**Best:** 4h, long/flat, target vol 0.8, 240-bar vol window — CAGR 69.5%, DD −61.3%,
PF 1.10, Sharpe 1.13, Calmar 1.13.
**Verdict: FAILS.** Vol-targeting raises *return* substantially but does nothing for Calmar,
because scaling up in quiet markets simply scales the drawdown too. Always-on (no trend
filter) is far worse (DD −66% to −91%).

## S8 — Multi-Strategy Portfolio, first pass
Daily-return correlations of the four sleeves (2021-2026):
|  | SMRD | OFS | AVT | CARRY |
|---|---|---|---|---|
| SMRD | 1.00 | 0.41 | 0.44 | **0.02** |
| OFS | | 1.00 | 0.38 | **−0.01** |
| AVT | | | 1.00 | **−0.03** |

The carry sleeve is essentially uncorrelated with all three directional books — exactly the
diversification the Calmar constraint needs. Risk-parity weights at 8× gave CAGR 140.8%,
DD −14.6%, Sharpe 3.74, Calmar 9.66.
**But this run is not trustworthy**: it scaled each sleeve's *return series* by the leverage
knob, which silently gives the carry sleeve 8× leverage for free. Superseded by S9.

## S9 / S11 — Multi-Strategy Portfolio with honest leverage (MSP-R)
Four sub-accounts (SMRD, OFS, AVT, CARRY), rebalanced monthly, each **re-simulated at its
true size** at every leverage setting so the carry sleeve pays its real USDT borrow cost.
Risk-parity weights are estimated on the in-sample window only and applied unchanged OOS.

Equal weight:
| knob | IS CAGR / DD | OOS CAGR / DD | ALL CAGR / DD | PF | Sharpe | Calmar |
|---|---|---|---|---|---|---|
| 1 | 10.1% / −3.6% | 6.4% / −3.9% | 8.9% / −3.9% | 1.41 | 1.98 | 2.31 |
| 4 | 30.6% / −14.2% | 22.1% / −16.4% | 27.7% / −16.4% | 1.26 | 1.51 | 1.69 |
| 6 | 44.2% / −20.8% | 32.2% / −24.0% | 40.1% / −24.0% | 1.23 | 1.44 | 1.67 |
| 12 | — | — | 72.8% / −42.7% | 1.18 | 1.34 | 1.70 |

Risk parity (IS-derived weights: CARRY 47.8%, OFS 18.4%, SMRD 18.2%, AVT 15.6%):
| knob | IS CAGR / DD / Sharpe | OOS CAGR / DD / Sharpe | ALL Calmar |
|---|---|---|---|
| 1 | 13.6% / −2.3% / 4.36 | 5.6% / −1.8% / 1.51 | 4.73 |

**The correction mattered enormously.** The first-pass S8, which scaled return series instead
of re-simulating, reported Calmar 9.66; done honestly the same construction gives 1.7–4.7.

## Structural finding — the funding premium is decaying
Annualised funding run-rate, half-year buckets:
| period | 2021 H1 | 2021 H2 | 2022 H2 | 2023 | 2024 H1 | 2025 H1 | 2025 H2 | 2026 |
|---|---|---|---|---|---|---|---|---|
| run-rate | **42.0%** | 18.3% | 4.2% | 5.5% | 17.2% | 9.0% | 5.3% | **3.0–3.4%** |

This is the single most important caveat in the whole study. The carry sleeve — the highest
Sharpe component and the one risk parity leans on for ~48% of capital — earns a premium that
has fallen by an order of magnitude as the basis trade became crowded. At a 3% funding
run-rate against an 8% APR USDT borrow, **levered carry is unprofitable today**. Its
historical contribution is not repeatable, and the portfolio's forward-looking Sharpe is
much closer to the OOS figure (1.5) than the full-sample one (3.3).

## S12 — ETH→BTC Lead-Lag (ELL)
ETH/BTC relative momentum plus ETH taker-flow imbalance as a risk-appetite proxy for BTC.
First variants: CAGR −6.6%, PF 0.91, DD −42.6%. **Verdict: FAILS** — no exploitable lead-lag
at 4h once costs are applied; ETH does not lead BTC at this frequency.

## Portfolio frontier — risk parity, honest leverage (the best result in the study)
Weights fixed from the in-sample window (CARRY 47.8%, OFS 18.4%, SMRD 18.2%, AVT 15.6%) and
applied unchanged out-of-sample. The knob raises every sleeve's true size simultaneously.

| knob | IS CAGR / DD / Shp | OOS CAGR / DD / Shp | ALL CAGR | ALL DD | PF | Sharpe | Calmar | N |
|---|---|---|---|---|---|---|---|---|
| 1 | 13.6% / −2.3% / 4.36 | 5.6% / −1.8% / 1.51 | 10.9% | −2.3% | 1.70 | 3.27 | **4.73** | 622 |
| 2 | 20.6% / −5.0% / 3.38 | 9.1% / −4.8% / 1.24 | 16.8% | −5.0% | 1.48 | 2.53 | 3.34 | 622 |
| 3 | 27.6% / −7.7% / 2.99 | 12.6% / −7.8% / 1.15 | 22.5% | −7.8% | 1.39 | 2.26 | 2.89 | 622 |
| 4 | 34.5% / −10.2% / 2.77 | 16.1% / −10.7% / 1.10 | 28.2% | −10.7% | 1.35 | 2.10 | 2.65 | 622 |
| **6** | 48.4% / −15.8% / 2.52 | 22.8% / −16.2% / 1.06 | **39.5%** | **−16.2%** | **1.29** | 1.93 | 2.45 | **622** |
| 8 | 62.2% / −21.4% / 2.37 | 29.3% / −21.4% / 1.03 | 50.7% | −21.4% | 1.25 | 1.82 | 2.37 | 622 |

Knob 6 is the **largest size that still respects the 20% drawdown limit**. It satisfies four of
the five numeric gates (trades 622 ≥ 100 ✔, PF 1.29 > 1.10 ✔, MaxDD −16.2% < 20% ✔, realistic
risk management ✔) and misses only on net yearly profit: **39.5% vs the required 300%**.

Block-bootstrap of the knob-6 daily returns (1,500 resamples, 5-day blocks):
median max drawdown −17.4%, 5th percentile −27.1%, **P(drawdown worse than −20%) = 29%**.
So even the drawdown gate is only marginally met — the realised −16.2% is a favourable draw.

## S13 — Liquidation-Cascade Reversal (LCR)
Long after a ≥3–7% 24h fall accompanied by a ≥2–6% collapse in open interest (forced closing,
not informed selling); mirror image for short. 1h and 4h, 54 variants.
First variants: CAGR −14.8% to −6.9%, PF 0.85–0.95, DD −56% to −68%.
**Verdict: FAILS.** The `flush` condition does mark capitulation (IC +0.023 at h=4) but the
cascade keeps going far enough to take out a 2×ATR stop before the snap-back arrives. The
signal is real; it is not survivable with sane risk control.

## S14 — Volatility-Squeeze Expansion (VSE)
Bollinger bandwidth in the bottom 15–30% of its trailing distribution, then the first close
outside the band. 1h and 4h, 24 variants.
Range: CAGR −36.8% to −9.2%, PF 0.85–0.98, DD −70% to −96%, win rate 27–33%.
**Verdict: FAILS badly.** BTC squeeze breaks are predominantly false; the compression is real
but the direction of the expansion is a coin flip and the stops pay for every one.

---

# Final ranking

**No strategy qualified.** The five numeric gates were: net yearly profit > 300%, ≥100 trades,
profit factor > 1.10, max drawdown < 20%, realistic risk management, no look-ahead bias.
The best configuration clears every gate except net yearly profit, which it misses by 7.6×.

| # | Strategy | Period | CAGR | MaxDD | PF | N | Sharpe | Calmar | OOS CAGR | PF @2× cost | P(DD>20%) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Portfolio, risk parity, size 6 | 2020-01→2026-08 | **39.5%** | −16.2% | 1.29 | 622 | 1.93 | 2.45 | 22.8% | — | 29% |
| 2 | S7 SMRD, 1.0% risk | 2021-01→2026-08 | 9.1% | −7.8% | 1.54 | 229 | 1.13 | 1.17 | 9.7% | 1.48 | **2%** |
| 3 | S7 SMRD, 2.5% risk | 2021-01→2026-08 | 22.9% | −18.7% | 1.49 | 229 | 1.14 | 1.23 | 24.1% | 1.43 | 76% |
| 4 | S4 AVT, 1.0% risk | 2020-01→2026-08 | 8.0% | −9.5% | 1.53 | 251 | 0.77 | 0.85 | 9.6% | 1.45 | 24% |
| 5 | S3 OFS, 2.0% risk | 2020-01→2026-08 | 9.7% | −18.1% | **1.71** | 113 | 0.88 | 0.53 | 7.2% | 1.65 | 28% |
| 6 | S5 Carry, gross 1× | 2020-01→2026-08 | 15.4% | **−3.9%** | — | 29 ✗ | **6.72** | 3.97 | — | — | — |
| — | BTC spot buy & hold | 2020-01→2026-08 | 43.2% | −77.2% | — | 1 | 0.90 | 0.56 | — | — | 100% |

Note that **buy & hold beat every strategy in absolute return** over this window. What the
portfolio buys is a −16.2% worst drawdown instead of −77.2%, and Sharpe 1.93 instead of 0.90.

## Why 300% at <20% drawdown is not reachable here
Two independent calculations agree.

1. **The ratio is fixed by the constraint.** 300% ÷ 20% = Calmar ≥ 15. Measured across every
   portfolio size, `Calmar ≈ 1.3 × Sharpe` (3.27→4.73, 1.93→2.45, 1.82→2.37). Leverage moves
   return and drawdown together and leaves the ratio alone — which is why raising the knob
   from 1 to 14 never helped. Calmar 15 needs **Sharpe ≈ 11** net of costs. Best measured:
   3.27 full-sample, 1.51 out-of-sample.

2. **The signal-strength ceiling.** `Sharpe ≈ IC × √(independent bets/yr)`. The best IC found
   anywhere was 0.108 (top-trader vs retail, 96h horizon). A 96h horizon on one instrument
   gives ~91 non-overlapping bets/yr, so `0.108 × √91 ≈ 1.03` — essentially the 1.13 that
   strategy actually delivered. Sharpe 11 at that IC needs ~10,400 independent bets a year.
   Shortening the horizon to buy breadth fails because IC collapses (0.013 at 1h) and the
   16 bps round-turn eats everything under roughly a 24h hold.

Breadth of that order requires either several hundred weakly-correlated instruments (outside
a BTCUSDT-only brief) or sub-second market making (not evaluable from OHLCV — it needs
order-book reconstruction and a queue model, and its return is a function of latency and fee
tier, not of a signal). **Within the brief, the ceiling observed here is about 40% net annual
at a 16% drawdown.**

---
# Round 2 — futures-only, and attacking the drawdown constraint directly

**Scope correction.** This is futures-only research. S1–S4, S7 and S15–S20 were already pure
Binance USDⓈ-M perpetual BTCUSDT (perp klines, perp funding, futures positioning metrics,
perp execution). **S5, the long-spot / short-perp carry, is out of scope** and is removed —
which matters, because it was 47.8% of the portfolio behind the 39.5% headline.

## Futures-native carry: tested and rejected
Downloaded 24 BTCUSDT **quarterly delivery** contracts (2021-02 → 2026-08, 75,823 hourly bars)
to replace the spot leg with a perp-vs-quarterly calendar trade.

| quantity | mean | sd | positive |
|---|---|---|---|
| quarterly annualised carry | +8.6% | 8.5% | 98% |
| perp funding annualised | +9.9% | 16.8% | — |
| **spread (quarterly − perp)** | **−1.3%** | 10.9% | **49%** |

**Verdict: no edge.** The spot-perp carry earned its 15% by harvesting funding against a leg
that pays none. Once both legs are futures, funding sits on both sides and the spread prices
to zero — exactly as arbitrage should. There is no futures-native replacement for that sleeve.

## New engine capability
Added two mechanisms aimed squarely at the drawdown constraint rather than at returns:
* **High-water-mark throttle** — nominal risk is full while drawdown is shallower than
  `dd_soft`, tapering linearly to `dd_floor` × nominal at `dd_hard`.
* **Pyramiding** — up to N extra units added as a trade advances, each after a further step of
  R, with the stop pulled to the new average entry so the enlarged package never risks more
  than the original unit.

## S15 — Convex Positioning Trend
Deliberately breaks the symmetric return distribution: no take-profit (winners ride an ATR
trail), pyramiding, and the HWM throttle.
* Pyramiding raised profit factor from 1.46 to **2.21** and cut win rate to ~20% — the intended
  convex shape.
* Best unthrottled: risk 5%, pyramid 3 → CAGR 59.6%, DD −70.4%, PF 1.71, **OOS CAGR 110.6%**.
* **The throttle works but locks out.** Tapering to zero caps drawdown at exactly −20.0% but
  collapses trade count from 266 to 15 and CAGR to −0.4%. With a floor of 0.15 it keeps 263
  trades: CAGR 30.6%, DD −40.9%, PF 1.89. Bounding drawdown by shrinking size costs more
  return than it saves.

## S18 — Growth-optimal leverage curve  ← the decisive result
Compound growth is **not monotone in size**. Traced for each book:

| book | peak CAGR | at risk/trade | drawdown at peak | at 22–30% risk |
|---|---|---|---|---|
| S15 convex, pyramid 3 | **59.6%** | 5.0% | −70.4% | **−71.6%** CAGR |
| S15 convex, no pyramid | **63.1%** | 12.0% | −83.6% | −43.2% CAGR |
| S4 adaptive trend | 35.9% | 9.0% | −64.2% | +9.0% CAGR |

Past the growth-optimal point, more size buys **less** compound return and strictly more
drawdown. This is a property of the return distribution, not a tuning failure: no leverage
setting reaches 300%. Under a 20% drawdown budget the same curves sit at roughly 1% risk and
~20% CAGR.

## S17 — Meta-labelling: inconclusive, not disproven
Lopez de Prado meta-labelling (secondary classifier predicting whether each primary signal
wins, expanding window, purge gap = max holding period). Base win rate 48.3% on **232 labelled
trades** — far too few to train a classifier. Higher probability thresholds dropped trade
counts below the 40-trade reporting floor. The technique is sound; this signal does not
generate enough events to use it.

## S20 — Continuous Positioning Signal
Target exposure proportional to signal strength, volatility-targeted, rebalanced every 4h,
costs charged only on the change in position. Higher breadth at lower turnover per bet.
* Best: CAGR **100.6%**, DD −73.9%, Sharpe 1.20, Calmar 1.36, OOS CAGR 50.5%.
* At a 20% drawdown budget: ~25% CAGR.
Sharpe improves slightly over the discrete implementation (1.20 vs 1.13) — the breadth
argument is real but small.

## S19 — Futures-only portfolio (corrected headline)
Four directional perp books, monthly rebalance, IS-derived risk-parity weights.
Sleeve correlations are high because they are all directional on one asset:
SMRD↔CONVEX **0.70**, CONVEX↔AVT 0.60, SMRD↔AVT 0.44, OFS↔others 0.25–0.41.

| knob | IS CAGR / DD | OOS CAGR / DD | ALL CAGR / DD | PF | Sharpe | Calmar | N |
|---|---|---|---|---|---|---|---|
| 1 | 9.0% / −6.7% | 11.6% / −8.9% | 9.9% / −8.9% | 1.24 | 1.12 | 1.11 | 811 |
| 2 | 17.9% / −12.9% | 23.3% / −17.1% | **19.8% / −17.1%** | 1.23 | 1.12 | 1.16 | 811 |
| 3 | 25.3% / −18.8% | 34.6% / −24.5% | 28.6% / −24.5% | 1.22 | 1.10 | 1.17 | 813 |

**Removing the spot leg costs most of the diversification**: Sharpe 1.93 → 1.12, Calmar
2.45 → 1.17. The futures-only answer under a 20% drawdown budget is **≈20% net annual**, not
39.5%.

## S16 — Drawdown-constrained grid search (480 configs, IS-selected then OOS-validated)
Grid over base risk × pyramid depth × throttle parameters × trail width; selection maximises
in-sample CAGR subject to a drawdown budget; the winner is then reported out-of-sample untouched.

| DD budget | IS CAGR / DD | OOS CAGR / DD | full CAGR / DD | winning config |
|---|---|---|---|---|
| 15% | 19.3% / −14.6% | 9.9% / −20.0% | 14.1% / −20.0% | risk 2%, pyr 2, throttle 5/16 floor 0.40 |
| 20% | 31.1% / −17.9% | **11.0% / −23.0%** | 22.1% / −23.0% | risk 2%, pyr 2, throttle 10/22 floor 0.45 |
| 25% | 37.8% / −22.1% | 14.7% / −31.7% | 28.3% / −31.7% | risk 2%, pyr 2, **throttle off** |
| 40% | **73.3%** / −38.5% | **20.2%** / −54.2% | 50.3% / −54.2% | risk 4%, pyr 2, **throttle off** |

**Verdict: FAILS, and instructively.** In-sample CAGR rises to 73.3% as the budget loosens
while out-of-sample sits at 20% regardless — the textbook signature of selection bias once the
real edge is exhausted. The 20% budget is also *breached out of sample* (−23.0%). Note that at
the two loosest budgets the winning configuration has the **throttle switched off**: the grid
independently rediscovered that capping drawdown by shrinking size is not worth its cost.

## S21 — Multi-timeframe ensemble
Same positioning signal on 2h/4h/8h/12h/1D sleeves, equal weight, monthly rebalance.
Per-sleeve IS Sharpe: 2h 1.46 · 4h 1.17 · 8h 0.71 · 12h 0.54 · 1D 0.49.
Cross-sleeve correlations 0.18–0.79.
Best: risk 3.5% → CAGR 19.1%, DD −16.7%, PF 1.17, Sharpe 1.10, N 970.
**Verdict: FAILS.** Equal weighting drags the blend *below* its best single sleeve. Time
diversification is real but the weak long-horizon sleeves cost more than the decorrelation
gains.

## S22 — Short-timeframe positioning book
1h / 2h / 3h / 6h versions of the S7 signal, chasing the higher breadth implied by the 2h
in-sample Sharpe of 1.46.

| tf | IS CAGR / Sharpe | OOS CAGR / Sharpe | full CAGR / DD / PF / N |
|---|---|---|---|
| 1h thr0.5 7d | 23.8% / **1.48** | 11.6% / **0.72** | 19.2% / −14.3% / 1.26 / 722 |
| 2h thr0.5 7d | 15.4% / 1.35 | 8.8% / 0.76 | 12.8% / −11.4% / 1.32 / 468 |
| 4h (baseline) | 22.3% / 1.17 | 24.1% / 1.10 | 22.9% / −18.7% / 1.49 / 229 |

**Verdict: FAILS — and the apparent short-timeframe advantage was in-sample only.** Sharpe
halves out of sample at 1h and 2h, while the 4h book is stable (1.17 → 1.10). Buying breadth
by shortening the horizon does not work for this signal.

---
# Final answer — futures-only

**No strategy qualified.** Under the 20% drawdown limit the best books reach ≈23% net annual.
Removing the limit does not help: the strongest single book peaks at 59.6% CAGR at its
growth-optimal size, and beyond that point more leverage returns less.

| # | Strategy | CAGR | MaxDD | PF | N | Sharpe | IS | OOS | gate missed |
|---|---|---|---|---|---|---|---|---|---|
| 1 | S7 Smart-money vs retail, 2.5% risk | **22.9%** | −18.7% | 1.49 | 229 | 1.14 | 22.3% | 24.1% | profit only |
| 2 | S19 futures-only portfolio, size 2 | 22.6% | −19.3% | 1.24 | 811 | 1.10 | 17.9% | 23.3% | profit only |
| 3 | S15 convex trend, 2% risk | 37.2% | −36.0% | **1.91** | 261 | 0.95 | — | 56.4% | profit + drawdown |
| 4 | S20 continuous vol-targeted | 31.0% | −25.9% | 1.18 | — | 1.21 | — | 22.2% | profit + drawdown |
| 5 | S21 multi-timeframe ensemble | 19.1% | −16.7% | 1.17 | 970 | 1.10 | 21.6% | 15.2% | profit only |
| 6 | S4 adaptive trend, 2.5% risk | 17.1% | −22.2% | 1.46 | 211 | 0.77 | 16.4% | 22.4% | profit + drawdown |
| — | BTCUSDT perp buy & hold | 16.8% | −75.2% | — | 1 | 0.55 | — | — | — |

Every book beats the underlying on this window (perp: 10k → 24.2k; convex book: 10k → 60.0k
at half the drawdown). None comes within an order of magnitude of 300%.

---
# Round 3

## S23 — USDT-perp vs COIN-margined-perp funding differential — REJECTED
Second attempt to rebuild a market-neutral sleeve without a spot leg. Downloaded Binance
COIN-margined `BTCUSD_PERP` (52,985 hourly bars, 2020-08 → 2026-08) and its independent
funding series; matched 2,115 settlements against the USDⓈ-M perp.

| leg | mean funding |
|---|---|
| USDⓈ-M perp `BTCUSDT` | +8.31%/yr |
| COIN-M perp `BTCUSD_PERP` | +8.38%/yr |
| **differential** | **−0.07%/yr**, sd 7.8%, positive **32%** of the time |

**Verdict: no edge.** The two funding rates track each other to within 7 bps a year. Combined
with the quarterly calendar spread (−1.3%/yr, positive 49%), this settles the question:
**Binance's futures complex is internally well-arbitraged and contains no futures-only carry.**
The market-neutral sleeve that carried the earlier portfolio genuinely required the spot leg.

## S24 — Session Range Breakout — REJECTED
Asia (00–08 UTC) range traded in the London session, London range traded in the US session,
US range traded into Asia. 1h bars, ATR or range-width stops, 24 variants.
Range across all variants: CAGR −29% to −54%, **PF 0.83–0.97**, win rate 34–42%, DD −90% to −99%.

## S25 — Session Range FADE — REJECTED, and the pair is informative
Same structure with the signal inverted, on the hypothesis that if breaking out loses then
fading should win. It does not: **PF 0.60–0.76**, CAGR −50% to −63%.

**The pair is the finding.** Costs subtract from both directions, so inverting a post-cost
PF 0.83 strategy does not hand you PF 1.20 — but if range breaks were pure noise the two sides
would lose roughly symmetrically around the cost drag. The fade losing *materially more* than
the breakout (0.60–0.76 vs 0.83–0.97) means breakouts do carry **weak genuine continuation**;
it is simply far too small to clear a 16 bps round turn. Together with S14 (volatility-squeeze
breakout, PF 0.85–0.98) this closes the whole intraday-breakout family: real but sub-cost
momentum at range edges, in both the volatility-compression and session-structure versions.

## Tick-level microstructure — tested and REJECTED as an information source
Downloaded 30 days of `aggTrades` (638 MB, ~50M prints) spanning three regimes (2022-06,
2024-03, 2025-10) and built per-minute features that klines **cannot** express: signed volume
restricted to large prints (≥$50k) vs small prints (≤$1k), aggressor run lengths (the
signature of one participant working an order), true VPIN, trade-size concentration, and
Kyle's lambda (price impact per unit of signed flow). 43,200 minute observations.

| feature | h=5m | h=15m | h=60m | h=240m |
|---|---|---|---|---|
| `kline_imb` (baseline, from klines) | −0.0155 | −0.0187 | −0.0078 | −0.0090 |
| `lg_imb` large-print imbalance | −0.0176 | −0.0201 | −0.0080 | −0.0090 |
| `lg_sm_div` institutions vs retail | −0.0196 | −0.0137 | −0.0006 | −0.0041 |
| `run_len` order-splitting signature | +0.0101 | +0.0101 | +0.0098 | +0.0115 |
| `vpin` | +0.0077 | +0.0131 | +0.0084 | +0.0045 |
| `lam` Kyle's lambda | −0.0102 | −0.0161 | +0.0013 | −0.0054 |

**Residual IC after orthogonalising to the kline baseline: 0.003–0.015** — noise at this sample
size (SE ≈ 0.005). And `corr(tick imbalance, kline imbalance) = 0.9999`: the aggregate
`taker_buy_base ÷ volume` already in the klines is a near-perfect proxy for the tick-level
computation.

**Verdict: no incremental information.** The 51 GB full-history download is not justified. This
closes the last untested data source for a directional futures-only study — OHLCV, taker
volume, trade count, funding, open interest, trader positioning, quarterly futures,
coin-margined perp and now tick prints have all been mined. Only the order book remains, and
that is a market-making dataset rather than a directional-signal one.

## Execution-granularity validation — results hold at 1-minute resolution
Every result in this study resolved stops and targets on **15-minute** bars, with the stop
assumed to fill first whenever one bar straddled both levels. That worst-case rule could cut
either way at finer resolution: fewer bars straddle both levels, but stops also trigger on
wicks a coarse bar smooths over. Downloaded the full **1-minute** perp history (3,506,400 bars,
zero gaps, zero OHLC violations) and re-ran the finalists on it.

| book | exec grid | CAGR | MaxDD | PF | N | Sharpe |
|---|---|---|---|---|---|---|
| S7 SMRD 2.5% | 15m | 22.9% | −18.7% | 1.49 | 229 | 1.14 |
| | **1m** | **21.8%** | **−19.2%** | 1.46 | 229 | 1.10 |
| S15 convex 2% pyr3 | 15m | 37.2% | −36.0% | 1.91 | 261 | 0.95 |
| | **1m** | **36.4%** | **−30.5%** | 1.66 | 283 | 0.93 |

The 15-minute grid was **mildly optimistic on return** (−0.8 to −1.1 pp) and, for the convex
book, **pessimistic on drawdown** (−36.0% at 15m vs −30.5% at 1m — the stop-first rule fires
less often when the path is resolved finely). Net: the headline numbers are robust to
execution granularity, and no conclusion in this study changes.

## S26 — Adaptive Sleeve Allocation — REJECTED
Monthly re-weighting of the four perp sleeves in proportion to trailing risk-adjusted
performance (3/6/12-month lookbacks, Sharpe- and mean-weighted), using only data available
before each month begins.

| scheme (knob 2) | IS CAGR / DD | OOS CAGR / DD | ALL CAGR / DD | Sharpe | Calmar |
|---|---|---|---|---|---|
| **fixed equal weight** | 19.4% / −13.9% | 28.2% / −19.3% | **22.6% / −19.3%** | **1.10** | **1.17** |
| adaptive Sharpe 3m | 20.8% / −15.4% | 21.3% / −19.1% | 21.5% / −19.1% | 1.01 | 1.12 |
| adaptive mean 6m | 24.3% / −16.2% | 24.3% / −24.7% | 24.8% / −24.5% | 0.99 | 1.01 |
| adaptive Sharpe 12m | 21.8% / −14.1% | 24.4% / −18.2% | 22.0% / −18.9% | 1.10 | 1.16 |

**Verdict: FAILS.** No adaptive scheme beats fixed equal weight on Sharpe or Calmar; the
higher-CAGR variants buy it entirely with deeper drawdowns. Relative sleeve performance is not
persistent enough month-to-month to chase.

## S27 — Parameter Ensemble — the one technique that helped
72 configurations of the S7 book (4 thresholds × 3 stops × 3 reward:risk × 2 holding caps) run
simultaneously at 1/N size instead of selecting one.

| | ensemble | median single config | gain |
|---|---|---|---|
| IS Sharpe | **1.54** | 1.34 | **+0.20** |
| OOS Sharpe | **0.80** | 0.73 | +0.07 |
| IS CAGR / DD | 28.1% / −12.2% | 26.5% / −14.1% | — |
| OOS CAGR / DD | 15.0% / −22.2% | 15.6% / −21.8% | — |

**Verdict: helps, modestly.** The ensemble beats the median single configuration in both
windows, and unlike a selected configuration it cannot be the one that happened to fit the
sample. Single-config CAGR ranged from −0.6% to +36.0% out of sample — that spread is exactly
the selection risk S16 exposed. This is the correct default; it does not change the ceiling.

## Market-wide breadth screen — one genuinely new signal
Downloaded 15 liquid USDⓈ-M alt perps (ETH, BNB, SOL, XRP, ADA, DOGE, AVAX, LINK, DOT, LTC,
TRX, BCH, ATOM, NEAR, FIL — 58,440 hours, 99.9% coverage) to use as **sensors only**; BTCUSDT
remains the sole traded instrument.

| feature | h=24 | h=48 | h=96 | note |
|---|---|---|---|---|
| `breadth24` (fraction of alts up over 24h) | **−0.074** | −0.045 | −0.026 | crypto-wide overbought |
| `flow_breadth96` (median 96h taker imbalance across 15 perps) | +0.024 | +0.044 | **+0.062** | vs BTC's own ofi24_z at +0.039 |
| `altrel24` (alt median return − BTC) | −0.063 | −0.053 | −0.034 | |
| `btc_dom` (BTC share of complex volume) | +0.037 | +0.039 | +0.050 | risk-off rotation into BTC |

**Averaging the same measure across 15 instruments beats BTC's own version** (+0.062 vs
+0.039) — more breadth in the *estimator*, not in the bets. `flow_breadth96`'s top decile earns
+131.9 bps over 96h (t=10.9), +115.9 bps net of cost, and correlates only **0.22** with the S7
positioning composite.

**Blending it into the S7 composite made things worse** — combined IC 0.070 vs 0.108 at h=96,
decile spread 135 bps vs 390 bps. This is the S2 failure repeating: equal-weight averaging
drags the strongest signal down toward the weakest. It is therefore run as its own sleeve (S28).

## S28 — Market-Wide Flow Breadth as a standalone sleeve — REJECTED out of sample
`flow_breadth96` z-scored, traded on 4h and 12h bars, 24 variants.

| variant | IS CAGR | OOS CAGR | OOS PF | full CAGR / DD |
|---|---|---|---|---|
| thr 0.4, 5d, long-only | +13.0% | **−13.0%** | 0.80 | +2.4% / −34.4% |
| thr 0.7, 5d, long-only | +10.8% | **−7.3%** | 0.87 | +3.5% / −25.3% |
| thr 1.0, 5d, long/short | +10.4% | **−3.4%** | 0.97 | +4.9% / −30.5% |

**Verdict: FAILS.** Every variant is positive in-sample and negative out-of-sample. The
in-sample decile economics were genuinely strong (top decile +131.9 bps over 96h, t = 10.9,
+115.9 bps net of cost) and they did not survive. This is the sharpest reminder in the study
that **in-sample decile economics are not evidence of out-of-sample tradability** — a t-stat of
10.9 on overlapping 96-hour windows is far weaker evidence than it looks.

## S29 — Conditional Gating instead of averaging — REJECTED
Two results pointed the same way: equal-weight *averaging* diluted the strongest signal twice
(S2 PF 1.30→1.19; S28 blend IC 0.108→0.070), while conditional *gating* worked in S1
(PF 1.04→1.30). Gating leaves the primary untouched and only removes trades the confirmer
disputes. Applied to the S7 positioning book with market-wide flow breadth as confirmer
(correlation 0.22).

| variant | CAGR | DD | PF | N | Sharpe | Calmar | IS | OOS |
|---|---|---|---|---|---|---|---|---|
| **ungated baseline** | **22.9%** | −18.7% | 1.49 | 229 | 1.14 | **1.23** | 22.3% | 24.1% |
| gate "agree" 0.0 | 13.7% | −16.0% | 1.40 | 168 | 0.84 | 0.85 | 16.7% | 9.0% |
| gate "strict" 0.3 | 8.0% | −26.4% | 1.23 | 159 | 0.55 | 0.30 | 15.5% | −3.1% |
| gate "veto" 1.0 | 23.3% | −20.1% | 1.51 | 217 | 1.16 | 1.16 | 24.1% | 22.4% |

**Verdict: FAILS.** Every gate that actually filters makes things worse, and the only variant
that matches the baseline is the weakest possible veto — which removes just 12 of 229 trades,
i.e. converges to doing nothing. The contrast with S1 is the point: gating works when the
confirmer is genuinely predictive, and breadth is not (S28 lost money in every out-of-sample
variant). Gating cannot rescue a signal that has no out-of-sample edge.

---
# Round 5

## IS-vs-OOS IC split — the screen I should have been running all along
Every earlier screen measured IC on in-sample data and used decile economics to decide what to
build. S28 showed that is not enough (top decile t=10.9 in sample, lost money out of sample).
The correct filter is to measure the SAME IC separately in both windows.

| feature | IS h=96 | OOS h=96 | verdict |
|---|---|---|---|
| `tt_vs_retail` (1h) | +0.108 | **−0.054** | collapses, flips sign |
| `retail_rng96` | −0.098 | −0.005 | collapses |
| `oi_vol96` | +0.082 | −0.004 | collapses |
| `tt_pos_rng96_z` | +0.057 | −0.041 | collapses, flips |
| `flow_breadth96` | +0.062 | +0.005 | collapses |
| `ttvr_accel96` | +0.085 | +0.016 | partial |
| `disagree` | +0.076 | +0.003 | partial |

**Almost every feature that looked strong in sample is weak or sign-flipped out of sample.**
Applied earlier this screen would have rejected S28 before a line of strategy code was written.

## Audit of my own headline result
The 1h `tt_vs_retail` reading above flips sign out of sample, yet the S7 strategy built on it
reported IS CAGR 22.3% against OOS 24.1%. Both cannot be innocent, so I checked directly.

**The composite the strategy actually uses degrades but does not collapse** (4h bars, which is
what it trades):
| horizon | IS | OOS |
|---|---|---|
| 96h | +0.0819 | +0.0142 |
| 168h | +0.0720 | +0.0336 |

**But the component doing the work out of sample is not the one the strategy is named after.**
At h=96 on 4h bars: `tt_vs_retail` IS +0.104 → OOS **−0.003**; `−retail_acct_z` IS +0.083 → OOS
**+0.017**; `−tt_acct_z` IS +0.126 → OOS **+0.023**. The "smart-money vs retail" ratio is the
component that stops working; what survives is **fading crowded retail and a crowded count of
top-trader accounts**. The strategy's name overstates what is actually carrying it.

**It is not disguised long-bias beta**, which was the other suspicion:
| window | long trades | long P&L | short trades | short P&L | perp buy & hold |
|---|---|---|---|---|---|
| IS | 56 | +9,501 | 65 | +976 | +94.9% |
| OOS | 55 | +5,453 | 53 | +978 | +25.1% |

Net exposure is −0.07 in sample and +0.02 out of sample, and **the short book is profitable in
both windows** — including out of sample, where the perpetual rose 25%. Shorts making money
into a rising market is genuine alpha, not beta. Longs do contribute 85–91% of gross P&L, so
the book is long-driven, but not long-only in disguise.

**Net effect on the study's conclusion: none.** S7 remains the best book at 22.9% net annual.
But the honest characterisation is weaker than the earlier framing: the edge degrades roughly
three- to five-fold out of sample, and it rests on crowd-fading rather than on following
sophisticated positioning.

## Systematic stability screen — the most useful thing in this study
Applied the IS-vs-OOS IC split to **all 91 features** in the 4h panel, at both a 24h and a 96h
horizon. A feature "survives" only if it keeps its sign in both windows at both horizons and
retains more than 40% of its in-sample strength.

* **Sign-stable at both horizons: 41 of 91 (45%)** — barely better than a coin flip.
* Of the 33 with |IS IC| > 0.04, only 18 (55%) are sign-stable, and the **median out-of-sample
  retention is 0.27**: a strong-looking feature keeps about a quarter of its apparent power.

**Survivors (|IS IC| > 0.03, sign-stable, retention > 40%):**
| feature | IS h=24 | OOS h=24 | IS h=96 | OOS h=96 | retention |
|---|---|---|---|---|---|
| **`oi_rank`** (open-interest percentile, faded) | −0.071 | −0.033 | **−0.137** | **−0.073** | 0.53 |
| **`ofi6_res`** (6-bar flow ⟂ past returns) | +0.039 | **+0.058** | +0.085 | +0.044 | 0.68 |
| `ofi6_resz` | +0.043 | +0.056 | +0.080 | +0.032 | 0.70 |
| **`fund`** (funding, faded) | −0.030 | −0.022 | −0.053 | **−0.060** | 1.13 |
| **`fund3`** | −0.017 | −0.023 | −0.041 | **−0.060** | 1.47 |
| `ofi96_res` | +0.008 | +0.010 | +0.040 | +0.034 | 0.85 |
| `ofi24_res` | +0.038 | +0.023 | +0.042 | +0.020 | 0.55 |

**Biggest in-sample mirages (|IS IC| > 0.06, sign flips out of sample):**
| feature | IS h=96 | OOS h=96 |
|---|---|---|
| **`tt_vs_retail`** — what the study's best book was built on | **+0.104** | **−0.003** |
| `ofi96_resz` | +0.080 | −0.009 |
| `mom168` | +0.068 | −0.014 |

**The uncomfortable conclusion:** the feature I selected the best strategy from is the single
biggest mirage in the panel, and the strongest *stable* feature — open-interest crowding,
`oi_rank`, at IS −0.137 / OOS −0.073 — was screened early, scored well, and never had a
strategy built on it. Selecting on in-sample IC, which is what I did for 29 strategies, is the
wrong selection rule. Funding, faded, is genuinely stronger out of sample than in it.

## S30 — Stability-Screened Composite — and the discovery of the study's best book
Built only from features that passed the stability screen: `−oi_rank`, `+ofi6_res`, `−fund`.
Each component was also traded alone.

**4h bars (risk 2.5%):**
| book | CAGR | DD | PF | N | Sharpe | IS | OOS | OOS PF |
|---|---|---|---|---|---|---|---|---|
| `−oi_rank` thr0.7 10d | 8.1% | −32.2% | 1.13 | 366 | 0.48 | 6.5% | 11.2% | 1.15 |
| **`ofi6_res` thr0.7 5d** | **22.9%** | −24.3% | 1.29 | **810** | 0.99 | **23.5%** | **21.9%** | 1.27 |
| `ofi6_res` thr1.0 10d | 17.8% | −25.5% | 1.27 | 553 | 0.83 | **17.7%** | **17.6%** | 1.28 |
| `−fund` thr0.7 5d | 5.7% | −36.0% | 1.08 | 574 | 0.37 | 15.6% | **−8.6%** | 0.92 |
| COMPOSITE thr0.7 5d | 12.2% | −26.4% | 1.18 | 378 | 0.69 | 17.6% | 4.1% | 1.08 |

**12h bars (risk 2.5%):**
| book | CAGR | DD | PF | N | Sharpe | Calmar | IS | OOS | OOS PF |
|---|---|---|---|---|---|---|---|---|---|
| **`ofi6_res` thr0.7 10d** | 16.9% | **−17.4%** | **1.62** | 259 | **1.31** | 0.97 | 20.3% | 11.7% | 1.38 |
| `ofi6_res` thr1.0 10d | 12.0% | −16.7% | 1.58 | 200 | 1.01 | 0.72 | **11.6%** | **13.2%** | 1.56 |
| COMPOSITE thr0.7 10d | 10.9% | −17.3% | 1.68 | 132 | 1.04 | 0.63 | 11.8% | 9.5% | 1.49 |

Three results worth separating:

1. **`ofi6_res` is the best single book in the study.** Sharpe **1.31** on 12h (against S7's 1.14),
   profit factor 1.62, drawdown inside the 20% limit, and the tightest IS/OOS agreement anywhere
   here — 11.6% vs 13.2% at thr1.0, 23.5% vs 21.9% on 4h. It also trades 3.5× more often than S7.

2. **Blending diluted again — the third time.** The equal-weight composite of the three
   stability-screened features is worse than `ofi6_res` alone on every measure (OOS 4.1% vs
   21.9% at 4h). S2, the breadth blend and now this: averaging signals of unequal strength is
   a reliable way to make the strong one worse.

3. **A stable IC does not guarantee a tradable strategy.** `−fund` passed the stability screen
   with the *highest* retention in the panel (1.13–1.47, stronger out of sample than in) and
   still loses money out of sample (−8.6%, PF 0.92). Its IC is real but too small (|0.05|) to
   survive a 16 bps round turn. Stability is necessary, not sufficient — magnitude matters too.

## S31 — Short-Window Orthogonal Flow — **the best book in the study**
Full parameter map over 3 timeframes × 3 thresholds × 3 stop/target pairs × 2 holding caps
(54 configurations). Best by drawdown-penalised Sharpe: **12h, thr 1.0, stop 3.0×ATR, target
2.0R, 7-day time stop.**

| risk | CAGR | MaxDD | PF | N | WR | Sharpe | Calmar | IS | OOS (PF) |
|---|---|---|---|---|---|---|---|---|---|
| 2.5% | 15.9% | −14.3% | 1.61 | 234 | 53.0% | **1.23** | 1.11 | 14.7% | **18.6%** (1.60) |
| **3.5%** | **22.4%** | **−19.6%** | 1.60 | 234 | 53.0% | 1.23 | 1.14 | 20.7% | **26.2%** (1.59) |
| 4.5% | 28.8% | −24.6% | 1.59 | 234 | 53.0% | 1.23 | 1.17 | 26.7% | 33.8% (1.58) |

**Robustness:**
* Cost stress: 15.9% → 14.7% → 13.3% at 1×/1.5×/2× costs; **PF 1.61 → 1.57 → 1.53**.
* Yearly: 2021 +13%, 2022 **−1%**, 2023 +32%, 2024 +6%, 2025 +34%, 2026 +10% — positive in
  five of six years, worst year −1%.
* Bootstrap (risk 2.5%): median DD −15.8%, 5th pct −26.3%, P(DD>20%) 21%.
* The whole 12h/thr-1.0 neighbourhood holds PF 1.55–1.63 with positive OOS in every cell — a
  robust region, not one lucky configuration.

**Against the previous best (S7):** PF 1.60 vs 1.49, Sharpe 1.23 vs 1.14, OOS CAGR 26.2% vs
24.1%, PF at double costs 1.53 vs 1.43, at comparable CAGR and drawdown.

**One honest caveat.** The traded signal's own rank-IC degrades out of sample much as
`tt_vs_retail`'s did: +0.112 in-sample vs +0.013 out, at h=96. The *strategy* nevertheless
does better out of sample. The reason is that it trades only the tails beyond |z|>1 and shapes
the payoff with a stop and a target, and full-distribution rank-IC says nothing about tail
behaviour. So the stability screen earned its keep by **pointing at an under-explored feature
family**, not by predicting strategy performance directly — the claim "stable IC implies stable
strategy" is not supported by this study's own evidence, in either direction.

### S31 — remaining validation
**1-minute execution grid** (3,506,400 bars) against the 15-minute grid used throughout:
| config | 15m CAGR / DD / PF | 1m CAGR / DD / PF |
|---|---|---|
| 12h thr1.0 3.0×2.0 7d | 15.9% / −14.3% / 1.61 | **15.5% / −14.8% / 1.59** |
| 12h thr1.0 3.0×2.0 12d | 14.1% / −16.5% / 1.63 | 13.8% / −17.3% / 1.62 |
| 6h thr1.3 3.5×2.5 7d | 20.0% / −21.0% / 1.45 | 18.8% / −21.0% / 1.41 |

Differences of 0.3–1.2 pp of CAGR and under a point of drawdown. The book is not an artefact of
coarse stop resolution.

**Alternative configurations considered and rejected:**
* `12h … 12d` — slightly higher PF (1.63) but drawdown −22.5% at the same risk, bootstrap
  P(DD>20%) 30%, and a worse worst-year (−7% vs −1%).
* `6h thr1.3` — **higher out-of-sample IC** (+0.036 at h=24 vs +0.006 for the 12h book) yet
  *worse* strategy performance out of sample (17.0% vs 18.6%), a −21.0% drawdown and bootstrap
  P(DD>20%) of **61%**. A second, independent instance of IC stability failing to predict
  strategy quality — in the opposite direction this time.

Chosen: **12h, thr 1.0, stop 3.0×ATR, target 2.0R, 7-day stop, risk 3.5%.**

## S32 — Flow + Positioning pair — **the best futures-only result in the study**
The two best books read different things and share no input series: S31 reads aggressive flow
(taker imbalance orthogonalised to returns, 12h), S7 reads positioning (how crowded retail and
top-trader accounts are, 4h). In-sample daily-return correlations:

| | FLOW | POSN | CONVEX |
|---|---|---|---|
| FLOW | 1.00 | **0.30** | **0.30** |
| POSN | 0.30 | 1.00 | 0.71 |

FLOW is genuinely diversifying against both positioning books, which correlate 0.71 with each
other. Two sub-accounts, monthly rebalance, inverse-vol weights fixed in-sample (FLOW 52%,
POSN 48%):

| knob | IS CAGR / DD | OOS CAGR / DD | ALL CAGR / DD | PF | Sharpe | Calmar | N |
|---|---|---|---|---|---|---|---|
| 1 | 22.2% / −13.5% | 26.0% / −11.4% | 23.4% / −13.5% | 1.26 | 1.42 | 1.73 | 463 |
| **1.5** | 34.1% / −19.7% | **39.8% / −16.6%** | **35.8% / −19.7%** | 1.25 | **1.43** | **1.82** | 463 |
| 2 | 46.3% / −25.5% | 54.0% / −21.6% | 48.7% / −25.5% | 1.24 | 1.43 | 1.91 | 463 |
| 3 | 71.8% / −36.0% | 83.0% / −30.8% | 75.1% / −36.0% | 1.23 | 1.44 | 2.09 | 463 |

Yearly at knob 2: 2021 +90%, 2022 **−5%**, 2023 +76%, 2024 +39%, 2025 +45%, 2026 +46%.

**Sharpe 1.43 and Calmar 1.82 are the highest futures-only figures in this study** — against
1.23 / 1.14 for the best single book and 1.12 / 1.17 for the earlier four-sleeve portfolio,
which was dragged down by having three correlated directional books in it. Pairing two
genuinely different reads beats stacking four similar ones.

At knob 1.5 the portfolio clears three of the five numeric gates — 463 trades, PF 1.25,
drawdown −19.7% — and misses net yearly profit at **35.8% against 300%**. That is a 60%
improvement on the previous futures-only best (22.4%) at the same drawdown, and still 8.4×
short of the target. Bootstrap P(DD>20%) is 98% at knob 2, so knob 1.5 is the practical ceiling
and even there the drawdown margin is thin.

## S33 — Adding the open-interest sleeve
`oi_rank` (open-interest percentile, faded) is the strongest *stable* feature in the panel
(IS −0.137 / OOS −0.073) but a weak book alone: 8.1% CAGR, PF 1.13, −32% drawdown. The
question was whether a weak-but-different read still earns portfolio weight.

**Correlation with the existing sleeves: 0.078 (FLOW), 0.111 (POSN), 0.131 (CONVEX)** —
near-orthogonal to all three, because it reads the *size of the levered book* rather than flow
or account positioning.

| knob | IS CAGR / DD | OOS CAGR / DD | ALL CAGR / DD | PF | Sharpe | Calmar | N | P(DD>20%) |
|---|---|---|---|---|---|---|---|---|
| 1 | 17.9% / −11.5% | 25.3% / −10.1% | 20.5% / −11.5% | 1.31 | **1.41** | 1.78 | 1090 | — |
| 1.5 | 27.3% / −16.9% | 38.6% / −14.8% | 31.2% / −16.9% | 1.30 | **1.41** | 1.85 | 1090 | **52%** |
| 2 | 35.4% / −21.9% | 52.1% / −19.3% | 41.1% / −21.9% | 1.29 | 1.39 | 1.87 | 1092 | — |

Sized to the drawdown limit for a like-for-like comparison:

| portfolio | size | CAGR | MaxDD | PF | N | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|---|---|
| S32, 3 sleeves | 1.5 | **38.6%** | −19.0% | 1.27 | 724 | 1.34 | **2.03** | — |
| S33, 4 sleeves | 1.7 | 35.6% | −18.9% | 1.30 | 1090 | **1.41** | 1.88 | 68% |
| S33, 4 sleeves | 1.8 | 37.8% | −19.9% | 1.30 | 1090 | **1.41** | 1.90 | 75% |

S33 at knob 1.8 yearly: 2021 +50%, 2022 **−3%**, 2023 +56%, 2024 +55%, 2025 +18%, 2026 +48%.

**Verdict: essentially a tie on return, a clear win on risk.** At matched drawdown the two are
within a point of each other on CAGR (38.6% vs 37.8%), but the four-sleeve version carries a
higher Sharpe (1.41 vs 1.34), higher profit factor (1.30 vs 1.27), 50% more trades and a
shallower worst year (−3% vs −8%). The three-sleeve version keeps a marginally better Calmar.
Either is defensible; neither is close to the target.

The useful generalisation: **a sleeve with almost no standalone edge but near-zero correlation
is worth more to a portfolio than a strong sleeve correlated 0.7 with what you already hold.**
That is why the original four-sleeve portfolio (four correlated directional books, Sharpe 1.12)
was beaten by a two-book pair reading different things (Sharpe 1.43).

## Order-book imbalance — the last data source, and the sharpest lesson in the study
24 days of `bookTicker` (top-of-book quotes) streamed and reduced to 34,547 minute bars across
four month-blocks, 2023-06 → 2024-02. Binance stopped publishing these daily files after early
2024, so the whole sample sits inside the in-sample window; the four blocks are split
early-vs-late as the nearest available substitute for an out-of-sample test.

Market context measured directly: **mean quoted spread 0.034 bps** (BTCUSDT perp is usually one
tick wide), mean top-of-book depth **$582,481**, **11,744 quote updates per minute**.

| feature | early h=1m | late h=1m | early h=15m | late h=15m |
|---|---|---|---|---|
| **`obi_last`** (imbalance at the minute's last quote) | **+0.1079** | **+0.0811** | +0.0268 | +0.0236 |
| `obi` (minute mean) | +0.0250 | +0.0095 | −0.0174 | +0.0065 |
| `micro_dev` (microprice − mid) | +0.0250 | +0.0030 | −0.0176 | −0.0052 |
| `spread_bps` | +0.0111 | +0.0004 | +0.0499 | +0.0089 |
| `kline_imb` (baseline) | −0.0161 | −0.0108 | −0.0371 | −0.0132 |

**`obi_last` is the strongest stable predictor found anywhere in this entire study** — IC
**+0.108** in the early blocks and **+0.081** in the late ones, holding its sign and most of its
magnitude, which almost nothing else did.

**And it is completely untradable.** The decile economics:

| signal | horizon | D1 | D10 | spread | vs cost |
|---|---|---|---|---|---|
| `obi` | 1 min | −0.08 bps | +0.08 bps | **+0.16 bps** | 16 bps |
| `obi` | 60 min | +0.35 bps | +1.58 bps | **+1.23 bps** | 16 bps |
| `micro_dev` | 5 min | −0.01 bps | −0.59 bps | −0.58 bps | 16 bps |

The predictable move is **two orders of magnitude smaller than the round turn**. Even at maker
fees (≈3.6 bps round trip, tested earlier) the 60-minute decile spread of 1.23 bps does not
clear.

**This is the study's clearest separation of statistical significance from economic
significance.** Order-book imbalance is real, strong and stable — and it is a *market maker's*
signal, not a taker's. A maker earns the spread and is paid for providing liquidity; the
imbalance tells them which side to skew. A taker must cross that spread and pay fees, and no
amount of predictive accuracy at a one-minute horizon recovers 16 bps from a 0.16 bps move.

With this, **every data source Binance publishes for BTCUSDT has been mined**: OHLCV, taker
volume, trade count, funding, open interest, trader positioning, quarterly futures, the
coin-margined contract, tick prints, and now the order book.

## S34 — Attacking the drawdown instead of the return (portfolio risk overlays)
Calmar = CAGR / MaxDD and leverage moves both together, so the only way leverage buys anything
is if the *shape* of the equity curve can be changed. Two causal overlays were applied to the
S32 portfolio's own daily returns, each computed from data through day t−1 and applied to day t:

| overlay | knob | CAGR | MaxDD | PF | Sharpe | Calmar |
|---|---|---|---|---|---|---|
| none | 1.5 | 38.6% | −19.0% | 1.27 | 1.34 | **2.03** |
| vol target 20% | 1.5 | 33.6% | −17.8% | 1.27 | **1.39** | 1.89 |
| vol target 25% | 1.5 | 42.7% | −21.9% | 1.26 | **1.39** | 1.95 |
| vol target 30% | 1.5 | 51.2% | −26.1% | 1.25 | **1.39** | 1.96 |
| HWM drawdown throttle 8/22 | 1.5 | 30.4% | −16.6% | 1.23 | 1.20 | 1.83 |
| HWM drawdown throttle 6/18 | 3.0 | 20.4% | −21.0% | 1.14 | 0.77 | 0.97 |

**Volatility targeting is Calmar-neutral here.** It does exactly what it should — the three
target levels trace a clean, near-linear risk dial (34%/18%, 43%/22%, 51%/26%) and the base
leverage knob stops mattering entirely once the overlay is on, which is the correct signature of
a working vol target. Sharpe improves 1.34 → 1.39 and out-of-sample drawdown tightens. But CAGR
falls in step with drawdown, so Calmar does not move. **The reason is that the sleeves already
size every trade by ATR**, so the equity curve is close to homoskedastic before the overlay ever
sees it; portfolio-level vol targeting is largely redundant with trade-level vol sizing.

**The high-water-mark throttle actively destroys the book.** Sharpe collapses from 1.34 to
0.77–1.20 and at higher knobs the drawdown gets *worse*, not better. Cutting size in a drawdown
means being small through the recovery, and for a book whose losses are not serially correlated
that is a pure tax. Recorded as a clean negative: **do not de-risk into drawdowns on a
mean-reverting-equity strategy.**

## S35 — Maker execution: does a resting limit order unlock the fast end?
Every book so far crossed the spread twice (≈4.5 bps fee + ≈3.5 bps slippage per side = 16 bps
round turn). A resting limit order pays ≈1.8 bps a side — 3.6 bps round turn, **4.4× cheaper**.
Since Sharpe ≈ IC × √(bets/year) and the sleeves take only ~85 bets a year, cheap execution is
the one thing that could open up the thousands-of-bets regime.

A new engine (`engine/maker.py`) was built on 1-minute bars: an order is posted at the first
minute after the decision bar closes, fills only when a later minute trades **strictly through**
the limit, is cancelled after a TTL, exits at a resting limit (maker fee) or a market stop
(taker fee + slippage), and takes the stop when a minute's range covers both.

Full grids of a 5-minute short-term-reversal book across thresholds, offsets, R:R and both
polarities returned **profit factor 0.36–0.81 — every single configuration lost**, most blowing
the account. Rather than tune, the raw edge was isolated directly: for every fill, the mean
forward return from the fill price, before any stop or target.

| limit offset | fill rate | +5m | +15m | +30m | +60m | +120m |
|---|---|---|---|---|---|---|
| 0.25 σ (fade) | 85% | −0.39 | −0.37 | −0.41 | −0.69 | −0.72 |
| 0.50 σ (fade) | 75% | +0.10 | +0.15 | +0.22 | −0.14 | −0.30 |
| **1.00 σ (fade)** | **57%** | **+0.84** | **+1.06** | **+1.18** | +0.63 | +0.48 |
| 1.00 σ (fade, 2σ trigger) | 69% | +1.15 | +1.19 | **+1.57** | +1.06 | +0.52 |

(bps; against a **3.6 bps** maker round turn.)

The trade-off is textbook and perfectly monotone: the deeper the order rests, the better the
fill-conditional edge and the lower the fill rate. **And the best point on that curve is
+1.57 bps against a 3.6 bps cost — less than half of what is needed.** Fading beats joining at
every offset, so short-term reversal is the right sign; there is just almost nothing there.

Note on the fill rule: modelling "fill on touch" instead of "fill on penetration" changes
nothing, because a limit placed at a continuous price (close − 0.5σ) is essentially never
exactly equal to a bar's low. The conservative and optimistic bounds coincide.

**Taken with the order-book result, this closes the fast end from two independent directions.**
The order book says the *information* at a 1-minute horizon is worth 0.16 bps; the maker engine
says the *execution* saving is worth 12.4 bps but the fill-conditional edge only 1.6 bps. Retail
high-frequency trading on BTCUSDT is not blocked by one of cost or signal — it fails on both.

## S36 — Implied volatility: the one input class the study had never touched
Correcting the previous entry: Binance publishes one more BTCUSDT-relevant series, and it is
not a price series at all. **BVOL** is a 30-day forward-looking implied volatility index for BTC,
a VIX analogue, published as 1-second ticks. 1,152 daily files were streamed and reduced to
**1,656,492 minute bars covering 2023-06-20 → 2026-09-09**. Everything else in this study is
*realised* — prices, taker flow, open interest, positioning, funding. This is the market's
*price* of future risk.

Measured directly over the window: **mean IV 51.4%, mean realised vol 42.7%, mean variance risk
premium +8.7 percentage points.** The VRP is real and positive in BTC, exactly as in equities —
but it is a premium for *selling options*, and this study trades futures, so it is not directly
harvestable here.

As directional signals for the perp, most IV features are unstable — the level, the premium and
the IV/RV ratio all flip sign between in- and out-of-sample. One does not:

| signal (12h bars, h = 1 day) | IS IC | OOS IC |
|---|---|---|
| iv (level, z-scored) | +0.062 | +0.039 |
| vrp (IV − realised) | −0.031 | +0.013 |
| iv_rv (ratio) | −0.036 | +0.008 |
| **iv_mom** (3-day IV change) | **+0.046** | **+0.091** |
| **iv_mom_res** (orthogonalised to price momentum) | **+0.083** | **+0.090** |
| price momentum (same lookback) | −0.016 | −0.028 |

**iv_mom is not a price-momentum proxy.** The two correlate −0.10, price momentum's own IC is
*negative* over this window, and projecting price momentum out (expanding-window fit, refit
monthly on strictly past data — the S31 construction) *raises* the IC from +0.046 to +0.083
rather than lowering it. What is left is the options market repricing risk before the perp moves.

Decile economics at a 1-day horizon: **D1 −22 bps, D10 +22 bps, spread +44 bps against a 16 bps
round turn.** Nearly 3× cost — the first feature in the study to clear its hurdle by that margin.

Backtested as a book (12h decision, 15m execution, 3 ATR stop, 2R target, risk 2%):

| variant | ALL CAGR | DD | PF | N | Sharpe | IS CAGR / PF | OOS CAGR / PF / N |
|---|---|---|---|---|---|---|---|
| **raw, thr 0.7** | **15.6%** | **−8.0%** | **1.61** | 201 | **1.41** | 26.0% / 2.10 | **11.0% / 1.45 / 142** |
| raw, thr 1.0 | 10.0% | −9.9% | 1.42 | 166 | 0.98 | 15.2% / 1.58 | 7.6% / 1.34 |
| residual, thr 0.7 | 10.5% | −9.5% | 1.45 | 187 | 1.06 | 13.1% / 1.90 | 9.3% / 1.35 |

An honest wrinkle: **the residual has the better IC but the raw signal makes the better book.**
The monthly refit adds estimation noise that a 3.2-year sample cannot absorb, and the raw series
is what gets traded. Sample caveat stated up front: BVOL begins 2023-06-20, so this book has
3.2 years where the others have 5.7 — but 2.17 of those years are out-of-sample, so most of its
life is out of sample, which is the opposite of the usual problem.

## S37 — The IV sleeve in the portfolio: the best result in the study
Standalone the IV book is modest (15.6% CAGR). What matters is that it reads something nothing
else reads. Daily-return correlations over the common window 2023-06-21 → 2026-08-31:

| | FLOW | POSN | CONVEX | IVOL |
|---|---|---|---|---|
| FLOW | 1.000 | 0.436 | 0.455 | **0.087** |
| POSN | 0.436 | 1.000 | 0.722 | **0.172** |
| CONVEX | 0.455 | 0.722 | 1.000 | **0.231** |

Inverse-volatility weights fixed in-sample give IVOL 40.9% of the book (it has the lowest
volatility). Like-for-like on the *same* window, so the shorter sample cannot flatter the
comparison:

| sleeves | knob | CAGR | MaxDD | PF | Sharpe | Calmar | N |
|---|---|---|---|---|---|---|---|
| FLOW+POSN+CONVEX | 1.5 | 49.2% | −18.1% | 1.29 | 1.49 | 2.72 | 517 |
| FLOW+POSN+CONVEX | 2.5 | 84.4% | −28.2% | 1.27 | 1.49 | 2.99 | 519 |
| **+IVOL** | 1.5 | 39.9% | −11.4% | 1.37 | **1.78** | 3.51 | 718 |
| **+IVOL** | 2.0 | 54.9% | −14.9% | 1.36 | **1.78** | 3.68 | 718 |
| **+IVOL** | 2.6 | **73.7%** | **−19.0%** | 1.35 | **1.78** | **3.87** | 720 |

**At matched drawdown the IV sleeve is worth roughly +40% of return**: ≈51% CAGR without it at
−19% drawdown versus ≈74% with it. Sharpe 1.49 → 1.78, Calmar 2.99 → 3.87. Yearly, at knob 2.6:
2023 +34%, 2024 +75%, 2025 +56%, 2026 +59% — no losing year, though the window excludes 2022.

**The drawdown must be read from the bootstrap, not the sample.** A stationary block bootstrap
(2,000 paths, 5-day blocks) says the −19.0% realised figure badly understates the risk:

| knob | CAGR | realised DD | bootstrap median DD | 5th pct | P(DD worse than 20%) |
|---|---|---|---|---|---|
| **1.5** | **39.9%** | −11.4% | **−15.6%** | −26.2% | **19%** |
| 2.0 | 54.9% | −14.9% | −20.3% | −33.4% | 52% |
| 2.6 | 73.7% | −19.0% | −25.7% | −41.4% | 84% |

So the honest headline is **≈40% a year at a genuine sub-20% drawdown**, not 74%. Taking the
74% means accepting an 84% chance of breaching the 20% limit — which fails the brief's risk
criterion even though the backtest's realised number passes it.

**Still nowhere near 300%.** But it is the first structural improvement in a long while, and it
confirms the study's central lesson for the third time: *a sleeve's correlation to what you
already hold matters more than its standalone quality.* IVOL is the weakest book here on
standalone CAGR and the most valuable one in the portfolio.

## S38–S41 — Stop looking for a better signal, look for a different one
Going from three sleeves to six took the portfolio's Sharpe from 1.36 to 2.13 purely through
decorrelation. So the search was reframed: **not "what is the best signal" but "what else is
different".** Four input families the study had data for but had never built a sleeve from:

| candidate | what it reads | IS CAGR / PF | OOS CAGR / PF | verdict |
|---|---|---|---|---|
| **CMPX** | log(BTCUSD_PERP / BTCUSDT_PERP) momentum — BTC cancels, leaving the implied **USDT/USD rate** | 5.4% / 1.20 | **20.0% / 1.82** | kept |
| CMDIV | coin-margined funding minus USDT funding | 6.4% / 1.47 | −2.6% / 0.97 | rejected |
| TERM | annualised front-quarterly basis over the perp | 0.6% / 1.07 | 2.2% / 1.14 | too weak |
| **ETHREL** | fade ETH's 3-day outperformance of BTC | 2.0% / 1.08 | **10.9% / 1.50** | kept, with reservations |
| BREADTH | share of the alt complex participating | −2.7% / 0.98 | −15.3% / 0.76 | rejected outright |

Then **every one of the 116 panel features** was put through the *same* standard book — 12h
decision, 15m execution, 1.0 z threshold, 3 ATR stop, 2R target, 7-day cap — with nothing tuned
per feature and the sign chosen in-sample only. 50 produced enough trades to judge; 22 beat OOS
PF 1.10; 13 beat 1.30. **Multiple-testing warning stated before, not after, the results:** at a
5% false-positive rate ~10 of these are luck, so in-sample rank was used only to order the queue
and nothing was kept unless it also cleared out of sample.

Two survivors were worth adding:

| sleeve | corr to incumbent | IS PF | OOS PF | ALL CAGR / DD / Sharpe |
|---|---|---|---|---|
| **BTCDOM** — BTC's share of dollar turnover across the perp complex | **0.11** | 1.51 | 1.25 | 13.1% / −10.4% / **1.11** |
| **FUNDZ** — fade the funding-rate z-score | **−0.03** | 1.21 | 1.10 | 3.8% / −14.8% / 0.44 |

`btc_dom` was inherited from an earlier build script with no surviving source, so its definition
was **verified by reconstruction**: BTC quote volume / (BTC + 15 alts quote volume) reproduces
the stored series at correlation 1.0000, maximum absolute difference 0.000000. Sign +1 — when
capital rotates *into* BTC and out of the alt complex, BTC leads. FUNDZ is weak and earns its
place entirely through being the only sleeve in the study **negatively** correlated with the rest.

### Look-ahead audit of every new sleeve
Three tests on the live harness: an oracle control fed literal next-bar returns, each real
signal shifted one bar *earlier* (peeking), and each delayed one bar.

| sleeve | as traded | peek 1 bar | delayed 1 bar | reading |
|---|---|---|---|---|
| oracle control | Sharpe **20.12**, PF 102.5 | — | — | the harness *can* express a leak |
| CMPX | 0.99 | **2.20** | 0.42 | textbook gradient, clean |
| BTCDOM | 1.11 | **1.32** | 0.27 | textbook gradient, clean |
| IVOL | 0.98 | 0.85 | 0.70 | flat — slow signal, no bar-timing content |
| ETHREL | 0.57 | 0.01 | 0.48 | flat — weak signal, fragile |
| FUNDZ | 0.44 | 0.24 | 0.24 | flat — a persistent tilt, not a timed entry |

A flat gradient is *not* evidence of leakage (leakage shows up as peeking adding nothing because
the future is already in the signal), but it does say those three sleeves have no sharp timing
content and are therefore the fragile ones. Recorded as such rather than smoothed over.

**Selection honesty on S36:** the winning IV configuration (thr 0.7, 3 ATR × 2R) was picked from
a grid that printed IS, OOS and ALL side by side, so out-of-sample numbers were visible at the
moment of choosing. Re-checking on in-sample alone: thr 0.7 wins regardless of the stop/target
pair, and all three stop/target pairs hold up out of sample (PF 1.31 / 1.45 / 1.41). The concern
is real but small, and it is disclosed rather than buried.

### The seven- and eight-sleeve books
Correlations across the seven sleeves available on the full window average **0.10**, with three
pairs negative:

| | FLOW | POSN | CONVEX | CMPX | ETHREL | BTCDOM | FUNDZ |
|---|---|---|---|---|---|---|---|
| FLOW | 1.000 | 0.384 | 0.380 | 0.144 | −0.094 | 0.086 | 0.001 |
| POSN | | 1.000 | 0.701 | 0.258 | 0.024 | 0.057 | 0.006 |
| CONVEX | | | 1.000 | 0.287 | −0.055 | 0.043 | −0.062 |
| CMPX | | | | 1.000 | −0.090 | 0.042 | −0.089 |
| ETHREL | | | | | 1.000 | 0.132 | 0.074 |
| BTCDOM | | | | | | 1.000 | 0.042 |

**Full window, 2021-03 → 2026-08 (5.5 years, includes the 2022 bear market), seven sleeves:**

| knob | CAGR | MaxDD | PF | Sharpe | Calmar | N | boot median DD | P(DD>20%) |
|---|---|---|---|---|---|---|---|---|
| 2.0 | 26.0% | −12.6% | 1.42 | 1.84 | 2.07 | 2129 | −11.1% | **2%** |
| **3.0** | **40.3%** | **−18.5%** | 1.42 | **1.84** | **2.18** | 2132 | −16.4% | 23% |
| 4.0 | 47.3% | −22.8% | 1.43 | 1.86 | 2.07 | 2132 | −18.5% | 37% |
| 5.0 | 54.3% | −27.2% | 1.43 | 1.86 | 1.99 | 2132 | −20.8% | 56% |

Yearly at knob 3.0: 2021 +34%, **2022 −8%**, 2023 +71%, 2024 +46%, 2025 +40%, 2026 +50%.
Calmar peaks at knob 3.0 and *falls* beyond it — the Kelly ceiling again, in a new place.

**BVOL window, 2023-06 → 2026-08 (3.2 years, no bear market), eight sleeves:**

| knob | CAGR | MaxDD | PF | Sharpe | Calmar | N | boot median DD | P(>20%) | P(>30%) |
|---|---|---|---|---|---|---|---|---|---|
| 4.5 | 69.6% | −13.3% | 1.52 | 2.32 | 5.22 | 1582 | −14.8% | **13%** | 0% |
| 5.5 | 83.0% | −14.6% | 1.52 | 2.33 | 5.67 | 1582 | −16.7% | 25% | 1% |
| 6.5 | 97.4% | −16.6% | 1.52 | 2.32 | 5.86 | 1582 | −18.9% | 40% | 4% |
| **8.0** | **120.7%** | **−19.8%** | **1.51** | **2.32** | **6.09** | 1582 | −22.1% | 66% | 11% |

In-sample 122.1% against out-of-sample 119.7% — as close as any result in this study.

**The gap between the two tables is almost entirely 2022.** Calmar 2.18 on the full window
against 6.09 on the short one, from the same machinery. The eight-sleeve book's headline number
is real but it lives on a window that excludes the one regime that hurt it, and the honest
reading is the pair, not the better half.

**Dropping any single sleeve makes it worse** — no one book is carrying the result:

| sleeve set (BVOL window, knob 2.5) | CAGR | Sharpe | P(DD>20%) |
|---|---|---|---|
| all six | 51.7% | **2.13** | **8%** |
| drop ETHREL | 60.7% | 1.90 | 38% |
| drop CMPX | 55.3% | 2.02 | 24% |
| drop IVOL | 52.9% | 1.92 | 28% |
| **the three NEW sleeves alone** | 35.0% | 2.00 | **2%** |

The last row is the striking one: IVOL + CMPX + ETHREL on their own, with none of the original
books, reach Sharpe 2.00 at a 2% chance of a 20% drawdown.

### The ceiling this implies
With average pairwise correlation ρ̄ and per-sleeve Sharpe s, a portfolio of k sleeves tends to
**s / √ρ̄** as k grows. Measured here: s ≈ 0.9–1.1, ρ̄ ≈ 0.10 → **a Sharpe ceiling near 2.8–3.2**,
against 2.32 already achieved with eight. Calmar ran at ≈ 2.6 × Sharpe on the short window, so
the implied ceiling is **Calmar ≈ 8, i.e. roughly 160% a year at a 20% drawdown** — and only on a
window without a bear market. On the full window the same arithmetic gives Calmar ≈ 2.2 and
~45%. Adding sleeves nine, ten and eleven cannot close a 300% gap; the limit is set by ρ̄, and
ρ̄ is a property of the market, not of the search.

## S42 — Phase diversification: the free lunch that is not there
A 12h book decides at 00:00 and 12:00 UTC. Nothing makes those instants special. Running the
identical signal on bars cut at 03:00, 06:00 and 09:00 gives a different trade sequence from the
same information — different fills, different stops, different which-side-of-the-bar luck. That
is pure timing luck and should be diversifiable at no cost in signal quality.

| IVOL phase | CAGR | DD | PF | N | Sharpe |
|---|---|---|---|---|---|
| 00h | 5.2% | −14.9% | 1.20 | 209 | 0.53 |
| 03h | 2.4% | −13.1% | 1.10 | 213 | 0.27 |
| **06h** | **8.0%** | −12.9% | **1.27** | 206 | **0.76** |
| 09h | 2.9% | −13.9% | 1.12 | 212 | 0.32 |
| four-phase average | 4.7% | −12.7% | — | — | 0.51 |

**Cross-phase correlation is 0.70–0.82**, so there is almost nothing to diversify: the four-phase
average lands at Sharpe 0.51 against a mean-of-singles 0.47, exactly the +0.04 that
s√k / √(1+(k−1)ρ) predicts at ρ = 0.76. A 12h signal's persistence swamps its timing luck.

Two things worth keeping from a negative result. First, **the diversification arithmetic behaves
exactly as theory says it should**, which is a direct check on the machinery that produced the
cross-sleeve gains. Second, the spread across phases — Sharpe 0.27 to 0.76 from *the same
strategy on the same data* — is a blunt warning about how much of any single book's headline
number is the accident of where the bars were cut.

## Constraint change: single account, one position
The brief was corrected mid-study — **no portfolios; one account, one position.** Everything from
S32 to S44 ran the sleeves as separate sub-accounts rebalancing monthly, which is not tradable
that way. So the same idea was rebuilt as a single strategy: every signal reduced to one number
on one 12h grid, one net BTCUSDT position at a time, one stop, one target.

**Netting turned out to be better than the sub-account structure, not a compromise.** Profit
factor rose from **1.51 to 2.09**, because opposing signals cancel *before* anything is traded
instead of both being opened and both paying a round turn. Sharpe rose from 1.84 to 2.13 on the
same window. The three previous failures of signal blending (S2, the breadth blend, the S30
composite) all averaged *correlated* signals; averaging near-orthogonal ones is a different
operation and it works.

## S43 — Lifting the other term: conviction sizing
Portfolio Sharpe tends to s/√ρ̄ and ρ̄ will not move, so the remaining lever is s. The engine had
been discarding information it already held: every book emitted a z-score and then collapsed it
to ±1 at the entry, so a 3σ signal and a 1.01σ signal were the same bet. Letting |z| scale the
risk budget — capped, so no single signal can take the account:

| book | base Sharpe | conviction | IS | OOS |
|---|---|---|---|---|
| IVOL | 1.41 | **1.61** | 2.05 → 2.14 | 1.07 → **1.33** |
| CMPX | 0.99 | **1.27** | 0.54 → 0.93 | 1.64 → **1.75** |
| FLOW | 1.22 | 1.26 | 1.16 → 1.19 | 1.35 → **1.41** |
| BTCDOM | 1.11 | 1.13 | 1.33 → 1.30 | 0.72 → **0.82** |

Out-of-sample Sharpe improved on **all four**. Profit factor rose on all four too (IVOL
1.61→1.73, CMPX 1.46→1.68). The engine change was regression-tested against S31's published
numbers — CAGR 22.4%, DD −19.6%, PF 1.60, N 234, Sharpe 1.23 — reproduced exactly, since books
emitting ±1 have |entry| = 1 and are unaffected.

**The instructive contrast:** conviction *filtering* fails where conviction *sizing* works.
Trading only |z| > 1.5× threshold roughly halves Sharpe on every book (IVOL 1.41→0.92, BTCDOM
1.11→0.25). So the extremes do not carry the edge — the edge is monotone in |z| and the
*ordering* is the information. That is what a real IC looks like, and it is a stronger check on
the signals than any single backtest.

Two other sizing ideas failed cleanly. A HAR-style volatility forecast (0.4·daily + 0.35·weekly
+ 0.25·monthly realised vol) replacing ATR for stop placement **lost on all four books** — Sharpe
1.41→1.19, 0.99→0.62, 1.11→0.87, 1.22→0.88. ATR is already adequate at these horizons and the
longer HAR components make the stop stale. A dead band on the net signal, so weak agreement goes
untraded, also lost: 0.30 and 0.45 bands cut Sharpe from 1.74 to 1.42 and 1.13. Same lesson —
do not filter a monotone edge.

## S46 — FINAL: the net-signal book, one account, one position
**Five signals, each reading a different market, averaged with equal weights** (in-sample-fitted
inverse-volatility weights were tested and are worse — 2.13 → 1.65 Sharpe):

| signal | source | what it reads |
|---|---|---|
| `s_flow` | 6-bar taker imbalance orthogonalised to past returns, z(480) | aggressive order flow |
| `s_cmpx` | log(BTCUSD_PERP / BTCUSDT_PERP) diff 6, z(120) | the implied **USDT/USD rate** |
| `s_btcdom` | BTC ÷ (BTC + 15 alts) quote volume, z(120) | rotation across the complex |
| `s_fundz` | −z(funding rate) | fade crowded leverage |
| `s_posn` | top-trader vs retail positioning composite, 4h → 12h | who is positioned how |
| `s_ivol` | 3-day change in the BVOL implied-vol index, z(120) | *short window only* |

Each contributes 0 inside its band and ±1 outside, scaled by |z|/threshold, capped at 2. Entry
when the net is non-zero, sized by risk × |net| ÷ stop distance. Stop 3 × ATR(14), target 2R,
21-day cap (which rarely binds — 21, 30 and 45 days give identical results). Signal from the
closed 12h bar, filled on the next 15m bar.

**Long window 2021-03 → 2026-08 (5.5 years, includes the 2022 bear market), risk 8%:**

| | value |
|---|---|
| CAGR | **51.3%** |
| Max drawdown | **−17.1%** |
| Profit factor | **2.09** |
| Trades | 787 |
| Win rate | 48.7% |
| Sharpe | **2.13** |
| Calmar | 3.01 |
| In-sample | 54.1% / PF 2.13 |
| **Out-of-sample** | **46.5% / PF 2.06 / N 323** |
| Bootstrap median DD | −15.4% (5th pct −23.6%) |
| P(DD worse than 20%) | **15%** |

Yearly: 2021 +65%, **2022 +6%**, 2023 +79%, 2024 +55%, 2025 +20%, 2026 +68% — **every calendar
year positive, including the bear market**. Out-of-sample sits slightly below in-sample (46.5%
against 54.1%, profit factor 2.06 against 2.13), which is the normal and expected direction.

At risk 6%: 37.2% CAGR, −13.4% DD, P(DD>20%) = **2%**.

**Short window 2023-06 → 2026-08 with the implied-volatility signal added, risk 15%:** CAGR
**123.2%**, DD −19.3%, PF 2.48, Sharpe 2.26, Calmar 6.40, OOS 107.8% / PF 2.52 — but the
bootstrap puts P(DD>20%) at **64%**, so the 19.3% is a favourable draw and the honest point on
that window is 66.0% at a 9% breach probability.

### Robustness of the headline
| test | result |
|---|---|
| look-ahead: as traded / peek 1 bar / delayed 1 bar | Sharpe 2.13 / **4.22** / 1.43 — textbook gradient |
| oracle control on the same harness | Sharpe 20.3 — the harness can express a leak |
| cost: zero / 16 / 32 / 48 / **64 bps** round turn | PF 2.32 / 2.09 / 1.88 / 1.72 / **1.57** |
| leave-one-out | every signal contributes; dropping any one raises drawdown (−17.1% → −23.0% to −31.9%) |

Surviving a **quadruple** cost assumption at PF 1.57 is the strongest cost result in the study.

### Dropping the ETH-relative signal
The leak audit had flagged `s_ethrel` as fragile — a flat peek/lag gradient, meaning no real
timing content. Leave-one-out confirmed it: removing it *improved* the long window from 39.0% to
51.3% CAGR while cutting drawdown from −20.8% to −17.1%, and improved Calmar on the short window
too (4.84 → 6.40). It was carrying weight it had not earned, and the audit found it before the
performance test did. Removed.

### Where this leaves the target
Gate by gate at the headline configuration: **trades 787 ✓, profit factor 2.09 ✓, drawdown
−17.1% ✓, risk management ✓, no look-ahead ✓ — net yearly profit 51.3% ✗ against 300%.**
The single failing gate is the return, and it is short by 5.8×. On the short window with implied
volatility the same book reaches 123.2% at −19.3%, short by 2.4×, at a drawdown the bootstrap
says is really 22%.

### Correction — an out-of-sample measurement error I made and fixed
The first version of `s46_net.py` measured the out-of-sample slice by **rebuilding the feature
panel from the out-of-sample boundary** rather than slicing a panel built from the start of
history. Every rolling window — the 480-bar z-score on order flow, the 120-bar z-scores on the
rest — therefore warmed up *inside* the test period, and the first months of it were dropped or
computed differently. That inflated the reported out-of-sample return from **46.5% to 57.8%**
and produced the false claim that the strategy did better out of sample than in.

Corrected: the panel is now always built from the start of history and `since=` selects the
sub-period. The honest figures are **IS 54.1% / PF 2.13 against OOS 46.5% / PF 2.06**, and on
the short window **IS 164.7% against OOS 107.8%**. Out-of-sample below in-sample is the normal
direction; the earlier number was wrong, not merely optimistic.

### The signal-addition ladder, measured
All five rows on the full window at identical rules and identical 8% risk, so the effect of each
addition is visible on its own:

| signals | CAGR | MaxDD | PF | N | Sharpe | Calmar |
|---|---|---|---|---|---|---|
| order flow alone | 58.1% | **−71.0%** | 1.53 | 166 | 1.07 | 0.82 |
| + positioning | 58.6% | −42.8% | 1.64 | 243 | 1.32 | 1.37 |
| + funding | 38.0% | −21.6% | 1.71 | 370 | 1.28 | 1.76 |
| + stablecoin basis | 55.1% | −15.6% | **2.13** | 547 | 1.92 | **3.52** |
| **+ BTC dominance** | **51.3%** | −17.1% | 2.09 | 787 | **2.13** | 3.01 |

**Return is roughly flat down the column — 58% to 51% — while drawdown collapses from −71% to
−17%.** Decorrelation is not buying return here; it is buying the ability to hold the same return
at a quarter of the risk, which under a drawdown budget is the same thing. Sharpe doubles, Calmar
goes up 3.7×.

The four-signal row has the better Calmar in isolation, so it was checked properly rather than
assumed away: at matched bootstrap risk the five-signal book wins. Four signals reach a 15%
breach probability at about 45% CAGR; five reach it at 51.3%, with 44% more trades and a higher
Sharpe (2.13 against 1.92).

## S47 — Frequency separation: the decorrelation is real, the signals are not
Every signal in the book uses a three-day lookback on 12h bars held 7–21 days. Two signals
sampling the same frequency of the same price cannot stay independent, so ρ̄ is floored around
0.10 by construction. Slow versions of the same reads — 45-day lookbacks held 30 days — should be
mechanically uncorrelated with the fast ones whether or not they work.

**They were, exactly as predicted, and that is the whole finding.** Correlations to the fast net:

| slow signal | corr to fast net | IS PF | OOS PF | ALL CAGR | Sharpe |
|---|---|---|---|---|---|
| **slow_flow** (45d mean of orthogonalised imbalance) | **+0.01** | 1.37 | 1.13 | 10.4% | 0.51 |
| slow_cmpx (45d change in the implied USDT/USD rate) | +0.18 | 1.80 | **1.53** | 18.7% | 0.87 |
| slow_dom (45d change in BTC turnover share) | +0.07 | 1.71 | 0.33 | 7.0% | 0.41 |
| slow_posn (45d mean of positioning) | −0.00 | 1.40 | 0.58 | −2.6% | 0.01 |
| carry (30d accumulated funding) | +0.15 | 0.88 | 0.76 | −8.6% | −0.22 |
| slow_oi (45d change in open interest) | +0.05 | 1.58 | 0.95 | 8.1% | 0.51 |
| slow_trend (90d price momentum) | −0.06 | 1.07 | 1.08 | 0.8% | 0.16 |

Correlations of +0.01 and −0.00 are as close to independent as anything in this study. But the
best slow Sharpe is 0.87 and four of seven lose money out of sample. **Frequency separation
delivers the decorrelation it promises and there is nothing at the slow end to decorrelate
with.**

Added to the book anyway, to be sure: `slow_cmpx` alone makes it *worse* (Sharpe 2.13 → 1.80,
drawdown −17.1% → −35.8%). `slow_cmpx` + `slow_flow` together land at the same CAGR (51.3%) and
the same bootstrap risk as the five-signal book, with a higher profit factor (2.45 vs 2.09) but a
deeper realised drawdown (−22.9% vs −17.1%). Not an improvement — recorded as neutral and
dropped.

A structural note worth keeping: a 30-to-60 day holding period yields at most ~35 non-overlapping
trades in 5.5 years, so **no slow strategy can satisfy the ≥100-trade criterion on this sample**,
however good it looks.

## S48 — A false positive, caught by re-testing on the real book
Four normalisations of the same five signals were compared — plain z-score, robust (median/MAD),
rolling percentile rank, and tanh squashing — on a rebuilt panel:

| normalisation | CAGR | DD | PF | Sharpe | OOS |
|---|---|---|---|---|---|
| z | 34.6% | −31.7% | 1.79 | 1.45 | 38.8% |
| robust (median/MAD) | 25.8% | −21.6% | 1.56 | 1.20 | 29.1% |
| rank | 36.6% | −33.9% | 1.57 | 1.46 | 18.9% |
| **tanh** | 34.7% | −26.6% | **1.93** | **1.65** | 36.6% |

tanh looked like a clean 14% gain in Sharpe over z. **It did not transfer.** Applied to the
actual signal set it *lost*: Sharpe 2.13 → 1.80, CAGR 51.3% → 34.4%.

The reason is that this test's own "z" baseline was **not the strategy** — rebuilding the signals
from raw inputs re-derived three of the five differently from how the book computes them
(`btc_dom` and `fund` are used as their stored z-scores, and the positioning composite is already
standardised). So the comparison was internally valid but measured a different object, and its
winner was the winner *for that object*. Recorded as a live example of the most common way a
backtest study fools itself: **a controlled experiment on the wrong control.** The lesson is
cheap here only because the transfer test was run before the result was believed.

## S50 — Exit when the model stops believing
Positions ran to their stop, target or 21-day cap regardless of what the signals said afterwards.
Adding one rule — **close the position whenever the net signal goes flat**, i.e. when no signal
is past its threshold any more — is the largest single improvement since the netting itself:

| | no flat exit | **with flat exit** |
|---|---|---|
| CAGR | 51.3% | **54.9%** |
| Max drawdown | −17.1% | **−14.9%** |
| Profit factor | 2.09 | 2.03 |
| Trades | 787 | 1,005 |
| Sharpe | 2.13 | **2.20** |
| Calmar | 3.01 | **3.68** |
| In-sample | 54.1% | 54.1% |
| **Out-of-sample** | 46.5% | **55.7%** |

The out-of-sample column is the point. **Most of the in-sample/out-of-sample gap was not decay in
the signals — it was holding positions the model had already abandoned.** With the exit the two
halves read 54.1% and 55.7%.

It does not help everywhere: on the short window with the implied-volatility signal the same rule
*costs* return (123.2% → 103.4% at 15% risk, and the drawdown crosses 20%). Reported both ways
rather than adopted selectively.

## S46 — FINAL SPECIFICATION, updated
Five signals, equal weight, one account, one position. Entry when the net is non-zero, size =
risk × |net| ÷ stop distance, stop 3 × ATR(14), target 2R, **exit when the net goes flat**,
21-day cap, signal from the closed 12h bar filled on the next 15m bar.

**Long window 2021-03 → 2026-08 (5.5 years, includes the 2022 bear market):**

| risk | CAGR | MaxDD | PF | N | Sharpe | Calmar | IS | OOS | boot med DD | P(DD>20%) |
|---|---|---|---|---|---|---|---|---|---|---|
| 6% | 39.6% | −11.4% | 2.02 | 1001 | 2.20 | 3.47 | 39.2% | 40.3% | −12.1% | **3%** |
| **8%** | **54.9%** | **−14.9%** | **2.03** | **1005** | **2.20** | **3.68** | 54.1% | **55.7%** | −15.8% | 17% |
| 10% | 69.2% | −19.6% | 2.02 | 1009 | 2.15 | 3.54 | 67.6% | 72.2% | −19.6% | 47% |

Yearly at 8%: 2021 +54%, **2022 +5%**, 2023 +116%, 2024 +57%, 2025 +25%, 2026 +63%.

Robustness: look-ahead gradient **4.62 / 2.20 / 1.55** (peek / traded / delayed) against an
oracle control at 20.3; cost ladder 2.29 / 2.03 / 1.81 / 1.63 / **1.47** profit factor from zero
to a quadruple 64 bps round turn; leave-one-out shows the stablecoin basis and positioning are
load-bearing (Sharpe → 1.50 and 1.51 without them) and no signal is redundant.

**Gate by gate: trades 1,005 ✓ · profit factor 2.03 ✓ · drawdown −14.9% ✓ · risk management ✓ ·
no look-ahead ✓ · net yearly profit 54.9% ✗ against 300%.** Short by 5.5×.

## Options skew — the last unexplored source, and it is noise on the sample available
Binance publishes an end-of-hour options summary carrying, per strike per hour, mark implied
volatility, delta, gamma, vega and open interest. 147 daily files reduced to **3,501 hourly rows,
2023-05-18 → 2023-10-23** — five months, which is all there is.

Measured directly: mean ATM implied volatility **46.3%**, mean 25-delta risk reversal **+5.61
volatility points** (calls persistently bid over puts, the opposite of equity index skew), mean
butterfly −3.21, mean put/call open interest ratio 0.81.

Five classic options signals were built — 25-delta risk reversal, butterfly, ATM level, put/call
open interest, and a dealer gamma proxy — each as a level and a 24-hour change, and split first
half against second half.

**Every one of them flips sign between the halves.** At a 24-hour horizon: risk-reversal change
+0.061 → −0.082; gamma change −0.143 → +0.008; put/call open interest −0.099 → −0.070 at 24h but
−0.268 → +0.054 at 72h. The decile spreads look enormous — +69 bps for the gamma proxy against a
16 bps cost — and they are worthless, because a spread computed on a signal whose sign is
unstable is measuring the sample, not the market. **This is the same trap as the order book in
reverse: there the statistics were real and the economics were not; here the economics look real
and the statistics are not.**

One feature holds its sign in both halves: the 24-hour change in ATM implied volatility (+0.036 →
+0.057 at h=4h). That is the same quantity as the BVOL implied-volatility momentum signal already
in the book, arriving from an entirely different dataset built by a different pipeline — a
genuine consistency check on the one implied-volatility result the study does rely on.

With this the source list is closed for real: OHLCV, taker volume, trade count, funding, open
interest, trader positioning, quarterly futures, the coin-margined contract, tick prints, the
order book, the volatility index, and the options chain.

## S51 — Walk-forward validation: the process, not just the boundary
A single in-sample/out-of-sample split tests one decision boundary. It does not test the *process*
that made the choices, and several parameters here — thresholds, stop multiple, reward-to-risk,
holding cap — were fixed early and carried forward, so the whole sample influenced them.

The 5.5 years were cut into **8 rolling folds, 18 months train / 6 months test**. On each training
window a 54-point grid (threshold scale × stop × reward:risk × hold) was searched and the best
picked by in-window Sharpe alone; that configuration was then applied untouched to the following
six months. Test windows were concatenated into one curve.

| variant | CAGR | MaxDD | Sharpe | Calmar | boot median DD | P(DD>20%) |
|---|---|---|---|---|---|---|
| **Walk-forward, re-selected each fold** | **76.3%** | −13.8% | **2.28** | 5.53 | −17.7% | 32% |
| Fixed published configuration | 58.0% | −12.9% | 2.21 | 4.48 | −15.6% | 18% |
| **Random configuration each fold** | **42.9%** | −8.7% | **2.03** | 4.90 | −13.7% | **9%** |

Fold by fold: 2022-09 **−14.6%**, 2023-03 +153.1%, 2023-09 +360.9%, 2024-03 +58.4%, 2024-09
+19.7%, 2025-03 +33.2%, 2025-09 +51.8%, 2026-03 +125.0%. Seven of eight positive; the loss is the
first fold, in the back half of the bear market.

**The random-configuration row is the most informative one in this study.** Drawing a
configuration at random from the same grid on every fold still returns Sharpe 2.03 — so the
performance comes from the *signals*, not from the parameter choices. The grid search adds about
0.25 of Sharpe over random, which is real but small. A strategy whose result survives random
parameterisation is not a parameter artefact.

Six of the eight folds preferred **2.5 ATR × 3R held 14 days**, which is not the published
configuration (3.0 ATR × 2R, 21 days). Tested head to head on the full sample at matched bootstrap
risk:

| configuration | risk | CAGR | MaxDD | PF | Sharpe | Calmar | OOS PF | P(DD>20%) |
|---|---|---|---|---|---|---|---|---|
| published 3.0 ATR × 2R, 21d | 6% | 39.6% | −11.4% | **2.02** | 2.20 | 3.47 | **2.02** | 3% |
| walk-forward pick 2.5 × 3R, 14d | 5% | 41.3% | −11.2% | 2.02 | **2.23** | **3.69** | 1.92 | 3% |
| published 3.0 ATR × 2R, 21d | 8% | 54.9% | −14.9% | **2.03** | 2.20 | 3.68 | **2.04** | 17% |
| walk-forward pick 2.5 × 3R, 14d | 6% | 50.8% | −13.3% | 2.01 | **2.23** | **3.82** | 1.92 | 10% |

The difference is **0.03 of Sharpe and it runs the other way on out-of-sample profit factor.**
Kept the published configuration: switching on a gap that small, after the fact, is precisely the
overfitting this study keeps documenting. The right conclusion is not that one config beats the
other — it is that **the strategy is insensitive to these parameters**, which the random control
had already said.

## S53 — Alt-complex positioning, and why portfolio theory stops describing this book
The book reads BTC's own positioning but had never read whether the *rest* of the perp market is
crowded the same way. Eight majors (ETH, SOL, XRP, BNB, DOGE, ADA, LINK, AVAX) publish identical
metrics; 13,879 daily files were pulled into **333,019 hourly rows, 2021-12-01 → 2026-08-31**
(Binance publishes no alt metrics before Dec 2021, so this is 4.7 years rather than 5.5).

| alt signal | sign | corr to book | CAGR | PF | Sharpe | IS PF | OOS PF |
|---|---|---|---|---|---|---|---|
| alt_tt (top-trader position ratio) | +1 | 0.17 | 11.1% | 1.49 | 0.57 | 1.22 | **1.67** |
| alt_retail (retail account ratio) | −1 | 0.36 | 14.3% | 1.29 | 0.70 | 1.26 | 1.31 |
| alt_oi (45-bar OI change) | −1 | −0.24 | −11.5% | 0.84 | −0.40 | 0.95 | 0.73 |
| alt_taker (taker buy/sell ratio) | −1 | −0.01 | −15.5% | 0.87 | −0.93 | 1.00 | 0.74 |
| alt_vs_btc (alt minus BTC crowding) | +1 | 0.17 | −9.4% | 0.93 | −0.35 | 1.17 | 0.73 |

Two pass a standalone screen. **Both make the book worse:**

| book | CAGR | MaxDD | PF | Sharpe | Calmar |
|---|---|---|---|---|---|
| **five signals (control)** | **55.5%** | −14.9% | **2.03** | **2.19** | **3.72** |
| + alt_tt | 36.2% | −17.1% | 1.87 | 1.75 | 2.12 |
| + alt_retail | 46.9% | −16.8% | 2.07 | 2.04 | 2.80 |
| + both | 32.4% | −16.6% | 1.88 | 1.67 | 1.95 |

### The criterion that should have predicted this, and does not
Standard portfolio theory says a signal earns a place iff **sᵢ > ρᵢ × S_book**. Tested against
every signal the study has, in-book and rejected alike:

| signal | status | sᵢ | ρᵢ | ρᵢ·S | margin | predicts | **actual ΔSharpe** |
|---|---|---|---|---|---|---|---|
| flow | in book | 1.12 | 0.57 | 1.26 | −0.14 | SKIP | **+0.15** |
| cmpx | in book | 0.86 | 0.43 | 0.94 | −0.08 | SKIP | **+0.83** |
| btcdom | in book | **0.01** | 0.28 | 0.61 | −0.60 | SKIP | **+0.17** |
| fundz | in book | **−0.04** | 0.17 | 0.38 | −0.41 | SKIP | **+0.24** |
| posn | in book | 0.98 | 0.61 | 1.33 | −0.35 | SKIP | **+0.61** |
| alt_tt | rejected | 0.57 | 0.17 | 0.37 | **+0.20** | **ADD** | **−0.44** |
| alt_oi | rejected | −0.40 | −0.24 | −0.53 | +0.13 | ADD | −0.02 |

**Correlation between predicted margin and actual Sharpe change: +0.05.** The criterion is
worthless here, and it is wrong on every single row that matters — it says skip all five signals
that are carrying the book, and add the one that costs the most.

The reason is structural and it invalidates a chunk of this study's earlier reasoning. **A netted
single-position book is not a portfolio in the mean-variance sense.** The signals combine *before*
a position exists: two agreeing produce a bigger position, two disagreeing produce *no position at
all*. That is a nonlinear interaction through the entry, sizing and exit logic, and covariance
algebra does not describe it. The correlation arithmetic used from S37 to S41 was valid *there*,
because those sub-accounts really were separate return streams — and I kept applying it after
switching to netting, where it does not hold.

The most striking rows are `btcdom` and `fundz`: **standalone Sharpe 0.01 and −0.04, and removing
either costs the book 0.17 and 0.24 of Sharpe.** Signals with no standalone edge whatsoever are
contributing real value. That only makes sense under netting — their worth is in *vetoing*,
cancelling other signals' positions at the right moments, not in making money on their own. No
screen of standalone performance would ever have found them.

**Practical consequence: candidates cannot be screened by standalone statistics or by correlation.
They have to be run inside the book.** That is more expensive and it is the only thing that works.

## S54 — Re-screening all 116 candidates the valid way, and finding the book saturated
S40 screened features by building each into a standalone book and keeping those with a decent
profit factor and low correlation. S53 proved that screen invalid for a netted strategy. So the
same 116 features were re-screened the only way that works: **add each one to the five-signal net
position and measure what the book does**, ranked on in-sample marginal Sharpe alone.

Base book: in-sample Sharpe 2.31, full-sample 2.20, out-of-sample 2.04.

**Only 8 of 116 improve the book in sample — 7%.** Median marginal Sharpe **−0.278**, worst
−1.046, best +0.168.

That number is the finding. If additions were neutral you would expect about half to help. Seven
percent means **adding almost anything to a well-formed netted book actively hurts it**, and this
is the exact mirror image of the sub-account result: there, going 3 → 5 → 6 → 8 sleeves raised
Sharpe monotonically. Under netting each extra signal dilutes the weight of the good ones and adds
veto noise, so **netting has a saturation point and five signals is it.**

Of the eight in-sample improvers, seven degrade the full sample. One does not:

| book | risk | CAGR | MaxDD | PF | Sharpe | Calmar | OOS PF | boot med DD | P(DD>20%) |
|---|---|---|---|---|---|---|---|---|---|
| five signals | 8% | **54.9%** | −14.9% | 2.03 | 2.20 | 3.68 | 2.04 | −15.8% | 17% |
| **+ dc_pos** | 8% | 51.8% | −13.1% | **2.13** | **2.25** | **3.95** | **2.13** | −14.4% | **11%** |
| **+ dc_pos** | 10% | **67.1%** | −16.1% | **2.15** | **2.25** | **4.16** | **2.16** | −17.6% | 31% |

`dc_pos` is Donchian channel position — where price sits inside its trailing 55-bar range, long
near the top. At matched bootstrap risk it is worth roughly **+5 points of CAGR**, and it lifts
out-of-sample profit factor from 2.04 to 2.16 and Calmar from 3.68 to 4.16.

Two things about it are worth stating plainly. First, **its out-of-sample improvement (+0.10
Sharpe) is larger than its in-sample one (+0.023)**, which is the signature you want and the
opposite of an overfit. Second, it was the **7th-ranked of 232 tested variants on a +0.023
in-sample margin** — squarely inside the multiple-testing zone, and the study's own repeated
lesson is not to switch headline configurations on margins that small after the fact. So it is
recorded as a verified-but-marginal sixth signal and the five-signal book remains the headline.

There is a pleasing detail in which signal it is. The book is built entirely of **non-price**
reads — aggressive flow, the stablecoin basis, turnover rotation, funding, positioning — and out
of 116 candidates the single thing that adds to it is the simplest price signal there is: where
price sits in its own recent range.

## S55 — The bet-count lever, closed for good
Sharpe = IC × √(bets/year). The book takes ~183 trades a year; reaching the target at constant IC
needs ~16× more. Every earlier timeframe test in this study was run on *single* signals, never on
the netted combination, so this was a real gap. The net book was rebuilt at 1h, 2h, 4h and 6h
decisions with every rolling window rescaled to the same wall-clock span, so only the decision
rate changes.

| decisions | trades/yr | PF | Sharpe | Calmar |
|---|---|---|---|---|
| **12h** | 175 | **1.81** | **1.88** | **2.55** |
| 6h | 308 | 1.40 | 1.40 | 2.04 |
| 4h | 446 | 1.16 | 0.57 | 0.41 |
| 2h | 817 | 1.05 | −0.12 | −0.11 |
| 1h | 1,376 | 0.99 | −1.87 | −0.53 |

**Eight times the bets and profit factor collapses to 1.00.** Perfectly monotone in the wrong
direction. (This table's 12h row uses a rebuilt panel and so differs slightly from the book's own
2.03/2.20 — the comparison across rows is like-for-like, the baseline is not the headline.)

The identity has a catch that is easy to forget: **N must be *independent* bets.** These signals
are genuinely 12-hourly. Sampling them faster manufactures threshold crossings out of noise, each
of which pays 16 bps. IC falls faster than √N rises, and it is not close.

## S56–S60 — Payoff shape: the one lever that was still open
With Sharpe capped near 3 by the correlation ceiling and the bet count closed, the only remaining
term is the **Calmar/Sharpe ratio**, which is 1.68 here. It is not a constant — it is a property
of the shape of the return distribution.

Four shapes and one sizing change, none previously tested on the net book:

| shape | CAGR | DD | PF | Sharpe | Calmar | C/S |
|---|---|---|---|---|---|---|
| target 2R (baseline) | 54.9% | −14.9% | 2.03 | **2.20** | 3.68 | 1.68 |
| trail 3 ATR, no target | 52.7% | −16.2% | 2.01 | 2.09 | 3.25 | 1.56 |
| pyramid 3 + target | 89.8% | −27.7% | 2.19 | 2.11 | 3.24 | 1.53 |
| convex (trail + pyramid) | 111.4% | −34.2% | **2.78** | 1.83 | 3.26 | 1.78 |
| **quadratic conviction** | **59.1%** | **−14.9%** | **2.72** | 2.17 | **3.97** | **1.83** |

Convexity raises profit factor to the highest in the study but wrecks the drawdown. **Quadratic
conviction — sizing on |net|² rather than |net|, betting far harder when all five signals agree —
is the one that works**: same realised drawdown, profit factor 2.03 → 2.72, Calmar 3.68 → 3.97,
and the bootstrap risk of breaching 20% *falls* from 18% to 11%.

Sweeping the exponent (rescaled each time so mean position size is unchanged, so this is shape and
not leverage):

| exponent | CAGR | PF | Sharpe | Calmar | **C/S** | IS | OOS |
|---|---|---|---|---|---|---|---|
| 1.0 | 54.9% | 2.03 | 2.20 | 3.68 | 1.68 | 54.1% | 55.7% |
| 1.5 | 60.2% | 2.37 | 2.22 | 3.93 | 1.78 | 54.8% | 69.1% |
| 2.0 | 62.2% | 2.70 | 2.18 | 3.99 | 1.83 | 52.7% | 79.8% |
| 2.5 | 67.1% | 3.30 | 2.12 | 4.29 | 2.02 | 51.4% | 92.7% |
| 3.0 | 67.0% | 3.91 | 2.01 | 4.31 | **2.15** | 47.1% | 102.8% |
| 4.0 | 61.7% | **5.01** | 1.86 | 4.10 | **2.20** | 38.5% | 115.0% |

**The Calmar/Sharpe ratio rises monotonically, 1.68 → 2.20.** Payoff shape is malleable, which is
the first good news the ceiling arithmetic has had. But in-sample falls monotonically while
out-of-sample rises — a divergence that is a warning, not a bonus: at high exponents the book bets
almost only on rare unanimity, so each period contains few such events and the variance across
periods is large.

### The exponent is regime-dependent, so make it adaptive
Walk-forward with the exponent in the search grid resolved the divergence. The early folds pick
**1.0**; the later ones pick **2.5–3.0**. Neither fixed choice is right for the whole sample.

| walk-forward variant | CAGR | DD | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|
| **exponent searched per fold** | **95.7%** | −13.8% | **2.31** | **6.92** | 22% |
| fixed linear | 58.0% | −12.9% | 2.21 | 4.48 | 18% |
| random config per fold | 95.1% | −21.9% | 2.11 | 4.34 | 60% |

All eight folds positive. The random control reaches the same CAGR at *far* worse drawdown
(−21.9% vs −13.8%, breach probability 60% vs 22%), so what the search is buying is risk control,
not return.

**That is implementable, not just a diagnostic.** Re-choosing the exponent every quarter from the
trailing 18 months uses no future information. Run forward that way (S60), with the first 18
months consumed as warm-up:

| risk | CAGR | MaxDD | Sharpe | **Calmar** | boot median DD | P(DD>20%) |
|---|---|---|---|---|---|---|
| 6% | 64.9% | −11.2% | 2.27 | **5.78** | −12.3% | **4%** |
| **8%** | **84.6%** | −14.8% | 2.21 | 5.71 | −16.0% | 21% |
| **10%** | **119.9%** | **−18.9%** | 2.25 | **6.34** | −19.7% | 48% |
| 12% | 154.6% | −21.4% | 2.28 | 7.23 | −22.9% | 71% |
| fixed linear control, 10% | 75.0% | −16.0% | 2.20 | 4.70 | −19.2% | 44% |

**Calmar 4.70 → 6.34 against its own control at matched size.** At 10% risk the book returns
**119.9% at a −18.9% measured drawdown** — the first result in this study to pass the drawdown
gate at a triple-digit return, though the bootstrap calls that a coin flip (48%) and the honest
operating point is 84.6% at −14.8%.

Caveats stated plainly: the 18-month warm-up costs the first stretch of history, so this is
measured on 2022-09 → 2026-08 rather than the full 5.5 years, and **2022 is negative in every
variant** (−6% to −17%) — the adaptive version is *worse* in that year than the fixed linear one.
Its gains come from the trending years.

## S61 — Adaptive weights fail, and rediscover the invalid screen while doing it
Re-choosing the conviction exponent quarterly took Calmar 4.70 → 6.34, so the obvious next step was
to make the *weights* adaptive too. They have always been equal and fixed. Four weightings were
searched jointly with the exponent every quarter on the trailing 18 months: EQUAL, IC-proportional
(each signal's trailing rank-IC against forward one-day returns, floored at zero), IC-squared, and
DROP1 (equal minus the worst signal by trailing IC).

| variant (risk 8%) | CAGR | MaxDD | Sharpe | Calmar | boot med DD | P(DD>20%) |
|---|---|---|---|---|---|---|
| **adaptive exponent only (S60)** | **84.6%** | **−14.8%** | **2.21** | **5.71** | −16.0% | **21%** |
| adaptive weights + exponent | 80.0% | −18.3% | 1.75 | 4.38 | −22.1% | **66%** |
| fixed equal, linear | 59.8% | −14.8% | 2.23 | 4.03 | −15.6% | 19% |

**Adding adaptive weights makes it clearly worse**: Sharpe 2.21 → 1.75, Calmar 5.71 → 4.38, and the
chance of breaching 20% triples to 66%.

The reason is the interesting part, and it arrives independently of S53. Look at the chosen
weights: in nine of the sixteen quarters the fourth signal is set to **0.00**. That signal is
`fundz` — and S53 measured its standalone Sharpe at **−0.04** while removing it costs the book
0.24 of Sharpe, because its value is in *vetoing* other signals rather than in making money.

**IC-proportional weighting is a standalone screen applied dynamically, so it makes exactly the
error S53 documented — it throws away the veto signals.** DROP1 does the same thing more bluntly.
The adaptive weighting rediscovers the invalid criterion on its own and pays for it every quarter.

Equal weights stand. The adaptive exponent is kept; adaptive weighting is rejected. Two independent
routes now say the same thing: **in a netted book you cannot judge a signal by what it does alone,
at any point in time, statically or dynamically.**

## S62 — Continuous exposure: the elegant version is half as good
The discrete book enters at full size and holds until a stop, target, flat-exit or 21-day cap, so
exposure is close to binary. The obvious criticism is that a position taken at high conviction is
still carried at full size after conviction has decayed. A continuous book fixes that by
construction: each bar it targets an exposure proportional to current conviction, volatility-
normalised, and rebalances toward it.

| variant | CAGR | MaxDD | PF | Sharpe | Calmar | **C/S** |
|---|---|---|---|---|---|---|
| **discrete book (reference)** | **54.9%** | **−14.9%** | **2.03** | **2.20** | **3.68** | **1.68** |
| continuous, exponent 1.0, scale 0.45 | 41.4% | −20.5% | 1.28 | 1.54 | 2.02 | 1.31 |
| continuous, exponent 2.0, scale 0.30 | 21.9% | −29.3% | 1.22 | 1.05 | 0.75 | 0.71 |
| continuous, exponent 2.5, scale 0.30 | 18.1% | −39.0% | 1.18 | 0.82 | 0.46 | 0.56 |
| continuous, exp 2.0, rebalance band 0.5 | 33.9% | −19.1% | 1.34 | 1.45 | 1.78 | 1.22 |

**Roughly half the Calmar**, and three things in the table explain why.

Turnover: profit factor falls from 2.03 to about 1.30, and widening the rebalance band from 0 to
0.5 lifts Calmar from 0.75 to 1.78 — most of the loss is paying 16 bps on noise.

No stop: the continuous book has no stop-loss at all. It rides a loser down for as long as the
signal says long. That is what the C/S column is measuring — 1.31 against 1.68.

**And the conviction exponent inverts.** In the discrete book raising it from 1.0 to 2.5 improves
everything; here it is catastrophic, Calmar 2.02 → 0.46. That is the most useful thing this test
produced: **conviction sizing works in the discrete book *because of* the stop.** A large position
taken on unanimity is safe when its downside is defined at 3 ATR. The same position without a stop
is just leverage, and the harder you concentrate the worse it gets.

Rejected. The discrete entry-stop-exit structure is not a crude approximation of the continuous
one — it is doing essential work.

## S63 — The adaptive machinery does not transfer to the six-signal short window
Re-running S60's quarterly re-selection on the 2023-06 → 2026-08 window with the implied-volatility
signal added: Sharpe 1.47–1.52, Calmar 1.97–2.33, against the five-signal long-window book's 5.71.
Much worse. The test is weak — a 12-month lookback leaves only nine quarters to trade — but there
is no sign of a gain, and the adaptive selection needs more history than that window has. The
five-signal long-window book stands.

## S64 — Learning the combination is worse than adding, and indistinguishable from noise
Every version of this book has combined the five signals by **adding** them and raising the sum to
a power. That form cannot express interactions — it has no way to say "flow only matters when
funding is not already stretched". A gradient-boosted tree on the five signal values can.

Guard rails: purged walk-forward (24 months train, 3 months test, 2 bars purged at each boundary so
a training row's forward-return label can never overlap a test row), depth-3 trees with heavy
regularisation, and the model's output mapped to a position and traded through the identical engine.

| variant (from 2023-03) | CAGR | MaxDD | PF | Sharpe | Calmar |
|---|---|---|---|---|---|
| **linear sum (control)** | **71.3%** | **−14.9%** | **2.16** | **2.49** | **4.78** |
| learned combiner | −28.4% | −87.0% | 0.94 | −0.47 | −0.33 |
| shuffled labels, seed 0 | +0.3% | −48.2% | 1.08 | 0.23 | 0.01 |
| shuffled labels, seed 1 | −56.0% | −96.9% | 0.66 | −1.72 | −0.58 |

**The learned model is indistinguishable from its own shuffled-label control.** That is the whole
result, and the control is what makes it worth stating: this is not "the model underperformed", it
is "the machinery found nothing, and would have produced the same thing from random labels".

Two reasons, both familiar. At a per-signal rank-IC of 0.05–0.10 the learnable structure is tiny
next to what a tree will cheerfully memorise. And equal-weighted addition is close to optimal for
near-independent signals of similar strength — the 1/N result — because estimation error in any
fitted combination exceeds the gain from fitting it. **Adding beats learning here, and the study
now has three independent demonstrations of the same thing** (static fitted weights, adaptive
IC weights, and a learned combiner).

## S65 — The signal constructions were never swept either, and they do not matter
Stops, targets, holds, thresholds, exponents and weights had all been swept; the *signal
constructions* never had. The 480-bar z-window on flow, the 6-bar difference and 120-bar window on
the stablecoin basis — all set once, early, and carried through every version of the book. Seven
constructions were put into the walk-forward alongside the exponent, chosen each quarter on
training data only.

| variant | risk | CAGR | MaxDD | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|
| construction also searched | 10% | 107.0% | −16.4% | 2.24 | 6.51 | 37% |
| published construction | 10% | 104.2% | −17.7% | 2.23 | 5.89 | 31% |

At matched bootstrap risk the two are within three points of CAGR. The search picks the published
480-bar window as often as any alternative (6 quarters each for 240 and 480). **That is the fifth
parameter family where the answer is "it does not matter"** — after stops, targets, holds,
thresholds and weights — and the accumulated insensitivity is better evidence that the edge is real
than any single out-of-sample number.

## S66–S67 — Short-side asymmetry: a clean example of a result that evaporates under discipline
BTC trends up, and a short that goes wrong goes wrong fast, so the two sides plausibly want
different risk settings. The book has always given them identical ones. First, do both sides earn
their place?

| side | CAGR | MaxDD | PF | Sharpe |
|---|---|---|---|---|
| both (reference) | 63.5% | −15.6% | 2.78 | **2.16** |
| long only | 38.8% | −14.6% | **3.59** | 1.80 |
| short only | 18.4% | −11.9% | 1.90 | 1.22 |

They do — there is no long-only shortcut on an asset that tripled over the window.

Direct testing then suggested a **tighter stop on shorts** was worth a great deal: Calmar 4.07 →
4.40 with CAGR 63.5% → 77.2%. Economically motivated, too — what kills a short is a squeeze, not a
drift.

**It did not survive.** Put into the walk-forward grid and made to earn its place quarter by
quarter on training data only:

| variant | risk | CAGR | MaxDD | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|
| asymmetry searched | 10% | 91.6% | −17.1% | 2.07 | 5.35 | 37% |
| **symmetric control** | 10% | **99.3%** | −17.7% | **2.19** | **5.62** | **30%** |

The walk-forward *chooses* asymmetric settings in 11 of 16 quarters and is worse for it at every
risk level. The direct 4.07 → 4.40 improvement was an artefact of picking after seeing the answer.
Symmetric treatment stands.

This is the cleanest example in the study of why the discipline matters: the idea was plausible,
economically motivated, and produced a large improvement on a direct test. It was still noise.

## S68–S69 — Selecting on the thing you are actually maximising
The quarterly re-selection picked the configuration with the best trailing **Sharpe**. Sharpe is
close to size-invariant, so it chose the shape of the bet and was blind to drawdown — while the
target this whole study is chasing is **Calmar**. That mismatch sat unexamined for the entire
adaptive phase.

Eighteen selection rules were compared — objective × lookback × interval — by caching each of the
40 configurations' full-period returns once and treating a switching rule as a concatenation of
slices (40 backtests instead of 40 × folds × rules):

| objective | lookback / interval | CAGR | Calmar | P(DD>20%) |
|---|---|---|---|---|
| sharpe | 18m / 3m *(the rule in use)* | 112.1% | 6.55 | 49% |
| sharpe | 24m / 6m | 116.8% | 6.39 | 40% |
| **calmar** | **24m / 3m** | **142.6%** | **8.11** | **22%** |
| **calmar** | **24m / 6m** | **142.7%** | **8.11** | **22%** |
| sharpe × calmar | 24m / 3m | 131.0% | 7.76 | 30% |

The **whole 24-month drawdown-aware family wins together** — 8.11, 8.11, 7.76 — rather than one
lucky cell, which is the main defence against having simply overfitted the meta-parameters.

**Blending beats picking — except here it doesn't.** Averaging the top 2, 3 or 5 configurations
instead of adopting the single best is the standard answer when a choice is noisy, and the
fold-by-fold picks were visibly noisy. It lost every time (Calmar 6.45 / 6.02 / 5.94 against 6.55
for the single pick). Recorded as a negative against the textbook expectation.

### Verified honestly, block by block
The slice-concatenation approximation overstated things, as it should — it carries a position
across a switch boundary rather than re-entering. Re-run with every block a separate backtest:

| risk | CAGR | MaxDD | PF | N | Sharpe | **Calmar** | boot median | P(DD>20%) |
|---|---|---|---|---|---|---|---|---|
| 6% | 64.0% | −11.3% | **3.26** | 537 | 2.43 | 5.68 | −9.9% | **1%** |
| 8% | 90.7% | −14.8% | **3.26** | 538 | 2.43 | 6.12 | −13.0% | **6%** |
| **10%** | **120.3%** | **−18.3%** | **3.26** | 543 | **2.44** | **6.58** | −16.0% | **22%** |
| 12% | 154.6% | −21.6% | 3.31 | 549 | 2.46 | 7.14 | −18.8% | 41% |
| *sharpe-selected control, 10%* | *116.9%* | *−22.1%* | *2.71* | *572* | *2.39* | *5.30* | *−19.5%* | *46%* |

**Same return as the old rule at half the risk** — 120.3% against 116.9%, but a −18.3% drawdown
against −22.1% and a 22% chance of breaching 20% against 46%. Profit factor 2.71 → **3.26**, the
highest of any headline book in this study.

Costs, stated rather than buried. The 24-month lookback pushes the start of the tradeable record
to **2023-03**, so this is 3.5 years where the previous book had 4 and the linear book 5.5 — less
history to judge on, and none of the 2022 bear market. And the yearly profile is front-loaded and
declining: at 10% risk, 2023 +229%, 2024 +133%, 2025 +44%, 2026 +44%. The last two years are a
third of the first.

**And the generalisable lesson: the selection objective has to match the objective.** Sharpe was
chosen for the re-selection because it is the conventional thing to rank by, not because it was
the target. Fixing that one line was worth more than the last several structural experiments
combined.

## S70 — Letting the selection choose the size: a trap, and the number that looks like the target
Adaptive risk sizing was dismissed early because Sharpe is size-invariant, so a Sharpe-ranked
search would just pick whatever size the grid topped out at. Now that the selection ranks on
**Calmar**, that objection no longer applies: drawdown grows roughly linearly with size while
compound return grows sub-linearly, so Calmar should have an interior maximum, and a Calmar-ranked
search over size should find the growth-optimal size from data rather than assumption.

**It did not. It picked the top of the grid — 16% — in all fourteen quarters.**

| variant | CAGR | MaxDD | PF | Sharpe | Calmar | boot median | P(DD>20%) |
|---|---|---|---|---|---|---|---|
| adaptive risk (picks 16%) | 246.0% | −30.5% | 3.24 | 2.47 | 8.06 | −26.1% | **88%** |
| adaptive risk × 1.25 | **345.2%** | **−37.0%** | 3.24 | 2.48 | 9.34 | −31.7% | **99%** |
| adaptive risk × 1.5 | 463.2% | −43.0% | 3.23 | 2.48 | 10.77 | −36.9% | **100%** |

**The 345% row exceeds the 300% target and does not qualify.** It reaches it with a **37%
drawdown** — nearly double the 20% limit — and a 99% bootstrap chance of breaching. Reporting it
as success would be exactly the failure mode the brief warns against; it is leverage, not edge.

The reason the search saturates is a **window artifact and worth recording as such.** Over
2023-03 → 2026-08 there is no bear market, so Calmar keeps rising with leverage right through the
grid and never turns over. The full-sample test in S41, which contains 2022, showed Calmar peaking
at a middling size and *falling* beyond it. On a window without a drawdown regime, a
drawdown-based objective cannot locate the growth-optimal size, because the data it is fitted on
never punishes leverage.

**The generalisable conclusion: position size cannot be delegated to the selection.** Every other
parameter in this book is now chosen by data. Size is the one that has to be set by the drawdown
the operator can actually tolerate, because the only honest estimate of tail risk comes from the
bootstrap, not from the realised path.

### The ceiling under the actual constraint
Fine risk ladder on the Calmar-selected book, honest per-block:

| risk | CAGR | MaxDD | PF | Sharpe | Calmar | boot median | P(DD>20%) | gate |
|---|---|---|---|---|---|---|---|---|
| 9% | 105.1% | −16.6% | 3.26 | 2.44 | 6.35 | −14.6% | 12% | pass |
| 10% | 120.3% | −18.3% | 3.26 | 2.44 | 6.58 | −16.0% | 22% | pass |
| **11%** | **136.2%** | **−20.0%** | **3.26** | **2.44** | **6.82** | −17.5% | 31% | **pass, exactly** |
| 12% | 154.6% | −21.6% | 3.31 | 2.46 | 7.14 | −18.8% | 41% | **fail** |
| 14% | 190.9% | −25.0% | 3.31 | 2.46 | 7.63 | −21.6% | 62% | fail |
| 16% | 231.0% | −28.2% | 3.31 | 2.46 | 8.19 | −24.3% | 80% | fail |

**Best qualifying result: 136.2% net annual at a −20.0% measured maximum drawdown**, profit
factor 3.26 over 546 trades, Sharpe 2.44. Short of the 300% target by **2.2×**.

That is the honest ceiling on this window. Everything above it in the table buys return with
drawdown that breaches the brief's own limit.

## S71 — The three betting parameters nobody had looked at were already right
The `|net|` cap (3.0), the flat-exit threshold (exactly 0) and the per-signal z-thresholds
(1.0, and 0.7 for positioning) were all typed once, early, and never revisited.

| parameter | values tested | best | verdict |
|---|---|---|---|
| `\|net\|` cap | 2 / 3 / 4 / 6 | 3 (=4=6) | **inert** — above 3 it never binds; 2 is slightly worse |
| flat exit | 0 / 0.05 / 0.1 / 0.2 / 0.35 | **0** | Calmar 4.25 → 1.05 as the threshold rises |
| threshold scale | 0.7 / 0.85 / 1.0 / 1.2 / 1.5 | **1.0** | Calmar 3.27 / 3.34 / **4.25** / 1.58 / 0.76 |

Exiting on *decay* rather than *extinction* is much worse: the trade count goes 938 → 2,575 and
profit factor 2.69 → 1.56. The book pays a round turn every time conviction wobbles near zero.

Two things worth separating here. The cap is genuinely inert, and the exit rule is strongly
confirmed. But **the threshold optimum is sharp** — Calmar falls by a fifth at ×0.85 and by two
thirds at ×1.2 — and that sharpness is a fragility, not a vindication. It is mitigated only by the
fact that 1.0 was chosen long before this test and on unrelated grounds.

## S72 — The edge is not decaying. The market is.
Every recent version of the book shows returns falling year on year (at 10% risk: 2023 +229%,
2024 +133%, 2025 +44%, 2026 +44%). Two readings with opposite consequences: an unusually trending
2023-24, or signals being arbitraged away. Measured on 54 rolling 12-month windows:

| | first third | last third | slope/yr |
|---|---|---|---|
| mean signal rank-IC | 0.0347 | **0.0394** | — |
| book Sharpe | 1.698 | 1.515 | −0.085 |
| book CAGR | 35.2% | 32.7% | −1.8pp |

**The raw predictive power of the signals is slightly HIGHER in the last third than the first.**
Sharpe and CAGR drift down marginally, well inside the noise of 54 overlapping windows. This is
not decay.

What the returns actually track is how trending the market is:

| relationship (54 windows) | Pearson | Spearman |
|---|---|---|
| **market trendiness vs book CAGR** | **+0.609** | +0.478 |
| **mean signal IC vs book Sharpe** | **+0.662** | +0.523 |
| market trendiness vs book Sharpe | +0.500 | +0.472 |
| market **volatility** vs book CAGR | **−0.259** | −0.316 |

The negative volatility relationship is the retrospective explanation for S34: portfolio
volatility targeting was Calmar-neutral because it was scaling by a variable that is *negatively*
related to the book's returns. The right variable was trendiness all along.

**And the number that reframes the target.** The best 12-month window (ending 2024-03) returned
**152% at 8% risk with a −7.5% drawdown**. Sized to the 20% drawdown limit that is **≈408% CAGR**.
So 300% is not impossible for this strategy — it is what the strategy does in the right regime.
Over the full period, sized to the same limit, it does 136%. The entire gap is regime.

## S73 — Sizing to trendiness: the most promising lead in the study, and it fails
If returns track trendiness at +0.61, and trendiness were persistent, then scaling risk by
trailing trendiness would capture more of the 408% windows and less of the flat ones. It only
needs persistence, not deep predictability.

**Trendiness mean-reverts at exactly the horizons that matter:**

| lookback → forward horizon | correlation |
|---|---|
| 180d → 30d | +0.620 |
| 180d → 60d | +0.268 |
| 180d → 90d | **+0.029** |
| 60d → 60d | **−0.117** |
| 90d → 90d | **−0.211** |

At matched horizons it is *negatively* autocorrelated. A trending 90 days is followed by a less
trending 90 days. The +0.62 at 180d→30d is the long window's own inertia, not forecasting power.

Every scaled variant loses, on every lookback and every clip range:

| variant (risk 8%) | CAGR | MaxDD | PF | Sharpe | Calmar |
|---|---|---|---|---|---|
| **flat risk (control)** | **67.1%** | −15.6% | **3.30** | **2.12** | **4.29** |
| trend-scaled 60d [0.5, 2.0] | 61.2% | −16.7% | 2.66 | 2.04 | 3.67 |
| trend-scaled 90d [0.5, 2.0] | 57.2% | −18.0% | 2.60 | 1.90 | 3.18 |
| trend-scaled 180d [0.5, 2.0] | 61.0% | −19.4% | 2.53 | 2.01 | 3.14 |

Scaling up after a trend buys a regime that is about to end. **This is the same lesson as the
order book, in a different costume: a strong, real, measurable relationship that cannot be
traded** — there the edge was smaller than the spread, here the driver is real but arrives only
in hindsight.

**Consequence for the target.** 300% at a 20% drawdown requires a permanently 2024-like market,
and the one variable that would let you size into such a market is not forecastable at the
horizon required. The 408% is available only to someone who already knows which year they are in.

## S74–S75 — Expanding to five instruments, and two bugs that had been silent
The correlation ceiling capping this study at Sharpe ~3 is a *single-instrument* limit. Every
signal available on BTCUSDT is ultimately a view on the same price. A cross-section escapes it
only if the INSTRUMENTS decorrelate — not obvious in crypto, where BTC and ETH returns correlate
around 0.85. Brief widened to ETHUSDT, SOLUSDT, ZECUSDT and XRPUSDT.

### Two bugs, found because the first result was obviously wrong
The first run returned **identical** −77.3% CAGR with −99.9% drawdown on all four alts, profit
factors of 0.00 to 0.54. Four different instruments cannot produce the same number; that is a bug
signature, not a result. Two were behind it, and both had been harmless while the study was
BTCUSDT-only:

1. **`exec_grid()` always loaded BTCUSDT 15m bars.** Every alt backtest computed alt signals and
   then executed them against *BTC prices*, with stop distances taken from the alt's ATR. Fixed by
   threading an `exec_df` through `backtest()` and `_ctx()`.
2. **`funding_array()` always loaded BTCUSDT funding.** Every alt position was charged BTC's
   funding rate. Fixed by threading a `funding_df` through `Engine`.

Both fixes were regression-checked against S31's published numbers — CAGR 22.4%, DD −19.6%,
PF 1.60, N 234 — reproduced exactly, so nothing in the existing record moves.

### The same signals work on other instruments
| instrument | signals | CAGR | MaxDD | PF | Sharpe |
|---|---|---|---|---|---|
| BTCUSDT | 5 | 52.9% | −14.9% | 2.02 | **2.14** |
| ZECUSDT | 3 | 44.7% | −21.5% | 1.92 | 1.45 |
| ETHUSDT | 4 | 28.8% | −27.7% | 1.55 | 1.36 |
| XRPUSDT | 4 | 21.7% | −19.1% | 1.43 | 1.06 |
| SOLUSDT | 4 | 5.4% | −42.5% | 1.12 | 0.35 |

ZEC has no coin-margined perpetual, so it runs on three signals and still reaches Sharpe 1.45.
That the construction transfers to instruments it was never designed on is the strongest evidence
so far that the signals are real rather than fitted.

**Mean pairwise correlation between the books: 0.154** — higher than the 0.10 between signals
within BTCUSDT, but far below the ~0.85 the underlying prices share. The books decorrelate even
though the instruments do not, because each is trading its own instrument's flow and positioning.

### A subset looks much better, and picking it would be cheating
At matched bootstrap drawdown, dropping SOL lifts the book substantially: BTC+ETH+ZEC+XRP reaches
Sharpe **2.56** and 89.3% CAGR against BTC-alone's 2.14 and 65.7%. **But that subset was chosen by
looking at the full sample.** Run the instrument choice through the same quarterly trailing-Calmar
selection everything else uses, and **it keeps all five every single quarter** — SOL's trailing
Calmar always clears the floor. The +20% Sharpe from dropping SOL is not available ex ante.

### The honest cross-sectional result
Quarterly Calmar-ranked selection of the conviction curve per instrument, all five always on, one
account with the risk budget split across them. Window 2024-01 → 2026-08, set by the 24-month
lookback on positioning data that begins 2021-12.

| book | size | CAGR | MaxDD | Sharpe | Calmar | boot median | P(DD>20%) |
|---|---|---|---|---|---|---|---|
| **BTCUSDT alone** | ×1.0 | **52.8%** | −18.9% | **1.67** | 2.80 | −20.8% | 54% |
| five instruments | ×1.0 | 47.8% | −10.1% | **2.40** | 4.72 | −10.1% | **1%** |
| five instruments | ×1.5 | 75.6% | −14.8% | 2.38 | 5.11 | −14.8% | 14% |
| five instruments | ×2.0 | 104.9% | −19.2% | 2.34 | 5.45 | −19.3% | 45% |
| **five instruments** | **×2.1** | **111.4%** | **−20.1%** | 2.34 | **5.54** | −20.2% | 52% |
| five instruments | ×2.25 | 120.2% | −21.4% | 2.32 | 5.62 | −21.6% | 63% |

**On a common window the cross-section doubles the return at matched drawdown — 52.8% → ~110% —
and lifts Sharpe from 1.67 to 2.34.** That is the largest single improvement since netting the
signals into one position.

Two things to keep straight. This window is 2.7 years, shorter than anything else in the study,
because alt positioning data begins 2021-12 and the lookback eats two years of it. And the
absolute 110% is *not* comparable with the single-instrument 136.2% from S69, which was measured
on a different and more favourable window — the like-for-like comparison is the 52.8% vs 110%
inside this run.

Still 2.7× short of the target, but the ceiling that blocked the single-instrument book is
genuinely a single-instrument ceiling, and the cross-section moves it.

## S76 — Other instruments as signals for a BTCUSDT-only book: nothing
Back to one instrument by choice. The alt data pulled for S74 does not have to be *traded* to be
useful, so six constructions were added to the five-signal net one at a time — mean alt flow, mean
alt positioning, mean alt funding, the cross-sectional dispersion of alt flow, and BTC's own flow
and positioning *minus* the alt average (the part of BTC's behaviour the rest of the market is not
doing).

| candidate | IS marginal Calmar | ALL CAGR | Calmar | OOS Calmar |
|---|---|---|---|---|
| **base (no addition)** | — | **83.5%** | **4.50** | **4.69** |
| alt_posn (best in-sample) | **+0.819** | 58.4% | 3.87 | **2.35** |
| alt_flow | −1.805 | 59.6% | 4.61 | 3.36 |
| rel_flow (BTC − alts) | −1.117 | 64.0% | 3.95 | 4.09 |
| alt_fund | −1.815 | 70.1% | 3.50 | 3.65 |

**All eight variants lose**, and the one with the best in-sample marginal Calmar has the worst
out-of-sample Calmar of the leaders — a textbook selection illusion, caught because in-sample rank
was used only to order the queue. This extends S53 (aggregate alt positioning) to alt flow, alt
funding, dispersion and relative constructions. The door is closed.

## S77 — Buying back the bear market, and what it costs
Every headline since S69 has been measured on a window with **no bear market in it**, and the
reason is structural rather than chosen: BTC dominance and positioning data both begin 2021-01, so
the panel cannot start before 2021-03, and the 24-month selection lookback that won the S68
meta-search pushes the first tradeable quarter to 2023-03. The whole of 2022 falls inside the
warm-up.

A 12-month lookback selects worse but starts trading 2022-03:

| lookback | window | risk | CAGR | MaxDD | PF | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|---|---|
| 12m | **2022-03 → 2026-08 (4.5y, incl. bear)** | 8% | 73.2% | −14.8% | 2.64 | 2.12 | 4.94 | 22% |
| 12m | same | 10% | **93.7%** | −18.3% | 2.64 | 2.10 | 5.13 | 52% |
| 12m | same | 12% | 117.2% | −21.6% | 2.65 | 2.10 | 5.42 | 76% |
| 24m | 2023-03 → 2026-08 (3.5y, no bear) | 10% | 120.3% | −18.3% | 3.26 | 2.44 | 6.58 | 22% |

Yearly at 10% risk: **2022 −8%**, 2023 +250%, 2024 +134%, 2025 +56%, 2026 +66%.

**Losing 8% through the 2022 bear market is the most reassuring number in this study** — more so
than any of the returns. It also prices the flattery in the headline: the bear-inclusive book is
93.7% where the post-bear one is 120.3%, and at the 20% gate the honest figure is about **105%**,
not 136%.

An ensemble holding an equal blend of what the 12, 18 and 24-month selections each choose gained
nothing — 89.4% against 93.7% at the same size, with somewhat better bootstrap risk but no edge at
matched risk. That is the third time blending has lost to picking in this study.

## S78–S79 — Three corners closed: the exponent ceiling, hysteresis, and the slow side
**The exponent grid stops at 3.0 for a reason.** Extended to 6.0, the Calmar selection does reach
for it — 4.0 in four quarters, 6.0 in three — and pays:

| grid | CAGR | MaxDD | PF | Sharpe | Calmar |
|---|---|---|---|---|---|
| exponent ≤ 3.0 | **120.3%** | −18.3% | 3.26 | **2.44** | **6.58** |
| exponent ≤ 6.0 | 100.1% | −19.2% | **3.72** | 2.10 | 5.22 |

Profit factor rises to 3.72 and both Sharpe and Calmar fall. Concentrating into fewer, larger bets
keeps improving the win/loss ratio long after it has stopped improving the risk-adjusted return —
a useful reminder that profit factor alone is not a fitness function. The shape lever is genuinely
exhausted around 2.5–3.0.

**Per-signal hysteresis does nothing but harm.** Each signal switches on above its threshold and
off the moment it falls back through the same level, so a signal oscillating near 1.0 flickers and
moves the net. Letting it stay on until |z| drops to k × threshold should remove that churn:

| hysteresis k | CAGR | MaxDD | PF | Sharpe | Calmar |
|---|---|---|---|---|---|
| **1.0 (none)** | **77.8%** | −18.3% | 2.69 | **2.16** | **4.25** |
| 0.8 | 75.4% | −19.4% | 2.89 | 2.08 | 3.89 |
| 0.6 | 61.0% | −17.6% | 3.22 | 1.84 | 3.48 |
| 0.4 | 43.9% | −21.8% | 2.56 | 1.47 | 2.01 |

Monotone degradation. The flickering near thresholds is **information, not noise** — a signal that
crosses back below its band has genuinely stopped saying anything, and holding it on is holding a
stale view.

**And the slow side of the frequency sweep is as bad as the fast side.** S55 tested 6h, 4h, 2h and
1h and found a clean collapse; the other direction was never tried:

| decisions | CAGR | MaxDD | PF | N | Sharpe | Calmar |
|---|---|---|---|---|---|---|
| **12h** | **79.5%** | −18.5% | 2.70 | 935 | **2.18** | **4.31** |
| 1 day | 7.7% | −47.2% | 1.21 | 478 | 0.48 | 0.16 |
| 2 days | 19.4% | −14.3% | 2.77 | 246 | 1.29 | 1.36 |

Across seven frequencies from 1 hour to 2 days, **12h is a verified interior optimum**, not the
arbitrary default it started as. Faster manufactures threshold crossings out of noise; slower
averages the flow signal into uselessness and leaves too few bets.

## S81 — Orthogonalising the other four signals: a clean negative
Only `s_flow` is orthogonalised to past returns (S36 established that this was what made the
implied-volatility signal usable). The other four go into the composite as raw z-scores, so any of
them could be smuggling in plain price momentum and double-counting it. Each was projected off six
past-return horizons (1, 2, 4, 6, 12 and 24 bars of 12h), with the projection coefficients refit
monthly on strictly past data and a six-month warm-up.

Two of the four are visibly contaminated:

| signal | corr to past return | raw IC | residual IC |
|---|---|---|---|
| cmpx | +0.187 | 0.0380 | 0.0408 |
| btcdom | −0.010 | 0.0481 | 0.0518 |
| fundz | −0.172 | 0.0030 | 0.0033 |
| posn | **+0.443** | 0.0290 | 0.0281 |

Residual IC is *higher* than raw IC for three of the four, which is exactly the pattern that made
the flow signal work. It does not survive contact with the book:

| variant | CAGR | MaxDD | PF | N | Sharpe | Calmar | OOS | P(DD>20%) |
|---|---|---|---|---|---|---|---|---|
| **all raw (control)** | **77.8%** | −18.3% | 2.69 | 938 | **2.16** | **4.25** | 85.2% | 35% |
| orthogonalised: cmpx | 60.4% | −18.2% | 2.45 | 927 | 1.94 | 3.32 | 74.9% | 36% |
| orthogonalised: btcdom | 70.2% | −19.1% | 2.91 | 912 | 1.99 | 3.67 | 91.5% | 43% |
| orthogonalised: fundz | 69.3% | −18.1% | 2.38 | 943 | 1.94 | 3.84 | 74.8% | 46% |
| orthogonalised: posn | 69.1% | −31.9% | 3.53 | 919 | 1.84 | 2.17 | 136.6% | 87% |
| orthogonalised: all four | 25.1% | −30.7% | 1.69 | 727 | 0.87 | 0.82 | 34.9% | 94% |

Every variant loses, and doing all four at once is catastrophic. The lesson is specific and worth
keeping: **a higher rank-IC on the residual does not mean a better bet.** Orthogonalising removes
the part of each signal that agrees with recent price, and that agreement is what makes the five
signals line up on the trades that matter. Stripping the shared component raises each signal's
standalone information and destroys the composite's. `posn` shows it most starkly — residualising
a signal that is 44% past-return by construction leaves something that still makes money (OOS
136.6%) but at −31.9% drawdown, because the trades it now takes are no longer the ones the other
four confirm.

The flow signal is the exception because order-flow imbalance is contaminated by *short-horizon
reversal* (IC −0.04 at h=1, recorded at the top of this log), so the thing being removed there is
noise with the wrong sign, not shared conviction.

**Closed.** Signal construction via orthogonalisation is exhausted.

## S82 — Conviction predicts the size of the move, and it still cannot be traded
Conviction |net| has done exactly one job in this study: it scales the SIZE of the bet. The
geometry of the trade — where the stop sits, where the target sits — is uniform across every trade
in a quarter, applied identically to a 0.3-sigma reading and a 3.0-sigma one. That is an
assumption, and it had never been tested.

**The premise checks out, cleanly.** Bucketing every signal bar by conviction and measuring the
forward close excursions over the 21-bar holding horizon, in ATR units:

| conviction quintile | n | mean cv | MFE | MAE | MFE/\|MAE\| | mean fwd |
|---|---|---|---|---|---|---|
| Q1 | 675 | 0.01 | 2.05 | −1.82 | 1.130 | +0.118 |
| Q2 | 674 | 0.06 | 1.92 | −2.11 | 0.906 | −0.099 |
| Q3 | 761 | 0.17 | 2.08 | −2.01 | 1.036 | +0.037 |
| Q4 | 588 | 0.44 | 2.30 | −1.96 | 1.171 | +0.168 |
| Q5 | 675 | 1.40 | **2.30** | **−1.63** | **1.410** | **+0.334** |

Favourable excursion rises with conviction and adverse excursion *shrinks*: the strongest readings
both go further and hurt less. So the geometry should be conviction-dependent — a farther target,
and (given the smaller MAE) if anything a tighter stop.

**Every exploitation of it loses.** On the bear-inclusive 12-month plan at 8% risk, with the
quarterly selection held at the control geometry so no variant gets a second layer of search:

| variant | CAGR | MaxDD | PF | N | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|---|
| **control (uniform)** | 73.2% | **−14.8%** | 2.64 | 771 | **2.12** | **4.94** | **22%** |
| stop × cv^0.3 | 60.3% | −18.0% | 2.29 | 825 | 2.07 | 3.34 | 19% |
| stop × cv^0.5 | 49.0% | −22.3% | 1.91 | 902 | 1.90 | 2.20 | 28% |
| stop × cv^−0.3 (tighter when strong) | 74.2% | −24.0% | 2.41 | 733 | 1.81 | 3.10 | 79% |
| target × cv^0.3 | **82.3%** | −19.9% | **2.81** | 774 | 2.15 | 4.13 | 27% |
| target × cv^0.5 | 73.9% | −42.2% | 2.47 | 789 | 1.84 | 1.75 | 75% |
| stop+target × cv^0.3 | 59.9% | −23.6% | 2.11 | 876 | 1.99 | 2.53 | 29% |
| breakeven stop after 1R | 71.7% | −14.6% | 2.62 | 775 | 2.09 | 4.90 | 24% |
| breakeven stop after 1.5R | 73.1% | −15.0% | 2.64 | 771 | 2.12 | 4.88 | 22% |
| ATR trail (2 ATR after 1R) | 71.5% | −15.1% | 2.55 | 786 | 2.04 | 4.72 | 27% |
| ATR trail (3 ATR after 2R) | 71.7% | −14.8% | 2.61 | 772 | 2.10 | 4.84 | 23% |

The farther target on strong signals is the only variant that raises return — 73.2% to 82.3% with
profit factor up to 2.81 — and it buys that with five points of drawdown, so Calmar falls. Every
stop variant is worse in both directions. Breakeven stops and ATR trails are *neutral*: they move
nothing, which is itself informative — the exits are not where the money is being lost.

**Why a true premise yields nothing.** The conviction exponent has already concentrated the risk
budget into exactly the Q5 bars whose excursions are favourable. Widening the target on those same
bars does not find new profit, it converts a booked profit into a give-back: the 2.30 ATR mean MFE
is a *mean*, and the trades that reach 3 R were already reaching the 2 R target. The uniform box
chosen by the quarterly grid is not laziness; it is the optimum given the sizing rule in front of
it. **Trade geometry is closed.**

## S83 — The position is sized once and frozen, and the first repair was worse than the disease
The engine opens a position only when flat and never resizes it. A marginal signal that opens a
5%-size long owns the slot for up to the timeout, so a full-conviction signal arriving two bars
later trades at the marginal signal's size. That is not a forecasting problem — the information is
on a closed bar, in the same composite the book already trusts for direction. Measured
(`research/blocked.py`, 643 trades on the bear-inclusive book):

| | mean | median |
|---|---|---|
| conviction at entry | 0.226 | 0.091 |
| peak same-sign conviction while held | **0.497** | 0.160 |

| trades whose conviction later rose ≥ | count | share | mean P&L | mean P&L, rest |
|---|---|---|---|---|
| 1.5× | 253 | 39.3% | **+413** | −4 |
| 2× | 238 | 37.0% | **+437** | −3 |
| 3× | 208 | 32.3% | +471 | +11 |

**The book enters at roughly half the conviction it goes on to see, and the trades whose conviction
rises carry the entire P&L.** By entry-conviction quintile the money is all in Q2, Q4 and Q5
(+39.6k, +24.9k, +40.5k) with Q1 and Q3 contributing −0.3k and −1.8k.

The first mechanism held the stop fixed and solved for the quantity that brought the package back
to budget, `aq = (budget − qty·|entry−stop|) / |add_price−stop|`. **The denominator is the distance
from the current price to the stop, and it shrinks as a trade loses** — so the rule added hardest
into losers, and refused to add once a trade was far enough in front that `qty·|entry−stop|` already
exceeded budget. An averaging-down machine wearing a risk budget as a disguise:

| variant | CAGR | MaxDD | PF | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|
| **no top-up (control)** | 73.2% | **−14.8%** | **2.64** | **2.12** | **4.94** | **22%** |
| top-up 2×, max 1 | 83.1% | −30.1% | 2.14 | 1.81 | 2.76 | 93% |
| top-up 2×, max 2 | 77.4% | −41.0% | 1.94 | 1.58 | 1.89 | 99% |
| top-up 2×, max 4 | 73.3% | −44.5% | 1.89 | 1.51 | 1.65 | 100% |
| top-up 1.5×, max 4 | **86.4%** | −45.5% | 1.98 | 1.57 | 1.90 | 100% |
| top-up 3×, max 4 | 74.0% | −47.3% | 1.96 | 1.56 | 1.56 | 98% |
| top-up 5×, max 4 | 71.9% | −44.1% | 2.01 | 1.63 | 1.63 | 94% |
| **SHUFFLED 2×, max 4** | 60.8% | −35.4% | 1.64 | 1.29 | 1.71 | 100% |

**The shuffled control is the reason this is not yet a closed door.** Topping up on the same
schedule with a random other bar's conviction returns 60.8%; topping up on the real conviction
returns 73.3% at essentially the same drawdown. The 12.5 points between them is signal content that
the mechanism failed to convert. The risk handling was wrong, not the premise. Repaired in S83b.

## Anatomy of the drawdowns — 66 episodes, not one accident
Before attacking the drawdown it is worth knowing whether there is a shape to attack. On the
bear-inclusive book at 8% risk over 4.5 years there are **66 distinct drawdown episodes**, 13 of
them deeper than 5% and 3 deeper than 10%:

| rank | peak | trough | recovered | depth | days down | days back |
|---|---|---|---|---|---|---|
| 1 | 2024-10-17 | 2025-02-23 | 2025-04-21 | **−14.8%** | 129 | 57 |
| 2 | 2026-07-01 | 2026-08-18 | 2026-08-20 | −11.3% | 48 | 2 |
| 3 | 2022-09-02 | 2023-01-09 | 2023-03-13 | −10.8% | 129 | 63 |
| 4 | 2024-03-03 | 2024-04-12 | 2024-07-04 | −9.4% | 40 | 83 |
| 5 | 2026-02-06 | 2026-03-19 | 2026-06-03 | −8.6% | 41 | 76 |

The max drawdown is therefore a *measurable* property rather than a single accident — good news for
every Calmar comparison in this log, which would otherwise be an argument about one observation.

Two numbers reframe the problem:

* **Daily skew +5.87, kurtosis 61.1**, on 1.44% daily vol, with the worst ten days only −5.5% to
  −3.3%. The return stream is lottery-shaped: the money arrives in a handful of enormous days and
  there is no crash risk to speak of on the losing side.
* **72% of days are spent in drawdown**, and the deepest episode is 129 days of grind — not a shock.

So the binding constraint is not a tail event that could be hedged or stopped out of. It is the
slow bleed between the big days. And the worst of those bleeds, 2024-10 to 2025-02, sits inside the
strongest trend of the whole sample — which for a book whose returns track trendiness at +0.61 is
the most surprising fact in this study and the obvious next thing to explain.

## S83b — The top-up with the sizing bug removed, and it is still a losing trade
Two repaired modes, neither with any price feedback in the sizing. Mode 1 sets the target quantity
to `budget / original_risk_unit` — exactly the size a fresh entry at this conviction would take —
and resets the stop to one risk unit from the new average entry so the package risk is the budget
by construction. Mode 2 adds the condition that the trade must not be in loss: a top-up may
reinforce a position the market is already agreeing with, never rescue one it is not.

| variant | CAGR | MaxDD | PF | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|
| **no top-up (control)** | 73.2% | **−14.8%** | **2.64** | **2.12** | **4.94** | **22%** |
| m1 conviction-unit 2×, max 1 | **92.3%** | −31.9% | 2.15 | 1.75 | 2.89 | 98% |
| m1 conviction-unit 2×, max 4 | 74.0% | −55.6% | 1.81 | 1.32 | 1.33 | 100% |
| m1 conviction-unit 3×, max 4 | 76.5% | −59.1% | 1.91 | 1.38 | 1.29 | 100% |
| m2 winners only 1.5×, max 4 | 73.7% | −61.2% | 1.82 | 1.23 | 1.20 | 100% |
| m2 winners only 2×, max 1 | 77.7% | −31.1% | 2.03 | 1.57 | 2.50 | 99% |
| m2 winners only 2×, max 4 | 56.2% | −59.2% | 1.67 | 1.11 | 0.95 | 100% |
| m2 SHUFFLED 2×, max 4 | 61.1% | −36.6% | 1.69 | 1.23 | 1.67 | 100% |

**Restricting top-ups to winners makes it worse, and that is the tell.** Adding to a long that is in
profit raises the average entry, so resetting the stop one unit below it *tightens* the stop
underneath a position that is now several times larger. A routine retracement then stops out the
big package instead of the small one. The mechanism converts a won trade into a large loss at
exactly the moment it looks safest.

The shuffled control still shows real signal content — 61.1% against 74.0% at comparable drawdown —
so conviction genuinely does keep rising on the trades that matter. It simply cannot be harvested
by adding to an open position, because the stop that made the original bet survivable is sized for
the original quantity and nothing you do to it afterwards is free.

## Attribution of the worst drawdown — it is 29 shorts into a melt-up
Splitting every trade in the deepest episode (2024-10-17 → 2025-02-23) by side and by which
signals were on when it opened:

| | n | P&L |
|---|---|---|
| long | 21 | −165 |
| **short** | **29** | **−1,351** |
| total | 50 | −1,516 (win rate 48%) |

**The hit rate does not collapse** — 48% inside the window against 47% everywhere else. The book
simply keeps selling a market that keeps going up, and the losing shorts are bigger than the
winning ones. By signal, inside the window against everywhere else:

| signal | agree n | agree P&L (in DD) | agree P&L (elsewhere) |
|---|---|---|---|
| flow | 9 | **−805** | +14,443 |
| ivol | 11 | −415 | +8,869 |
| cmpx | 13 | +271 | +15,430 |
| btcdom | 11 | −396 | +5,408 |
| fundz | 7 | −291 | +4,568 |
| posn | 23 | −209 | **+29,441** |

`posn` *opposing* the trade loses a further 596 inside the window while costing only 965 across the
other 721 trades — so positioning is not merely quiet in a melt-up, it is actively on the wrong
side and dragging the composite short.

This is the textbook failure mode of crowding data: positioning and funding turn contrarian early
in a melt-up and stay wrong for months. It also explains the paradox in the drawdown anatomy — a
book whose returns track trendiness at +0.61 losing its worst money inside the strongest trend.
The +0.61 is the *long* side working; the short side is what fails, and it fails exactly when the
trend is strongest.

**Caveat that governs everything downstream:** this rule was found by looking at the worst window,
which is how overfitting starts. S84 measures a trend gate as an overlay only. Nothing is adopted
from it — if it looks real it goes into the quarterly grid and must be chosen causally, quarter by
quarter, on trailing Calmar alone.

## S83c — The top-up, priced against the risk dial
Every top-up variant raised return and drawdown together. That is not interesting on its own,
because the risk dial does the same thing for free. The only comparison that settles the mechanism
is at matched drawdown:

| | risk | CAGR | MaxDD | PF | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|---|
| control | 8% | 73.2% | −14.8% | 2.64 | 2.12 | 4.94 | 22% |
| control | 10% | 93.7% | −18.3% | 2.64 | 2.10 | 5.13 | 52% |
| control | 12% | 117.2% | −21.6% | 2.65 | 2.10 | 5.42 | 76% |
| control | 14% | 142.1% | −25.0% | 2.66 | 2.10 | 5.68 | 91% |
| control | 16% | 169.2% | −28.2% | 2.67 | 2.10 | 6.00 | 97% |
| control | 18% | 198.1% | −31.3% | 2.69 | 2.11 | 6.33 | 100% |
| control | 20% | **222.1%** | −34.3% | 2.67 | 2.08 | 6.48 | 100% |
| top-up m1 2×, max 1 | 8% | 92.3% | −31.9% | 2.15 | 1.75 | 2.89 | 98% |
| top-up m2 2×, max 1 | 8% | 77.7% | −31.1% | 2.03 | 1.57 | 2.50 | 99% |

At the ≈−31% drawdown the top-up produces, the plain control returns about **198%**. The top-up
returns 92%. **It buys drawdown at less than half the price of the risk dial, and the mechanism is
closed for good.**

Two things in this ladder matter beyond the top-up. Profit factor and Sharpe are flat across the
whole dial (2.64→2.67, 2.12→2.08), which is the signature of a book whose shape does not change
with size — the ATR sizing is doing its job. And **Calmar rises with risk**, 4.94 at 8% to 6.48 at
20%, because compounding inside winning streaks accelerates faster than the drawdowns deepen. That
is why the honest headline is quoted at the risk that puts realised drawdown at the 20% gate rather
than at an arbitrary 8%.

## S84 — The trend gate as an overlay: a real 35% on Calmar, and a reason to distrust it
Blocking SHORT entries while price is above a long exponential average, measured as an overlay on
the existing quarterly plan (nothing adopted — see S85 for the causal test):

| variant | CAGR | MaxDD | PF | N | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|---|
| **no gate (control)** | 73.2% | −14.8% | 2.64 | 771 | **2.12** | 4.94 | 22% |
| EMA100 block shorts | 74.1% | −15.6% | 2.96 | 544 | 1.95 | 4.74 | 52% |
| EMA100 block shorts +exit | 59.1% | −23.3% | 2.47 | 608 | 1.72 | 2.54 | 67% |
| **EMA200 block shorts** | **75.6%** | **−11.3%** | **3.35** | 528 | 1.99 | **6.68** | 26% |
| EMA200 block shorts +exit | 65.5% | −11.3% | 2.95 | 590 | 1.93 | 5.78 | 16% |
| EMA200 block longs | 56.2% | −14.8% | 2.80 | 508 | 1.89 | 3.79 | 19% |
| EMA200 block both | 53.2% | −21.1% | 3.81 | 268 | 1.58 | 2.52 | 52% |
| EMA200 block both +exit | 45.7% | −10.5% | 2.89 | 394 | 1.62 | 4.33 | 15% |

The direction is coherent — gating shorts helps, gating longs hurts, gating both is worse than
either — and the sign matches the attribution exactly. Blocking only the *entry* beats also forcing
an exit, which says the damage is in initiating shorts into strength, not in holding one when the
trend turns.

**Three reasons not to believe it yet.** The rule was derived by looking at the worst drawdown. The
EMA100 version is flat (Calmar 4.74) while the EMA200 version is the best result in the study,
which is more span-sensitivity than a robust effect should show. And applied to a single fixed
configuration rather than the quarterly plan, the gate makes things *worse* — 64.7% at −22.1%
against 70.2% at −15.6% ungated — so the overlay gain is an interaction with which configurations
the selection happened to choose, not a standalone property of the gate.

S85 settles it by putting the gate into the quarterly grid as a third axis and making the selection
choose it causally, on trailing Calmar alone.

## S86 — Pick one configuration, or hold several? Blending finally wins
The quarterly selection keeps exactly one configuration out of 40 — a bet that the trailing-Calmar
ranking is informative *at the top*, which throws away whatever diversification the runners-up
would add. A single account can hold several at once, because they all trade the same instrument
and the positions simply add. S77 found blending the 12/18/24-month *lookbacks* lost to picking,
but those three selections agree with each other most quarters; configurations differ in exponent,
stop, target and hold, so they disagree far more often.

Nothing new is fitted: rank all 40 each quarter by the existing trailing-Calmar rule, hold the top
k at risk/k each.

| k | CAGR | MaxDD | PF | N | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|---|
| **1 (current book)** | 73.2% | **−14.8%** | **2.64** | 771 | 2.12 | 4.94 | **22%** |
| 2 | 74.5% | −16.4% | 2.59 | 1,502 | 2.13 | 4.55 | 22% |
| 3 | 83.1% | −16.7% | 2.72 | 2,180 | 2.21 | 4.99 | 20% |
| 5 | **87.7%** | −17.5% | 2.71 | 3,417 | **2.23** | 5.02 | 22% |
| 8 | 85.4% | −16.7% | 2.59 | 5,065 | 2.22 | 5.11 | 25% |
| 12 | 85.4% | −16.2% | 2.53 | 6,724 | 2.18 | **5.27** | 32% |
| 20 | 81.6% | −21.9% | 2.37 | 9,173 | 2.08 | 3.72 | 47% |

**Every k from 3 to 12 beats k=1 on both CAGR and Calmar**, and the curve is broad and smooth
rather than a spike — the shape a real effect has, and the reason this is not simply a new
parameter to overfit. It degrades at k=20, where the blend is reaching configurations the ranking
has already judged bad, so the ranking is doing *something*.

Two honest caveats. Reading k=12 off this table is itself in-sample selection; the defensible
adoption is a mid-range k, not the argmax. And the k=2 dip below k=1 on Calmar says the second-best
configuration each quarter is often a near-duplicate of the first — diversification only starts
paying once the blend is wide enough to hold genuinely different bets.

Blending at risk/k is the conservative model of a netted single account: P&L is additive, and where
two sleeves take opposite sides the real account pays *less* in fees than the blend charges.

## S86b — The blend gain is the RANKING, not diversification
Blending five configurations drawn **at random** each quarter, against blending the top five by
trailing Calmar:

| | CAGR | MaxDD | PF | N | Sharpe | Calmar |
|---|---|---|---|---|---|---|
| top-1 (current book) | 73.2% | −14.8% | 2.64 | 771 | 2.12 | 4.94 |
| random-5, seed 1 | 75.8% | −15.6% | 2.39 | 3,383 | 2.08 | 4.86 |
| random-5, seed 2 | 74.8% | −14.5% | 2.39 | 3,507 | 2.26 | 5.17 |
| random-5, seed 3 | 71.7% | −15.0% | 2.35 | 3,531 | 2.22 | 4.78 |
| **top-5 by trailing Calmar** | **87.7%** | −17.5% | **2.71** | 3,417 | 2.23 | **5.02** |

**Random blending is worth nothing** — 71.7–75.8% against 73.2% for the single best, with Calmar
indistinguishable. The 18% of extra return in the top-5 blend is the ranking, not the
diversification, which is the reverse of what the k=2 dip suggested. The ranking is informative
*down the list*, not just at the top: the five best trailing-Calmar configurations are all good, and
holding all five harvests that more reliably than betting everything on the single noisiest
estimate of which one is first.

Risk ladder, top-5 blend: 101.8% at −19.3% (9% risk), 117.3% at −20.7% (10%). At the 20% gate the
blend is worth about **110%**, against 105% for the single-configuration book.

## S85 — The trend gate survives the causal test
The gate demoted to a third axis of the quarterly grid — 120 configurations instead of 40, chosen
each quarter on trailing Calmar over the preceding 12 months and nothing else, with the 40-config
plan as control so the comparison also prices the 3× bigger search:

| | risk | CAGR | MaxDD | PF | N | Sharpe | Calmar |
|---|---|---|---|---|---|---|---|
| 40-config control | 8% | 73.2% | −14.8% | 2.64 | 771 | **2.12** | 4.94 |
| **120-config with gate** | 8% | **80.6%** | **−13.7%** | **3.25** | 602 | 2.07 | **5.87** |
| 40-config control | 10% | 93.7% | −18.3% | 2.64 | 775 | 2.10 | 5.13 |
| **120-config with gate** | 10% | **106.8%** | **−16.8%** | **3.30** | 604 | 2.09 | **6.34** |
| 40-config control | 12% | 117.2% | −21.6% | 2.65 | 780 | 2.10 | 5.42 |
| **120-config with gate** | 12% | **134.5%** | **−20.0%** | **3.33** | 607 | 2.10 | **6.72** |

The gate is chosen in **10 of 18 quarters**, and the gated book wins at every point on the risk
dial — more return, less drawdown, profit factor 2.64 → 3.33. At 12% risk it lands exactly on the
−20.0% gate at **134.5%**, which replaces 105.2% as the honest bear-inclusive headline.

2022 goes from −6% to +1%: the gate blocks shorts only *above* the average, so it is inactive
through the bear market, and the gain there comes from the selection choosing different
configurations once the gated variants are in the menu.

**The remaining weakness is the menu, not the selection.** Both spans in the grid, EMA100 and
EMA200, were picked after looking at the full sample. The per-quarter choice is causal; the
*candidate list* was not. S87 widens it to {100, 150, 200, 300} — spans never inspected — so the
selection has to find trend gating useful without being handed the lucky number.

## S87 — Both improvements at once, and the gate passes a menu it never saw
S85's gate menu was {EMA100, EMA200} and both spans had been inspected on the full sample before
they were offered to the selection. The per-quarter choice was causal; the *candidate list* was
not. Widening it to {100, 150, 200, 300} — two spans never looked at — tests whether the effect is
trend gating or one lucky number. 200 configurations, ranked each quarter on trailing Calmar over
the preceding 12 months.

**Gate choices, top-1 of each quarter:** none 7, EMA100 6, EMA200 4, EMA300 1 — a gate in **11 of
18 quarters**, spread across three different spans. Across the top five of every quarter: none 30,
EMA100 31, EMA150 4, EMA200 16, EMA300 9 — a gate in 60 of 90 slots. The selection reaches for
trend gating without being handed the lucky number, and the recent quarters favour EMA200/EMA300
where the narrow menu had only EMA100 to pick. **The gate is a property of trend gating, not of a
span.**

| k | CAGR | MaxDD | PF | N | Sharpe | Calmar |
|---|---|---|---|---|---|---|
| gated top-1 | 81.3% | −13.7% | **3.24** | 602 | 2.07 | 5.92 |
| **gated top-3** | 86.2% | **−12.3%** | 3.17 | 1,697 | **2.15** | **7.01** |
| gated top-5 | 85.4% | −14.1% | 3.01 | 2,643 | 2.14 | 6.08 |
| gated top-8 | 86.1% | −14.0% | 2.99 | 3,855 | 2.11 | 6.13 |
| gated top-12 | **87.2%** | −14.2% | 2.92 | 5,126 | 2.10 | 6.15 |

**Calmar 7.01 at the top-3 blend is the best measured in this study**, against 4.94 for the
ungated single-configuration book — a 42% improvement from two changes that between them fit one
new number (k). Risk ladder on the top-5: 105.2% at −17.4% (10%), 132.2% at −21.1% (12%), 164.4%
at −24.4% (14%).

The two improvements compose only partially. Gate alone (S85) gave Calmar 6.72 at the 20% gate;
blend alone (S86) gave 5.27; together 7.01 rather than anything like the sum. They overlap because
both work by the same route — removing the trades where the configuration and the regime disagree.

**Note on bootstrap risk.** The blends carry a materially worse P(DD>20%) than their realised
drawdown suggests — 45% for the gated top-5 at 8% risk against a realised −14.1%. Holding several
configurations smooths the realised path but does not thin the tail of the return distribution, so
the resampled drawdown distribution is not improved as much as the single realised number implies.
The realised max drawdown is the more flattering of the two measures and should be read that way.

## S88 — What is the trend gate measuring? Price level, and nothing subtler
"Price above its long average" conflates three claims: *direction* (the trend is up), *strength*
(the move is efficient rather than choppy) and *level* (price is above a reference, whatever the
path). S72 measured that book returns track market trendiness at +0.61, and S73/S80 closed
trendiness as a *sizing* input in both directions — but it was never tested as a *directional
filter*, which asks nothing of persistence: the gate only has to describe the bar it stands on.

So the menu became four questions rather than four spans, each at 100 and 200 bars, chosen
causally by the quarterly rule: `ema` (price > EMA), `mom` (n-bar return > 0, direction alone),
`slope` (the average rising), `er` (efficiency ratio > 0.35 **and** the n-bar return > 0 —
direction and strength). 360 configurations.

**Which gate the selection reaches for:**

| | none | ema | mom | slope | er |
|---|---|---|---|---|---|
| chosen top-1 (of 18) | 5 | **8** | 2 | 3 | **0** |
| chosen top-5 (of 90) | 16 | **37** | 11 | 8 | 18 |

`ema` dominates at both depths. **`er` is never chosen first** and appears in the top five only as
a near-tie, so trend *strength* adds nothing once direction is known. `mom` — direction with no
reference level — is picked twice. The gate is about **where price sits relative to a smoothed
reference**, not about direction alone and not about how efficient the move is.

**And widening the menu made the book worse:**

| | CAGR | MaxDD | PF | Sharpe | Calmar |
|---|---|---|---|---|---|
| S87 ema-only menu, top-1 | 81.3% | −13.7% | 3.24 | 2.07 | **5.92** |
| S88 four-kind menu, top-1 | 77.8% | −23.2% | 2.99 | 1.93 | 3.35 |
| S87 ema-only menu, top-3 | 86.2% | −12.3% | 3.17 | 2.15 | **7.01** |
| S88 four-kind menu, top-3 | 81.0% | −15.2% | 2.89 | 2.10 | 5.34 |
| S87 ema-only menu, top-5 | 85.4% | −14.1% | 3.01 | 2.14 | 6.08 |
| S88 four-kind menu, top-5 | 84.1% | −13.2% | 2.89 | 2.16 | 6.36 |

Top-1 Calmar falls from 5.92 to 3.35 and the drawdown nearly doubles. 90 extra configurations gave
the trailing-Calmar rule 90 more chances at a lucky window, and it took them. Only the widest
blend recovers, and even then it does not reach the ema-only top-3.

**This is the cleanest measurement of search cost in the study.** The candidates added were not
junk — `mom` and `slope` are reasonable trend definitions and `er` is the variable that correlates
+0.61 with returns. Adding sensible-but-redundant options to a selection grid still costs real
performance, because the selection cannot tell a genuinely better configuration from a luckier
one. The ema-only menu was already right, and S87 stands.

**An operational note.** The first run of this file died silently after seven quarters and lost
~2,500 backtests because the ranking cache was written only at the end. It now checkpoints after
every quarter.

## S89 — The gate is a step, and the sample cannot resolve anything finer
Blocking every short while price is above its average is a step function, which asserts that a
short one dollar above the average is as bad as one thirty percent above. Price is above EMA200 on
52% of bars, and when it is, the median distance is **+10.1%** with a 90th percentile of +24.3% —
so there is plenty of range for a shape to show itself. Overlay on the 40-configuration plan, short
side only:

| gate shape | CAGR | MaxDD | PF | N | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|---|
| no gate (control) | 73.2% | −14.8% | 2.64 | 771 | 2.12 | 4.94 | 22% |
| **binary at the average** | **75.6%** | −11.3% | **3.35** | 528 | 1.99 | **6.68** | 26% |
| band, allow to +2% | 69.4% | −16.0% | 2.87 | 554 | 1.99 | 4.33 | 43% |
| band, allow to +5% | 64.6% | −32.0% | 2.57 | 590 | 1.75 | 2.02 | 81% |
| band, allow to +10% | 72.6% | −11.3% | 2.89 | 643 | 2.10 | 6.42 | 19% |
| near-only, block 0 to +5% | 67.3% | −19.2% | 2.63 | 719 | 1.90 | 3.50 | 27% |
| taper over 5% | 64.3% | −14.4% | 2.86 | 587 | 2.01 | 4.46 | 28% |
| taper over 10% | 67.4% | −11.3% | 2.96 | 630 | 2.12 | 5.95 | **13%** |
| taper over 20% | 69.8% | −11.3% | 2.87 | 709 | 2.13 | 6.17 | 14% |

The binary step wins, but **the band results are the interesting ones because they are erratic**:
allowing shorts to +2% is worse than the control, +5% is catastrophic (Calmar 2.02), +10% is nearly
as good as binary. A real monotone relationship in distance-above-average cannot produce that
ordering. The shape parameter is not identifiable on this sample, and the robust finding is
**gate versus no gate**, not the precise cut.

Two things worth carrying forward. **Four different gated variants share an identical −11.3% max
drawdown**, which says the gate removes the 2024-10 → 2025-02 episode outright and what binds
afterwards is a different, gate-independent drawdown — so the realised max DD has stopped
responding to the gate and further tuning of it is measuring noise. And the **graded tapers have
materially better bootstrap risk than the binary step** (13–14% against 26% chance of breaching
20%) at three to eight points less return. Since this study's own advice is to size on the
bootstrap rather than the realised path, the taper is the defensible choice for anyone actually
trading it, even though the binary step prints the better backtest.

Given S88's lesson about search cost, the shape is **not** added as a grid axis.

## S90 — Gate the signals, not the net: funding is the whole problem
The net gate is blunt — it zeroes the entire composite's short side regardless of which signals
asked to be short. The drawdown attribution said that is heavier than necessary, so the gate was
applied to one signal's short contribution at a time.

**A correction first.** The first run of this file built the composite from the six-signal list,
which adds implied volatility as a hard zero for the 15 months before BVOL exists, diluting every
other signal by a sixth. Its control returned 62.6% at −25.7% where the same plan returns 73.2% at
−14.8%, and nothing was concluded from it. Rebuilt from `s45.unit`, the control now reproduces the
traded composite to 4.4e-16 — floating-point noise — so the control provably *is* the book.

| gated signal (short side only, above EMA200) | CAGR | MaxDD | PF | N | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|---|
| none (control) | 73.2% | −14.8% | 2.64 | 771 | 2.12 | 4.94 | **22%** |
| flow | 74.1% | −11.3% | 2.62 | 795 | 1.97 | 6.54 | 25% |
| cmpx | 60.8% | −17.8% | 2.41 | 746 | 1.94 | 3.41 | 40% |
| btcdom | 70.5% | −14.4% | 2.58 | 719 | 1.98 | 4.90 | 40% |
| **fundz** | **84.1%** | **−11.3%** | **2.92** | 762 | **2.24** | **7.43** | 19% |
| posn | 69.2% | −21.7% | 2.51 | 827 | 1.89 | 3.19 | 33% |
| ALL five | 73.7% | −14.3% | 2.92 | 651 | 1.92 | 5.14 | 39% |
| all but cmpx | 70.0% | −14.1% | 2.69 | 745 | 1.82 | 4.96 | 48% |

**Gating funding alone beats gating everything** — Calmar 7.43 against 5.14, return 84.1% against
73.7%, and it is the only variant that raises **Sharpe** (2.24 against the control's 2.12). Every
other gate buys Calmar by cutting drawdown while *lowering* Sharpe; this one improves the bet
itself. Gating `cmpx` is the worst thing on the list, which matches the attribution exactly —
`cmpx` was the one signal that *made* money inside the melt-up (+271 while flow lost 805).

The mechanism is the textbook failure of crowding data, and it is specific rather than general.
`s_fundz` is minus the funding z-score, so persistently high funding in a melt-up holds the signal
persistently short, and it stays wrong for months rather than days. The other four recover; funding
does not, because the crowding it measures is *correct* — longs really are crowded — and being
correct about crowding tells you nothing about when it unwinds.

**Not adopted on this evidence.** Five signals were tested on one sample, so the best of five is
expected to flatter itself. It also explains why per-signal gating differs from net gating at all:
zeroing each signal's negative contribution lets a bar that netted short flip to a small *long*,
which the net gate would have left flat — 651 trades under the net gate against 762 here. S91 puts
it in the quarterly grid and makes the selection choose it causally.

## S91 — The funding gate, chosen causally: real, validated, and not an improvement
S90's overlay found that gating only `fundz`'s short side beats gating the whole composite. Here
the choice is an axis of the quarterly grid — 120 configurations, gates {none, whole short side
above EMA200, funding's short side above EMA200} — with the selection choosing each quarter from
the preceding twelve months and nothing else. Grid size deliberately matches S85's, since S88
showed what widening it to 360 costs.

**The selection reaches for it.** Given a free choice among the three:

| gate chosen | top-1 (of 18) | top-3 (of 54) |
|---|---|---|
| **fundz** | **10** | **32** |
| net | 5 | 13 |
| none | 3 | 9 |

So the finding is not an artefact of having looked at the whole sample: the causal rule prefers
funding-only gating to the net gate already adopted, in most quarters.

**And it shrinks, as it should:**

| | CAGR | MaxDD | PF | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|
| S90 overlay (full-sample read) | **84.1%** | −11.3% | 2.92 | 2.24 | **7.43** | 19% |
| S91 causal, top-1 | 77.0% | −11.3% | 2.81 | 2.11 | 6.79 | 24% |
| S91 causal, top-3 (**V8**) | 81.5% | −12.3% | 2.90 | **2.18** | 6.63 | **18%** |
| S87 incumbent, top-3 (**V7**) | 86.2% | −12.3% | **3.17** | 2.15 | **7.01** | 34% |

Calmar 7.43 → 6.63 once the selection has to choose causally. That gap is the selection illusion
being removed, the same shrinkage that caught S66 and S76.

**At the 20% gate the two books are a dead heat, and V7 keeps the headline:**

| | risk | CAGR | MaxDD | PF | N | Sharpe | Calmar | P(DD>20%) |
|---|---|---|---|---|---|---|---|---|
| **V7** wide gate menu, top-3 | 14.4% | **179.0%** | −19.99% | **3.18** | 1,769 | 2.13 | 8.95 | 98% |
| **V8** funding gate, top-3 | 14.0% | 172.0% | −19.18% | 2.97 | 2,133 | **2.21** | **8.96** | **86%** |

Calmar 8.96 against 8.95 — indistinguishable. V7 wins return and profit factor; V8 wins Sharpe and
bootstrap risk. **The decider is 2022: V7 returns +3% through the bear market where V8 returns
−10%**, because the net gate suppresses the whole short side while the funding-only gate leaves
four signals free to keep selling a falling market. The bear year is the sample's hardest test and
the one there is least of, so the book that survives it stays the headline.

Note also that V8's bootstrap advantage at 8% risk (18% against 34%) **largely evaporates at the
gate** (86% against 98%). Sized so that realised drawdown lands on 20%, almost any version of this
book is likely to breach it. That is a statement about the size, not about the gate.

**The gate lever is now closed.** Four experiments — S84 overlay, S85 causal, S88 what it measures,
S89 what shape, S90/S91 which signal — established that a trend gate is real, that it reads price
against a smoothed reference rather than direction or trend strength, that its shape is a step the
sample cannot resolve further, and that funding is the signal it is mostly correcting. None of the
refinements beat the plain net gate at the 20% drawdown limit.
