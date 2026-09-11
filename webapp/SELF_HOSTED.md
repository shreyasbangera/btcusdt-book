# Running the bot on your own machine, through GitHub Actions

GitHub's own runners are refused by Binance, so the bot can compute decisions
there but never trade. A **self-hosted runner** keeps everything you already
have — the schedule, the logs, the artifacts, the dashboard publishing — and
moves only the network onto a machine Binance will talk to.

## Before anything else: check your location is served

One command on the machine you intend to use. Do not skip it — if it fails,
none of the rest is worth doing.

```bash
curl -s "https://fapi.binance.com/fapi/v1/time"
```

* **`{"serverTime":1757...}`** — you are served. Continue.
* **`{"code":0,"msg":"Service unavailable from a restricted location..."}`** —
  that machine is blocked too. A runner there changes nothing; you need a host
  in a different region.

## The catch, stated plainly

**A self-hosted runner only runs when the machine is on.** If it is asleep at
00:05 UTC the job queues and fires whenever the machine wakes, which for a
12-hour book means a late entry rather than a missed one. The engine refuses to
trade on a decision bar older than 13 hours, so a long outage stops the bot
rather than having it act on stale prices — but a few hours late is still worse
than on time.

If you have an always-on machine, this is the nicest setup available. If you do
not, a small VPS (Hetzner, Vultr, DigitalOcean — pick a served region) running
this same runner is about €4 a month and removes the problem.

## What the machine needs

* Linux or macOS, x64 or arm64
* Python 3.11+
* git
* ~2 GB free disk for the data panels
* to be on at 00:05 and 12:05 UTC

## Setting it up

**1. Get a registration token.** In your repo: **Settings → Actions → Runners →
New self-hosted runner**. Pick the OS. GitHub shows a script with a token in it
— that token expires in an hour, so do this when you are ready.

**2. Run what GitHub shows you.** It is roughly:

```bash
mkdir actions-runner && cd actions-runner
curl -o actions-runner.tar.gz -L https://github.com/actions/runner/releases/download/<version>/<file>
tar xzf actions-runner.tar.gz
./config.sh --url https://github.com/<you>/btcusdt-book --token <TOKEN>
```

Copy the command from **your** page rather than from here — the version and
filename change, and the token is yours.

`config.sh` asks three things. Press Enter for the defaults, except the label:

* runner group → Enter
* **name** → something you will recognise, e.g. `home-box`
* **additional labels** → Enter (it already has `self-hosted`)
* work folder → Enter

**3. Install it as a service** so it survives reboots and does not need a
terminal left open:

```bash
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
```

On macOS drop the `sudo`.

**4. Point the workflow at it.** No code change needed. In the repo:
**Settings → Secrets and variables → Actions → Variables → New repository
variable**:

| Name | Value |
|---|---|
| `RUNNER_LABEL` | `self-hosted` |

The workflow reads `runs-on: ${{ vars.RUNNER_LABEL || 'ubuntu-latest' }}`, so
setting the variable switches runners and deleting it switches back.

**5. Prove it works.** Actions → BTCUSDT book → **Run workflow**, arm
**unchecked**. In the log you want:

* the job picked up by your runner's name rather than a GitHub one
* **no** `funding: REST unavailable` line
* `last bar 0h old` — not 22h

That third line is the whole point. If it still says 22h, REST is still being
refused and the machine is not in a served location.

## Security

A self-hosted runner executes whatever the workflow says, on your machine.
**Never attach one to a public repository**: anyone could open a pull request
that runs code on your box. Yours is private, which is the condition that makes
this safe — keep it that way, and do not add collaborators you would not hand a
shell to.

The runner also needs no Binance keys of its own. They stay in Actions secrets
and are injected per run.

## Running it

```bash
sudo ./svc.sh status      # is it up
sudo ./svc.sh stop        # pause the bot; queued jobs wait
sudo ./svc.sh start
sudo ./svc.sh uninstall   # remove the service
```

Removing the runner entirely: **Settings → Actions → Runners → … → Remove**,
then run the `./config.sh remove --token <TOKEN>` command it gives you.

## The simpler alternative

If the Actions interface is not worth this to you, the same machine can run the
bot with two cron lines and no runner at all:

```cron
5 0,12 * * *  cd ~/btcusdt-book && BOOK_STORE=~/btcusdt-book/data/live \
  BOT_MODE=test python live/fetch.py update && python -m webapp.once --arm \
  >> ~/book.log 2>&1
```

You lose the artifacts, the dashboard publishing and the web UI for triggering
runs. You keep the bot.
