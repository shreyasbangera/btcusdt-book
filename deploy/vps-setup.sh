#!/usr/bin/env bash
# One-shot setup for a fresh Ubuntu/Debian box. Installs the bot, seeds the data
# and schedules it twice a day. Idempotent - safe to run again.
#
#   curl -fsSL https://raw.githubusercontent.com/shreyasbangera/btcusdt-book/main/deploy/vps-setup.sh | bash
#
# Then put your testnet keys in ~/btcusdt-book/.env and arm it. Read the script
# before piping anything to bash - including this.
set -euo pipefail

REPO="${REPO:-https://github.com/shreyasbangera/btcusdt-book}"
DIR="${DIR:-$HOME/btcusdt-book}"

say() { printf "\n\033[1m==> %s\033[0m\n" "$*"; }

say "Checking that Binance serves this location"
# The whole point of moving off GitHub's runners. If this fails, nothing below
# is worth doing on this machine.
if curl -s --max-time 20 "https://fapi.binance.com/fapi/v1/time" | grep -q serverTime; then
  echo "    served - fapi.binance.com answers"
else
  echo "    REFUSED. Binance does not serve this host:"
  curl -s --max-time 20 "https://fapi.binance.com/fapi/v1/time" | head -c 300; echo
  echo "    Pick a different region. Nothing else here will help."
  exit 1
fi

say "Checking the clock is UTC"
# The schedule is written in UTC (00:05 and 12:05). A box set to IST would fire
# five and a half hours off and nothing would look wrong.
TZ_NOW="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo unknown)"
if [ "$TZ_NOW" != "UTC" ] && [ "$TZ_NOW" != "Etc/UTC" ]; then
  echo "    clock is $TZ_NOW - setting it to UTC so the cron times mean what they say"
  sudo timedatectl set-timezone UTC || echo "    could not change it; adjust the cron times by hand"
else
  echo "    UTC"
fi

say "Checking memory"
# Oracle's always-free micro shape has 1 GB, and pandas plus a 36-month seed is
# tight in that. A swap file costs nothing and turns an out-of-memory kill into
# a slow step.
MEM_MB=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
echo "    ${MEM_MB} MB RAM"
if [ "$MEM_MB" -lt 1800 ] && [ ! -f /swapfile ]; then
  echo "    adding a 2 GB swap file"
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap -q /swapfile \
    && sudo swapon /swapfile \
    && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null \
    && echo "    swap on"
fi

say "Installing packages"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv git curl >/dev/null

say "Fetching the bot"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone --depth 1 "$REPO" "$DIR"; fi
cd "$DIR"

say "Creating the environment"
python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cat > .env <<'ENV'
# Testnet keys from https://testnet.binancefuture.com (sign in with GitHub).
# These control PLAY MONEY. Never put production keys here until you have run
# a full quarter on testnet and read the risk note in the README.
BINANCE_TEST_KEY=
BINANCE_TEST_SECRET=
BOT_MODE=test
BOT_STRATEGY=v7
BOT_EQUITY=10000
BOT_RISK=0.08
ENV
  chmod 600 .env
  echo "    wrote .env - put your testnet keys in it"
else
  echo "    .env already exists, leaving it alone"
fi

say "Seeding market data (this takes 10-20 minutes the first time)"
set -a; . ./.env; set +a
export BOOK_STORE="$DIR/data/live" PYTHONPATH="$DIR"
./.venv/bin/python live/fetch.py update

say "Installing the plan"
mkdir -p "$BOOK_STORE"
[ -f "$BOOK_STORE/v7_plan.json" ] || cp plans/v7_plan.json "$BOOK_STORE/v7_plan.json"

say "Scheduling"
# 00:05 and 12:05 UTC, five minutes after each 12h bar closes. --arm is NOT set:
# the bot computes and logs and places nothing until you add it deliberately.
CRON="5 0,12 * * * cd $DIR && set -a && . ./.env && set +a && BOOK_STORE=$DIR/data/live PYTHONPATH=$DIR $DIR/.venv/bin/python live/fetch.py update >> $DIR/book.log 2>&1 && BOOK_STORE=$DIR/data/live PYTHONPATH=$DIR $DIR/.venv/bin/python -m webapp.once >> $DIR/book.log 2>&1"
( crontab -l 2>/dev/null | grep -v "btcusdt-book" ; echo "$CRON" ) | crontab -
echo "    cron installed (dry run - no --arm)"

say "Done"
cat <<EOF

  1. Put your testnet keys in   $DIR/.env
  2. Watch it for a week:       tail -f $DIR/book.log
  3. When you trust it, add --arm to the cron line:
         crontab -e     # append  --arm  to the webapp.once command

  Run one now by hand:
     cd $DIR && set -a && . ./.env && set +a && \\
     BOOK_STORE=$DIR/data/live PYTHONPATH=$DIR ./.venv/bin/python -m webapp.once

EOF
