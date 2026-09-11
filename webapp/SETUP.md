# Setup, explained from scratch

Three different secrets are involved and they are easy to confuse. Nothing works
properly until you know which is which.

| what | what it unlocks | where it lives | who creates it |
|---|---|---|---|
| **`APP_PASSWORD`** | your **dashboard** | Render → Environment | Render generated it |
| **Binance testnet key + secret** | placing **test** orders | GitHub → Actions secrets | you, on Binance testnet |
| your Binance account password | your real Binance login | **nowhere but your head** | you |

The third one never goes into any of this. Nothing here ever asks for it. If
anything ever does, that thing is stealing from you.

---

## 1. `APP_PASSWORD` — the lock on your own dashboard

Your dashboard is on the public internet now. Anyone who finds the URL could
open it, so it has a password. Render generated a random one for you.

**To find it:** Render → your `btcusdt-book` service → **Environment** in the
left menu → the row `APP_PASSWORD` → click the eye/reveal icon → copy it.

**To log in:** open your `.onrender.com` URL. The browser shows a grey
username/password box (that is the browser's own, not a page).

* username: `trader`
* password: the value you just copied

You can change it to something memorable: edit the value in Environment and
save. Render redeploys, and the new one applies. It is not connected to Binance
in any way — losing it costs you nothing but a reset.

## 2. Binance testnet key and secret — and why they are NOT on Render

**They do not go on Render.** Your Render dashboard is a *viewer*: it shows the
last decision and cannot place an order. The trading happens in GitHub Actions,
so the keys live there. That is deliberate — it means the public-facing thing
has no credentials on it at all.

### Getting the keys

1. Go to Binance's **futures testnet**. It is a separate site from Binance with
   separate play money — find the current address from Binance's own API docs
   rather than a link pasted anywhere, including here.
2. Sign in. It uses a GitHub login, not your Binance account.
3. Find the API key section on the page and generate a key. You get two strings:
   * an **API key** — long, public-ish, identifies you
   * an **API secret** — shown **once**. Copy it now; you cannot see it again.
4. You are given test USDT automatically. It is not real.

### Putting them where the bot can use them

GitHub → your `SplitEase` repo → **Settings** → **Secrets and variables** →
**Actions** → **New repository secret**. Add two:

| Name (exactly) | Value |
|---|---|
| `BINANCE_TEST_KEY` | the API key |
| `BINANCE_TEST_SECRET` | the API secret |

The names must match exactly — the workflow looks them up by name. GitHub hides
them permanently once saved and masks them in logs, so you cannot read them back;
if you lose one, generate a new pair on testnet and replace both.

## 3. Why your dashboard says it has no decision yet

Because nothing has decided yet. The workflow that trades is on the branch
`claude/btcusdt-strategy-research-kd9l7c`, and **GitHub only runs scheduled
workflows from the default branch.** Until it is merged to `main`, the schedule
never fires.

The dashboard reads `status/latest.json` on `main`, which right now is the
placeholder that ships with the repo. That is the correct behaviour, not a bug:
it is telling you the truth.

## 4. The order to do things in

**Step 1 — log in to your dashboard.** Confirm the password works and the page
loads. Nothing is trading; you are checking the plumbing.

**Step 2 — add the two GitHub secrets** (above).

**Step 3 — run the workflow by hand, as a dry run.**
GitHub → **Actions** → **BTCUSDT book** → **Run workflow**. Leave **arm**
unchecked. This works from any branch, so you can do it before merging.

It computes a complete decision and places nothing. When it finishes, open the
run → **Artifacts** → `decision-1`. Inside, `run.txt` is the readable version.

**Step 4 — read that output before going further.** You should see the price,
what it thinks you should hold, three sleeves with their stops, and `not sent —
not armed` at the end. If any of that looks wrong, stop and ask.

**Step 5 — merge the workflow to `main`** so the schedule starts. From then it
decides at 00:05 and 12:05 UTC, and scheduled runs arm themselves.

**Step 6 — watch for a week.** Two runs a day is fourteen a week. Count them. If
you see eleven, three decisions were skipped and your record has gaps the
backtest does not.

## 5. What "armed" means

* **Not armed** — it computes a decision and writes it down. Places nothing.
* **Armed** — it also sends the order and the stop orders.

Manual runs are dry runs unless you tick the box. Scheduled runs arm themselves.
That is why the first thing anyone does by hand is harmless.

## 6. What you are risking

At this stage: nothing. Testnet money is not real, and Binance resets those
balances periodically.

The number that matters when that changes: at the size behind the headline
return, this book's own bootstrap puts a **drawdown worse than 20% at 98%
probability**. The backtest's realised −19.99% was a lucky draw, not an
expectation. Start at 8% risk, where the same figure is 34%.
