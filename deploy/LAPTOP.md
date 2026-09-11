# Running the book on your laptop

This is the honest option when nothing else is available. It works. It costs
nothing. It will miss decisions, and the whole design below is about making
that visible rather than pretending otherwise.

## What you are actually signing up for

The book decides on 12h bars: **00:05 and 12:05 UTC — 05:35 and 17:35 IST**. A
server is awake then. A laptop is in a bag, or shut, or flat.

So the schedule here is **hourly**, not twice a day, and each run carries
`--once-per-bar`: the first run of a 12h bar decides, and every other run that
day exits immediately having done nothing. A laptop shut at 05:35 catches that
bar whenever it next opens. No missed-run recovery to configure, and no time
zone arithmetic — hourly is hourly everywhere.

In practice that gives each bar a window: the **00:00 UTC** bar can still be
decided any time up to 13:00 UTC (**05:35 to 18:30 IST**), and the **12:00 UTC**
bar up to 01:00 UTC (**17:35 to 06:30 IST**). Open the laptop once during the
day and once in the evening and you catch both — you do not have to be at it at
5:35 in the morning.

That buys you a **late** decision, not a free one. S92 measured the cost:

| decision delay | CAGR |
|---|---|
| on time | 73.2% |
| 30 minutes | 67.4% |
| 1 hour | 68.1% |
| 3 hours | 65.5% |
| 6 hours | 51.7% |
| 12 hours | 45.9% |

Under three hours is inside the noise. Six is real damage. Past **13 hours the
run refuses to trade at all** — acting on a bar that closed yesterday takes the
backtest's trades at prices that have already moved through most of what the
signal predicted, and a bot doing that twice a day forever is worse than one
that stops.

So: open the laptop in the morning and again in the evening and you lose almost
nothing. Leave it shut for two days and those four bars are simply gone.

## Before anything else

One command decides whether any of this can work. Run it on the laptop:

```bash
curl -s https://fapi.binance.com/fapi/v1/time
```

* `{"serverTime":1757...}` — good, carry on.
* `{"code":0,"msg":"Service unavailable from a restricted location..."}` — stop.
  Binance refuses this IP address, before any key is involved. **If you are on a
  VPN, turn it off and try again** — a VPN exit in a restricted country produces
  exactly this. Nothing in this repository can work around it.

---

# macOS and Linux

```bash
git clone https://github.com/shreyasbangera/btcusdt-book
cd btcusdt-book
bash deploy/laptop-setup.sh
```

The script checks Binance first and stops there if the answer is no. Then it
makes a virtualenv, installs pandas and numpy (that is the entire dependency
list), runs the test suite, writes a `.env`, seeds 36 months of market data
(~650 archive downloads, 10–20 minutes), writes `run.sh`, and installs an
hourly cron entry **as a dry run — no `--arm`**.

Read it before you run it. It is about 130 lines and it does install a cron job.

Then jump to [**Your testnet keys**](#your-testnet-keys).

---

# Windows

No script — the steps are short and Task Scheduler is easier to get right by
hand than to generate.

### 1. Python

Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/).
**Tick "Add python.exe to PATH"** on the first screen of the installer. Then, in
PowerShell:

```powershell
py -V
```

### 2. The code

