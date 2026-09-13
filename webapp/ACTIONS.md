# Running the book on GitHub Actions

> ## RETIRED — 2026-09-13
>
> **This does not work and is no longer scheduled.** Binance refuses most
> datacentre ranges, GitHub's runners included, so the runs could not reach the
> API reliably enough to be trusted with a decision.
>
> The `schedule:` triggers are removed, and the step that published
> `status/latest.json` is deleted — otherwise a manual diagnostic run would
> leave a one-off dry run on `main` for a dashboard to read as live state.
> `workflow_dispatch` remains, for diagnostics only.
>
> **The laptop is now the sole decision path** — see `deploy/LAPTOP.md`. The
> hourly task covers the hours it is awake, the wake task covers 05:35 / 17:35
> IST, and `python -m webapp.journal` is the only record of which 12h bars
> actually got a decision.
>
> Reviving this needs a runner on an IP Binance serves. Everything below is kept
> because it describes how that would work, not because it is running.

Zero infrastructure: GitHub's runners wake twice a day, decide, place orders on
**Binance testnet**, and exit. Nothing of yours stays switched on.

Workflow: `.github/workflows/btcusdt-book.yml` at the **repository root**.

## Two things that will otherwise waste your afternoon

**Schedules only fire from the default branch.** GitHub ignores `schedule:` on
any branch except `main`. In this repository the workflow is on `main` from the
first commit, so this is already satisfied — it matters if you ever move it to a
feature branch. Note also that the **Run workflow** button itself only appears
once the workflow exists on the default branch.

**Timing is best-effort.** Scheduled workflows are commonly delayed 10–30
minutes under load and are sometimes skipped outright. The backtest assumes a
fill at the next bar's open, so a late run is a worse fill and a skipped run is a
decision the backtest never missed. For a 12h book that is survivable. It is
still why a $4 VPS is the better answer for anything you would mind losing.

## Setup

**1. Get testnet keys.** Sign in to Binance's futures testnet (it uses a GitHub
login) and generate an API key and secret. These control play money on a separate
exchange and are not your production keys.

**2. Add them as repository secrets.** Settings → Secrets and variables →
Actions → New repository secret:

| name | value |
|---|---|
| `BINANCE_TEST_KEY` | your testnet API key |
| `BINANCE_TEST_SECRET` | your testnet API secret |

Secrets are write-only — GitHub will not show them again, and they are masked in
logs. **Never add production keys here.** The workflow pins `BOT_MODE: test` and
reads only the testnet secret names, so it cannot reach a real account even if
production keys were added by mistake.

**3. Merge the workflow to `main`** so the schedule starts firing.

**4. Do a dry run first.** Actions → BTCUSDT book → Run workflow, leave **arm**
unchecked. That computes a full decision and places nothing. Read the artifact.

**5. Watch it disarmed for a week** before letting the schedule arm itself.

## What each run does

1. checks out the repo and installs dependencies
2. restores the cached market-data panels (under a megabyte; a cold cache falls
   back to a full 36-month seed, which is slow but works)
3. tops the panels up from Binance's **public archive** — klines, funding and
   positioning all come from there, so no API key is needed to compute a
   decision, only to place an order. REST supplies the funding tail when
   reachable and is skipped with a printed warning when it is not
4. installs the quarterly plan from `plans/v7_plan.json` (see below)
5. decides, and on a **scheduled** run places the order and the reduce-only stop
   ladder; a manual run is a dry run unless you tick **arm**
6. uploads the decision and the full plan JSON as an artifact, kept 90 days
7. fails the run if no decision was reached — silence and success look identical
   in a cron job, so a run that decided nothing shows up red rather than green

## Reading it

Every run leaves `decision-<n>` under the run's artifacts: `run.txt` is what a
human reads, `plan.json` is every number the decision used, including each
sleeve's conviction, stop and target.

**Check for gaps weekly.** Two runs a day means fourteen a week. If you see
eleven, three decisions were skipped and your record has holes the backtest does
not.

## Why testnet and not paper here

In `test` mode the position and the resting stops live on Binance, so nothing
needs to survive between runs. Paper mode keeps its book in a local file, which
on a stateless runner would have to be cached or committed, and a cache eviction
would silently reset your equity. If you want paper numbers, run
`BOT_MODE=paper` somewhere with a disk.

