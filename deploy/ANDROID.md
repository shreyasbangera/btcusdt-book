# Running the book on an old Android phone

This is the option with the fewest unknowns. Not because a phone is a good
server — it is a bad one — but because the thing that kills every other free
option is not specs. It is that **Binance refuses most datacentre IP ranges**,
and a phone on your home wifi is not one.

A 2018 phone with a cracked screen, plugged in behind the router, will run this
book more reliably than any free cloud tier, forever, for nothing.

## Before anything else

Open Termux on the phone and run:

```bash
curl -s https://fapi.binance.com/fapi/v1/time
```

`{"serverTime":1757...}` and you are fine. The eligibility message and you are
not, and nothing below will help — try the other network (home wifi if you are
on mobile data, or the reverse), and if both refuse, this phone cannot do it.

## The short version

```bash
# 1. Termux from F-DROID, not the Play Store. The Play Store build was
#    abandoned in 2020 and its package repository no longer works.
#    https://f-droid.org/packages/com.termux/

pkg install git
git clone https://github.com/shreyasbangera/btcusdt-book
cd btcusdt-book
bash deploy/termux-setup.sh
```

The script checks Binance first and stops there if the answer is no. Then it
installs Python and pandas, writes a `.env` for your testnet keys, seeds the
market data, installs a cron entry in **UTC**, and sets up a wake lock and a
boot script. Read it before you run it — it is about 120 lines and it does
install a cron job.

## The parts worth understanding

### pandas on a phone

Termux has no prebuilt pandas in its main repository, so `pip install pandas`
compiles it from source on a phone CPU — it works, and it takes 30 to 60
minutes. The script tries `tur-repo` first, which does carry prebuilt wheels,
and only falls back to the build.

It does **not** install `pyarrow`, which has no Termux build at all. It does not
need to: `panelstore.py` writes the panels as pickle when no parquet engine is
present. That change is what made this option possible, and
`tests/no_heavy_deps.py` keeps it true by blocking both modules and then making
a real decision.

### Seed on the laptop, not the phone

A cold seed is roughly 650 archive downloads. On a phone that is an hour of
work for something your laptop does in ten minutes. If you have already seeded
elsewhere:

```bash
# on the laptop
python panelstore.py convert pkl      # parquet -> pickle, in place
# then copy the whole data/live directory onto the phone
```

The phone reads either format, so this is only about speed — but the phone will
*write* pickle from then on, and `panelstore.py` deletes the other copy after a
write so you can never end up reading a stale panel of the wrong format.

### The clock

The book decides at 00:05 and 12:05 UTC — 05:35 and 17:35 IST. An Android phone
runs on local time, so the cron file gets `CRON_TZ=UTC` and UTC times, which
stay right regardless of what the phone's clock says. Check it survived:

```bash
crontab -l
```

You should see `CRON_TZ=UTC` above the schedule line. If your cron does not
honour `CRON_TZ`, use `35 5,17 * * *` instead and re-check it every time the
phone changes time zone.

### Android will kill it if you let it

This is the failure mode to actually worry about, because it is silent. Two
settings, both on the phone rather than in this repository:

1. **Settings → Apps → Termux → Battery → Unrestricted.** Without it Android
   stops `crond` within a day or two and the bot simply stops. No error, no log
   line, no missing file — just nothing.
2. **Termux:Boot** from F-Droid, opened once. The setup script writes
   `~/.termux/boot/btcusdt-book`, which re-takes the wake lock and restarts
   `crond` after a reboot. A phone that reboots at 3am and never restarts cron
   looks exactly like a phone that is working.

Keep it plugged in. A phone at 100% on a charger for years is fine; the battery
will swell eventually, which is a reason to use one you do not care about.

### Check it is alive

```bash
tail -20 ~/btcusdt-book/book.log      # every run appends
python ~/btcusdt-book/panelstore.py   # how fresh the panels are
```

The panel age is the number that matters. `webapp/once.py` refuses to trade on
data more than 13 hours old — one 12h bar plus slack — so a phone that quietly
stopped fetching will refuse to trade rather than trade on stale prices. Check
the log weekly anyway: refusing to trade for a month is not a working bot
either.

## What this costs you

Nothing in money. In attention: about a minute a week to confirm the log is
still growing, and the knowledge that a phone in a drawer is one dropped wifi
password away from missing a decision. The delay study (S92) says a missed
decision is survivable — a 3-hour delay barely moves the numbers, 6 hours does
real damage — but a week of missed decisions is not a test of the strategy, it
is a test of the phone.