Install [Git for Windows](https://git-scm.com/download/win) if you do not have
it, then:

```powershell
cd $HOME
git clone https://github.com/shreyasbangera/btcusdt-book
cd btcusdt-book
```

### 3. The environment

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe tests\all.py
```

The last line should end `all 3 test files passed`. If it does not, stop and
send me the output rather than carrying on.

### 4. Configuration and data

Create `.env` in the `btcusdt-book` folder (Notepad is fine — save as
"All files" so it does not become `.env.txt`):

```
BINANCE_TEST_KEY=
BINANCE_TEST_SECRET=
BOT_MODE=test
BOT_STRATEGY=v7
BOT_EQUITY=10000
BOT_RISK=0.08
```

Then seed the market data:

```powershell
$env:BOOK_STORE = "$PWD\data\live"
$env:PYTHONPATH = "$PWD"
mkdir data\live -Force
copy plans\v7_plan.json data\live\
.venv\Scripts\python.exe live\fetch.py seed --months 36
.venv\Scripts\python.exe panelstore.py
```

The seed takes 10–20 minutes. The last command should print two panels with row
counts and a recent timestamp.

### 5. The schedule

`deploy\run.bat` is the thing Task Scheduler runs. Test it once by hand first:

```powershell
deploy\run.bat
type book.log
```

Then: **Task Scheduler → Create Task** (not "Basic Task" — you need the
settings tab).

* **General** → Name: `BTCUSDT book`. Tick **Run whether user is logged on or
  not**, and **Run with highest privileges**.
* **Triggers** → New → Daily, recur every 1 day. Tick **Repeat task every
  1 hour** for a duration of **Indefinitely**.
* **Actions** → New → Start a program → Program:
  `C:\Users\<you>\btcusdt-book\deploy\run.bat`
  Start in: `C:\Users\<you>\btcusdt-book`
* **Conditions** → **untick "Start the task only if the computer is on AC
  power"**. This one is the trap: it is ticked by default, and on a laptop it
  will silently stop the bot the moment you unplug it.
* **Settings** → tick **Run task as soon as possible after a scheduled start is
  missed**.

---

# Your testnet keys

1. Go to **testnet.binancefuture.com** and log in with GitHub or Google. This is
   Binance's *futures testnet* — fake money, real order plumbing, a completely
   separate site from binance.com.
2. Scroll to the bottom of the trading page. There is an **API Key** panel with
   a key and a secret.
3. Paste them into `.env`:

```
BINANCE_TEST_KEY=your_key_here
BINANCE_TEST_SECRET=your_secret_here
```

The secret is shown once. If you lose it, generate a new pair.

**These are testnet keys and they must stay testnet keys.** `.env` is in
`.gitignore` and `BOT_MODE=test` sends every request to the testnet host. Real
keys would need `BOT_MODE=live` *and* `ALLOW_LIVE=yes`, which is deliberately
awkward. Do not make it less awkward.

# Watch one decision before arming anything

```bash
./run.sh              # macOS / Linux
deploy\run.bat        # Windows
tail -30 book.log     # or:  type book.log
```

You should see something like:

```
2026-09-11T12:05:03+00:00  mode=test  v7
  price 111,240.5   equity 5,000.00  (config said 10,000)
  bar 2026-09-11T12:00:00+00:00, 0h old
  held +0.0000   target -0.0151
    #1 exp 3.0 · 3.0ATR ×2.0R · 14d                 -0.0048  stop 114,012.1
    #2 exp 3.0 · 3.0ATR ×2.0R · 21d                 -0.0048  stop 114,012.1
    #3 exp 2.5 · 3.0ATR ×2.0R · 14d                 -0.0054  stop 114,012.1
  order: {'side': 'SELL', 'qty': 0.0151, 'notional': 1680.0}
  note:  bar 2026-09-11 12:00:00+00:00
  not sent — not armed
  record: 1/1 bars decided — complete
```

`equity 5,000.00 (config said 10,000)` means the bot sized off what the account
actually holds rather than the number in `.env`, which is what you want. The
three sleeves are V7's three configurations; they always point the same way, so
what reaches the exchange is one netted position with three reduce-only stops
resting on it.

`not sent — not armed` is correct. Nothing is placed until you add `--arm`.

Run it a second time straight away. It should say **`already decided — nothing
to do`** — that is `--once-per-bar` working, and it is what makes an hourly
schedule safe.

# Arming it

Only after you have watched a few dry runs and they look sane.

* **macOS / Linux:** `crontab -e`, and append ` --arm` to the `run.sh` line.
* **Windows:** Task Scheduler → your task → Actions → Edit → **Add arguments:**
  `--arm`.

Start at `BOT_RISK=0.08`, which is what the `.env` already says. At that setting
the book's own bootstrap puts a drawdown worse than 20% at **34% probability**,
and the backtest returns 86.2% at −12.3%. The headline 179% number runs at 14.4%
risk, where that probability is **98%**. Do not start there.

# The weekly ritual

This is the part that actually matters on a laptop. Once a week:

```bash
.venv/bin/python -m webapp.journal
```

```
record      /home/you/btcusdt-book/data/live/decisions.jsonl
from        2026-09-11 00:00Z
to          2026-09-25 12:00Z
bars        29 expected, 24 ran, 22 decided
coverage    75.9%

7 bars with no decision. Any conclusion you draw from the P&L is about
these bars being absent as much as about the strategy:
  2026-09-14 00:00Z
  2026-09-14 12:00Z
  ...
```

Missing bars is survivable. **Forgetting that you missed them is not** — that is
how you look at a 40% return over three months and conclude something about V7
when a third of the bars were never traded. The journal is append-only; nothing
rewrites it, so a bad fortnight stays in the record where it belongs.

# Keeping the laptop awake

Optional. Hourly catch-up means you do not need this, but fewer gaps is better.

**Windows:** Settings → System → Power & battery → Screen and sleep → set
"When plugged in, put my device to sleep after" to **Never**. Closing the lid
still sleeps it; change that under Control Panel → Power Options → Choose what
closing the lid does.

**macOS:** System Settings → Battery → Options → "Prevent automatic sleeping on
power adapter when the display is off". A closed lid still sleeps unless an
external display is attached, so a Mac laptop will have gaps — read the journal.

**Linux:**
```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
# and set HandleLidSwitch=ignore in /etc/systemd/logind.conf
```

# When something is wrong

| what you see | what it means |
|---|---|
| `not sent — not armed` | working as intended. Add `--arm` when ready |
| `already decided — nothing to do` | working as intended on an hourly schedule |
| `data is N h old (limit 13h)` | the laptop was shut through a bar, or the fetch is failing. The bar is lost; the journal records it |
| `Service unavailable from a restricted location` | a VPN is on, or your network is not served. Nothing here can fix it |
| `REST unavailable, extending from the archive` | fine. The archive lags about a day, so if this persists the decisions go stale and get refused |
| nothing in `book.log` for hours | the schedule is not firing. Windows: check the AC-power condition. macOS: cron needs Full Disk Access (System Settings → Privacy & Security → Full Disk Access → add `/usr/sbin/cron`) |
| `sleeves disagree on side` | should be impossible for V7. Stop and send me the output |

# The honest summary

A laptop is a worse host than a phone in a drawer, which is a worse host than a
served VPS. What it is *not* is useless: with hourly catch-up and the journal,
you get a real record of a real strategy with visible, quantified gaps. That is
a legitimate thing to learn from.

What you must not do is read the P&L without reading the journal next to it.