## GitHub Actions cannot run this bot for real — measured, not assumed

Binance refuses GitHub-hosted runners outright:

```
{'code': 0, 'msg': "Service unavailable from a restricted location according to
'b. Eligibility' in https://www.binance.com/en/terms..."}
```

That is the eligibility restriction, not a transient failure. GitHub's runners
sit in Azure ranges Binance blocks. Measured from a real run:

| host | from a GitHub runner |
|---|---|
| `data.binance.vision` (the archive) | works |
| `testnet.binancefuture.com` | works |
| `fapi.binance.com` (production) | **refused** |

Two consequences, and the second is the one that matters:

**The data goes stale.** Klines, funding and positioning all fall back to the
archive, which publishes yesterday's file each morning — so decisions are made
on a bar that closed 22–23 hours ago. The backtest fills at the open of the bar
*after* the signal; acting a day late takes the same trades at prices that have
already moved through most of what the signal predicted. The book is not being
run, it is being impersonated.

**Real money is impossible here.** Live orders go to `fapi.binance.com`, which
is refused. Testnet works only because it is a different host.

So the engine **refuses to send orders when the decision bar is more than 13
hours old** — one bar period plus an hour of slack. A bot trading day-old data
twice a day forever is worse than one that stops.

### Where to run it instead

Anywhere Binance serves. The container and the cron are the same:

```cron
5 0,12 * * *  cd /opt/btcusdt-book && BOOK_STORE=/opt/btcusdt-book/data/live \
  BOT_MODE=test python live/fetch.py update && python -m webapp.once --arm \
  >> /var/log/book.log 2>&1
```

A €4 Hetzner box in Germany, a Vultr or DigitalOcean instance in Singapore, or
your own machine will all reach `fapi.binance.com`. Check your region against
Binance's terms before paying for anything.

If you want to keep the Actions interface, register that machine as a
**self-hosted runner** and change `runs-on: ubuntu-latest` to
`runs-on: self-hosted`. The workflow is then unchanged and only the network
moves.

Actions remains useful as a free dry-run harness: it can compute decisions and
publish them to the dashboard. It just cannot trade.

Testnet will tell you whether the plumbing works — orders at the right times,
three reduce-only stops against one netted position, surviving a restart
mid-position. It will not tell you whether the strategy makes money: its book is
thin, its prices drift from production, and Binance resets testnet balances
periodically.


## The quarterly plan, and why the runner does not choose it

The plan names the three configurations the book holds. Choosing them means
ranking 200 configurations by backtesting each over the trailing twelve months,
and that needs the **research data cache** — roughly 1.7 GB of parquet that is
not in this repository and would be absurd to rebuild twice a day. So the chosen
plan is committed at `plans/v7_plan.json` and the workflow just installs it.

The one in the repo was selected **as of 2026-09-11** on a 12-month lookback:

| | exponent | stop | target | hold | gate |
|---|---|---|---|---|---|
| 1 | 3.0 | 3.0 ATR | 2.0 R | 14 d | none |
| 2 | 3.0 | 3.0 ATR | 2.0 R | 21 d | none |
| 3 | 2.5 | 3.0 ATR | 2.0 R | 14 d | none |

**All three chose no gate**, which is worth understanding rather than glossing.
The trend gate earns its place across 2022–2026 as a whole; over the most recent
twelve months alone the ungated configurations ranked better. That is the
walk-forward rule working as designed — it picks what the recent past supports,
not what the full-sample study concluded — and it is also a reminder that the
gate's benefit is an average over regimes rather than a property of every year.

### Re-selecting

Due **1 January, 1 April, 1 July and 1 October**. Not in between: re-choosing
whenever convenient is exactly how a walk-forward rule turns into hindsight.

On a machine with the research data:

```bash
python live/v7_select.py --asof $(date -u +%F)
cp ~/quant/data/live/v7_plan.json plans/v7_plan.json
git commit -am "plan: quarterly selection $(date -u +%F)" && git push
```

The workflow installs whatever is committed, so the new plan takes effect on the
next run. If `$BOOK_STORE/v7_plan.json` already exists on the runner — restored
from the cache — it is left alone, so delete the cache or bump its key when you
want a new plan to take hold immediately.
