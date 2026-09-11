# Local trading dashboard

A web app you run **on your own machine**. Dashboard at `http://127.0.0.1:8000`.

## Why it is not a hosted website

Two independent reasons, either of which is decisive:

* **Signing.** Binance requires every private call to be HMAC-signed with your API
  secret. Browser JavaScript can only do that by having the secret *in the
  browser*, where any extension, any bug and anyone with the page can read it.
* **CORS.** Binance does not serve `fapi.binance.com` to browser origins, so a
  hosted page cannot reach it even if you were willing to ship the secret.

So the app runs locally and your keys never leave your machine. This app never
accepts a key through the browser, never writes one to disk, and never logs one
— it reads them from the environment and shows you the last four characters so
you can tell which key is loaded.

## Install and run

```bash
pip install fastapi uvicorn pandas numpy pyarrow
export BOOK_STORE=~/quant/data/live
python live/fetch.py seed --months 36      # once; the app needs the panels
python -m webapp.app
```

Open `http://127.0.0.1:8000`.

## The three modes

| `BOT_MODE` | what it does | needs |
|---|---|---|
| **`paper`** *(default)* | no exchange contact at all; fills simulated at the real price with the backtest's own costs — 5 bps commission, 3 bps adverse slippage | nothing |
| `test` | Binance USD-M futures **testnet**; fake money, real order plumbing | `BINANCE_TEST_KEY`, `BINANCE_TEST_SECRET` |
| `live` | **real money** | `BINANCE_KEY`, `BINANCE_SECRET`, `ALLOW_LIVE=yes`, **and** typing `TRADE REAL MONEY` in the UI |

Paper is the default deliberately. It is the only mode whose numbers are
comparable to the backtest — testnet has its own thin book and its own prices, so
a testnet fill tells you nothing about what a trade would really have cost.

**Live mode has three independent locks:** the environment variable, the
credentials, and the typed confirmation. Changing strategy disarms. The kill
switch cancels every order, closes the position at market, and disarms.

## Making the key safely

When you create the production key: **enable futures trading, disable
withdrawals, and set an IP allowlist.** There is no reason this app ever needs
withdrawal permission, and a key without it cannot move your coins off the
exchange no matter what goes wrong.

## Adding a strategy

Drop a file in `webapp/strategies/`. It is discovered automatically.

```python
from .base import Strategy, Sleeve, Decision

class MyBook(Strategy):
    name = "mybook"
    description = "One line, shown in the dropdown."
    decision_tf = "12h"
    warmup_bars = 200

    def needs(self):
        return ["panel_12h"]

    def decide(self, panels, equity, risk):
        df = panels["panel_12h"]
        px = float(df.close.iloc[-1])
        sma = df.close.rolling(50).mean().iloc[-1]
        if px <= sma:
            return Decision([], note="flat")
        stop_dist = 0.03 * px
        qty = self.size_for(equity, risk, 1.0, stop_dist, px)
        return Decision([Sleeve("above the 50", qty, stop=px - stop_dist)],
                        diagnostics={"close": px, "sma50": float(sma)})
```

A strategy answers exactly one question: *given the data and my risk budget,
what should I be holding?* It never asks what is currently held. The engine sums
the sleeves, compares against the real position, and moves the difference — so
strategies stay stateless and the awkward parts live in one place.

Return several sleeves when the strategy holds several configurations at once, as
V7 does. Each sleeve's stop becomes its own reduce-only order against the single
netted position. `webapp/strategies/v7.py` also contains a deliberately trivial
`BuyAndHold` as a second worked example.

## What is verified and what is not

**Verified:** the strategy interface, the engine's netting and ladder logic, and
the paper broker — including that a stop fires at *its own price* rather than the
ticker (the first version of the paper broker reported a 150 USDT stop-out as a
4 USDT one, which is exactly the kind of error that makes a paper record
worthless).

**Not exercised:** `webapp/broker/binance.py`. Every call in it is written
against Binance's documented API and has never returned a real response, because
the endpoints are unreachable from the environment this was built in. Run it in
`test` mode first and read every reply by hand before going near `live`.

## Risk

V7's own bootstrap puts a drawdown worse than 20% at **34% probability** at 8%
risk and **98%** at the size behind its headline return. The backtest's realised
−19.99% was a favourable draw, not an expectation. Start in `paper`, stay there
for a quarter including one quarterly re-selection, and compare your realised
signals against `strategies/s87_combined.py` before trusting anything.

---

## Running it unattended (autopilot)

The dashboard on its own is a calculator you have to press. The **Autopilot**
card makes it a bot: it decides at each 12h close (00:05 and 12:05 UTC, a few
minutes after the bar so the feed has caught up) and, if armed, sends the order
and replaces the stop ladder.

