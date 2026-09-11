# Running the bot free forever on Oracle Cloud

Oracle's **Always Free** tier has no time limit and has **Mumbai** and
**Hyderabad** regions, which Binance serves. Start to finish this is about an
hour, most of it waiting.

Read the two warnings at the bottom before you depend on it.

---

## 1. Sign up

**cloud.oracle.com → Start for free.**

* A **card is required for identity verification**. Always Free resources are
  not charged. Oracle places a small temporary authorisation and reverses it.
* **Your home region is permanent.** Choose **India South (Hyderabad)** or
  **India West (Mumbai)**. Getting this wrong means a new account later.
* Approval is usually minutes, occasionally a day. Signups do get rejected,
  often for a card the issuer blocks on foreign authorisations — a different
  card usually fixes it.

## 2. Create the machine

**Menu ☰ → Compute → Instances → Create instance.**

**Name** — `btcusdt-book`.

**Image and shape → Edit:**

* **Image** → Change image → **Canonical Ubuntu 22.04**. Do not leave it on
  Oracle Linux; every command below assumes Ubuntu.
* **Shape** → Change shape → **Ampere** → `VM.Standard.A1.Flex`, set **1 OCPU**
  and **6 GB**. That is comfortably inside the free allowance.
* If you get **"Out of host capacity"** — common for ARM — switch to
  **AMD → `VM.Standard.E2.1.Micro`**. One core, 1 GB RAM, always available, and
  enough. The setup script adds swap automatically on a box that small.

**Networking** — leave everything default. A VCN and subnet are created for you.
The bot only makes outbound connections, so no ingress rules are needed beyond
the SSH the default list already allows.

**Add SSH keys** — **Generate a key pair for me**, then **download the private
key**. You cannot download it again. Put it somewhere you will find it:

```bash
mkdir -p ~/.ssh && mv ~/Downloads/ssh-key-*.key ~/.ssh/oracle.key
chmod 600 ~/.ssh/oracle.key
```

**Create.** It is running in a minute or two. Copy the **Public IP address**.

## 3. Connect

```bash
ssh -i ~/.ssh/oracle.key ubuntu@<PUBLIC_IP>
```

The user is `ubuntu` for Ubuntu images (`opc` is for Oracle Linux). Accept the
fingerprint prompt.

## 4. Check Binance serves it — before anything else

```bash
curl -s https://fapi.binance.com/fapi/v1/time
```

* `{"serverTime":1757...}` — good, continue.
* `{"code":0,"msg":"Service unavailable from a restricted location..."}` — this
  region is restricted. Terminate the instance and rebuild in the other Indian
  region. Nothing else will help.

## 5. Install

```bash
curl -fsSL https://raw.githubusercontent.com/shreyasbangera/btcusdt-book/main/deploy/vps-setup.sh | bash
```

Read the script first if you like — piping anything to `bash` deserves that.
It checks Binance reachability, forces the clock to UTC, adds swap on a small
box, installs Python and the bot, **seeds 36 months of market data (10–20
minutes)**, installs the quarterly plan, and schedules the job **without
`--arm`** so it computes and logs and places nothing.

## 6. Add your testnet keys

```bash
nano ~/btcusdt-book/.env
```

Fill in `BINANCE_TEST_KEY` and `BINANCE_TEST_SECRET` from
testnet.binancefuture.com. Ctrl-O, Enter, Ctrl-X.

## 7. Run one by hand

```bash
cd ~/btcusdt-book && set -a && . ./.env && set +a && \
BOOK_STORE=$PWD/data/live PYTHONPATH=$PWD ./.venv/bin/python -m webapp.once
```

What you want to see:

```
  mode=test
  last bar 0h old          <- NOT 22h. This is the whole reason for the move.
  held +0.0000   target -0.0100
    #1 exp 3.0 · 3.0ATR ×2.0R · 14d   -0.0027  stop 80,932.0
  not sent — not armed
```

`last bar 0h old` is the line that proves the move worked.

## 8. Watch it for a week

```bash
tail -f ~/btcusdt-book/book.log
```

It runs at **00:05 and 12:05 UTC — 05:35 and 17:35 IST**. You should count
fourteen entries a week. Eleven means three decisions were skipped and your
record has holes.

## 9. Arm it, when you are ready

```bash
crontab -e
```

Append `--arm` to the end of the `webapp.once` command. That is the only change
between a bot that watches and a bot that trades.

---

## Two warnings

**Oracle reclaims idle Always Free compute.** Their definition of idle is
roughly: under 10% CPU, network and memory over seven days. A job that runs
twice a day meets it. Instances do get stopped, and the first you will know is
a gap in the log. **Check weekly** — `ssh` in and `tail book.log`. If it is
reclaimed, restart it from the console; the disk survives. Treat this as
expected behaviour of a free tier, not as the bot failing.

**ARM capacity comes and goes.** "Out of host capacity" on A1 shapes is normal
and can persist for days in popular regions. The AMD micro shape is always
available and is enough for this — take it rather than waiting.

## Useful commands

```bash
crontab -l                                   # is it scheduled
tail -50 ~/btcusdt-book/book.log             # what it did
cd ~/btcusdt-book && git pull                # take an update
free -h; df -h                               # memory and disk
```

## If you stop using it

**Compute → Instances → ⋮ → Terminate**, and tick *delete the boot volume*.
Always Free storage is capped, and a stopped instance still holds its share.
