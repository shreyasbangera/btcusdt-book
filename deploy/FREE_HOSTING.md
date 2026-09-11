# Running it always-on for nothing

The twice-daily bot is small. Verified by import-walking `webapp/once.py`: it
needs **pandas and numpy only** — it never touches the numba backtest engine,
because the heavy part (ranking 200 configurations) happens quarterly, somewhere
else, and arrives as a committed plan file.

So the always-on machine can be almost anything. Two requirements:

1. **Binance must serve its location.** One command decides it:
   ```bash
   curl -s https://fapi.binance.com/fapi/v1/time
   ```
   `{"serverTime":...}` means yes. The eligibility message means no, and nothing
   else about that host matters.
2. **It must be awake at 00:05 and 12:05 UTC** — 05:35 and 17:35 IST.

## Option 1 — Oracle Cloud Always Free

Genuinely free with no time limit, and it has **Mumbai and Hyderabad** regions,
which Binance serves.

* cloud.oracle.com → Start for free. A card is required for identity
  verification; Always Free resources are not charged.
* Create a **VM instance**, shape `VM.Standard.A1.Flex` (ARM, 1 OCPU / 6 GB is
  ample) or `VM.Standard.E2.1.Micro` if ARM capacity is unavailable.
* Image: Ubuntu 22.04. Region: Mumbai or Hyderabad.
* SSH in and run `deploy/vps-setup.sh`.

**Two things to know before you rely on it.** ARM capacity in popular regions is
often exhausted and you may have to retry over days — the micro AMD shapes are
usually available and are enough. And Oracle reclaims Always Free compute it
considers idle; a job that runs twice a day is idle by that definition. Check
the instance is still up weekly, and treat a disappearance as expected rather
than as a failure of the bot.

## Option 2 — an old Android phone

If you have a phone in a drawer, this costs nothing and has no capacity queue.
It is always on, always charged, and on your home connection — which Binance
serves if you are in India.

```bash
# Termux from F-Droid (NOT the Play Store version, which is abandoned)
pkg update && pkg install python git cronie
pip install pandas numpy
git clone https://github.com/shreyasbangera/btcusdt-book
```

`pyarrow` has no Termux build, so the panels cannot be parquet there. Ask me to
switch the store to a pickle format and I will — it is a small change and makes
the dependency set pandas and numpy alone.

Keep the phone plugged in, disable battery optimisation for Termux, and run
`termux-wake-lock` so Android does not suspend it.

## Option 3 — anything already on in your house

A desktop that stays on, a media box, an old laptop with the lid shut and
suspend disabled. The bot uses a few seconds of CPU twice a day. If something in
the house is already running, that is the cheapest answer available.

## What does not work

| | why |
|---|---|
| GitHub-hosted runners | Binance refuses them by eligibility — measured |
| Google Cloud free tier | its free regions are US-only, which Binance restricts |
| Render / Railway free web services | they sleep when idle, so the schedule does not fire |
| AWS free tier | twelve months, then it bills |
| Cloudflare Workers | no Python runtime for pandas |

## If none of these are available

Run it by hand when you are at your machine, and **record which decisions you
missed**. A partial record honestly labelled is worth something. A partial
record you later mistake for a complete one is worth less than nothing, because
you will conclude something about the strategy from a sample that was really
about your schedule.