**While disarmed the autopilot still computes and logs but sends nothing.** That
is the intended way to start: turn it on, leave it disarmed, and read a week of
decisions before letting it touch anything. A disarmed bot is a live dry run,
not a dead one.

In paper mode it also watches stops every 60s, because nothing else will. On
testnet and live the exchange holds the reduce-only stops and fires them itself.

## Testnet keys through the browser

Binance's futures testnet issues its own API key and secret, and they behave
exactly like production keys against a separate exchange with play money. That
makes them safe to type into a web form in a way production keys are not, so the
app accepts them — behind three independent checks:

1. only while `BOT_MODE=test`
2. **verified against the testnet endpoint before being stored** — a production
   key fails that call, so a mis-pasted live key is rejected rather than used
3. held in memory only; nothing is written to disk and a restart forgets it

Production credentials are never accepted through the browser. They come from
the environment.

## Deploying

```bash
docker build -t btcbook -f webapp/Dockerfile .
docker run -d --name btcbook \
  -p 127.0.0.1:8000:8000 \
  -v ~/quant/data/live:/data \
  -e BOT_MODE=test \
  btcbook
```

Publish to `127.0.0.1` and reach it over an SSH tunnel, or put an
authenticating reverse proxy in front. **The app has no login of its own** —
anyone who can reach the port can arm it and place orders, so do not expose it
to the open internet.

## What testnet will and will not tell you

**Will:** whether your plumbing works. Do orders go in at the right times, do the
three reduce-only stops sit correctly against one netted position, does the bot
survive a restart mid-position, does it miss a 12h boundary. These are the
failures that actually kill live bots, and testnet finds them for free.

**Will not:** whether the strategy makes money. Testnet has its own thin order
book and its own prices, which drift from production, so a fill there says
nothing about what the trade would really have cost. Testnet balances are also
periodically reset by Binance, so a long track record there evaporates.

For judging the strategy use `BOT_MODE=paper`, which simulates fills at the
**real** price with the backtest's own costs and is therefore the only mode whose
numbers are comparable to the backtest.

**The data split that catches people.** Testnet does not carry the feeds this
strategy reads — no coin-margined `BTCUSD_PERP`, no alt-perp turnover, no
top-trader positioning metrics, and its funding is its own. Signals always come
from **production public data**, which needs no API key at all; only the orders
go to testnet. `live/fetch.py` already does this, and it is why the app needs no
credentials to compute a decision.

---

## You do not need to leave a laptop on

The long-running scheduler is convenient, not necessary. Targets only change on a
closed 12h bar, and **the stops are reduce-only orders resting on the exchange**,
so they fire whether or not anything of yours is running. The holding cap and the
flat-signal exit are both evaluated at a 12h close, which is exactly what the
backtest does.

So a process that wakes twice a day, decides, places orders and exits is not a
cut-down bot. It is the same bot, and it is *more* faithful to the backtest than a
laptop that sleeps at 3am.

```bash
python -m webapp.once --strategy v7 --equity 10000 --risk 0.08          # dry run
python -m webapp.once --strategy v7 --equity 10000 --risk 0.08 --arm    # sends
```

`--arm` is required to place anything, so a mis-fired cron job cannot trade.

### Where to run it

| | cost | reliability | notes |
|---|---|---|---|
| **Small VPS** (Hetzner, Vultr, DigitalOcean) | ~$4–6/mo | high | the straightforward answer; run the container, or just two cron lines |
| **Oracle Cloud Always Free** | $0 | high | genuinely free ARM instances; the container builds on ARM |
| **Raspberry Pi at home** | one-off | high | ~3 W. Needs your home internet to stay up |
| **GitHub Actions** (`.github/workflows/trade.yml`) | $0 | **best-effort** | see the caveat below |
| **Cloud Run Jobs / Lambda + EventBridge** | ~$0 | high | a container or zip on a cron trigger; no idle cost |

Two cron lines on a VPS are all it takes:

```cron
5 0,12 * * *  cd /opt/quant && BOOK_STORE=/opt/quant/data BOT_MODE=test \
  python live/fetch.py update && python -m webapp.once --arm >> /var/log/book.log 2>&1
```

### The GitHub Actions caveat

Scheduled workflows are **best-effort**. Under load they are commonly delayed by
10–30 minutes and can be skipped outright. The backtest assumes a fill at the
next bar's open, so a late run is a worse fill and a skipped run is a decision
the backtest never missed. For a 12h book that is survivable, and it is still
the reason a $4 VPS is the better answer for anything you mind losing.

Whatever you use, **log every run and check for gaps.** A week of silently
missed decisions makes the comparison against the backtest meaningless, and
silence looks identical to "nothing to do".
