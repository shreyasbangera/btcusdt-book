#!/data/data/com.termux/files/usr/bin/bash
#
# Set up the twice-daily book on an Android phone under Termux.
#
#   pkg install git && git clone https://github.com/shreyasbangera/btcusdt-book
#   cd btcusdt-book && bash deploy/termux-setup.sh
#
# Then put your testnet keys in ~/btcusdt-book/.env and arm it. Read the script
# before running it; it is short and it installs a cron entry.
#
# WHY A PHONE. Binance refuses most datacentre ranges, so almost every free
# always-on host is useless for this regardless of its specs. A phone on a home
# connection is served. That is the whole argument, and the script checks it
# first rather than at the end.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

say() { printf "\n\033[1m%s\033[0m\n" "$*"; }

# --------------------------------------------------------------------------
say "1. Does Binance serve this phone?"
# Nothing below matters if this fails, so it is first and it is fatal.
RESP="$(curl -s --max-time 20 https://fapi.binance.com/fapi/v1/time || true)"
case "$RESP" in
  *serverTime*) echo "    yes - $RESP" ;;
  *restricted*|*Eligibility*)
    echo "    NO. Binance refuses this connection:"
    echo "    $RESP"
    echo
    echo "    This is decided by the IP address, before any key is involved,"
    echo "    and nothing in this repository can work around it. If you are on"
    echo "    mobile data, try the home wifi (and the reverse). If both refuse,"
    echo "    this phone cannot run the bot."
    exit 1 ;;
  "") echo "    no answer at all - is this phone online?"; exit 1 ;;
  *)  echo "    unexpected answer: $RESP"; exit 1 ;;
esac

# --------------------------------------------------------------------------
say "2. Python, pandas, numpy"
pkg update -y >/dev/null 2>&1 || true
pkg install -y python git cronie termux-api >/dev/null

if python -c "import pandas, numpy" 2>/dev/null; then
  echo "    already installed"
else
  # tur-repo carries PREBUILT wheels. Without it, pip builds pandas from
  # source on a phone CPU, which works but takes the better part of an hour.
  echo "    trying the prebuilt packages first (tur-repo)"
  if pkg install -y tur-repo >/dev/null 2>&1 && \
     pkg install -y python-numpy python-pandas >/dev/null 2>&1 && \
     python -c "import pandas, numpy" 2>/dev/null; then
    echo "    installed prebuilt"
  else
    echo "    no prebuilt wheels here - building from source."
    echo "    This takes 30-60 minutes on a phone. Leave it plugged in and"
    echo "    do not close Termux. 'Preparing metadata' stalls for a long"
    echo "    while without being stuck."
    pkg install -y build-essential cmake ninja libopenblas \
                   libandroid-execinfo patchelf binutils-is-llvm >/dev/null
    PYV="$(python -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    pip install setuptools wheel packaging pyproject_metadata cython meson-python versioneer
    MATHLIB=m LDFLAGS="-lpython${PYV}" pip install --no-build-isolation --no-cache-dir numpy
    LDFLAGS="-lpython${PYV}" pip install --no-build-isolation --no-cache-dir pandas
  fi
fi
# NOT pyarrow: it has no Termux build, and since panelstore.py the bot does not
# need one. The panels will be pickle here.
python -c "import pandas, numpy; print('   ', pandas.__version__, numpy.__version__)"

# --------------------------------------------------------------------------
say "3. Keys"
if [ ! -f .env ]; then
  cat > .env <<'ENV'
# Binance USD-M futures TESTNET keys, from testnet.binancefuture.com.
# NEVER put a real-money key in here.
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

# --------------------------------------------------------------------------
say "4. Market data"
export BOOK_STORE="$DIR/data/live" PYTHONPATH="$DIR"
mkdir -p "$BOOK_STORE"
[ -f "$BOOK_STORE/v7_plan.json" ] || cp plans/v7_plan.json "$BOOK_STORE/v7_plan.json"
if python panelstore.py | grep -q "rows, to"; then
  echo "    panels already here, topping up"
  python live/fetch.py update
else
  echo "    no panels yet. A cold seed is ~650 downloads and can take an hour"
  echo "    on a phone. If you have already seeded on a laptop, stop now, run"
  echo "    'python panelstore.py convert pkl' there, and copy data/live across."
  python live/fetch.py seed --months 36
fi
python panelstore.py

# --------------------------------------------------------------------------
say "5. Schedule"
# The book decides at 00:05 and 12:05 UTC. cronie honours CRON_TZ, so the times
# are written in UTC and stay correct whatever the phone's clock is set to -
# which matters, because an Android phone is on local time and this is the kind
# of thing nobody notices until the fills are twelve hours out.
LINE="cd $DIR && set -a && . ./.env && set +a && BOOK_STORE=$DIR/data/live PYTHONPATH=$DIR python live/fetch.py update >> $DIR/book.log 2>&1; BOOK_STORE=$DIR/data/live PYTHONPATH=$DIR python -m webapp.once >> $DIR/book.log 2>&1"
{
  crontab -l 2>/dev/null | grep -v "btcusdt-book" | grep -v "^CRON_TZ=UTC$" || true
  echo "CRON_TZ=UTC"
  echo "5 0,12 * * * $LINE"
} | crontab -
crond 2>/dev/null || true
echo "    cron installed, in UTC (dry run - there is no --arm on that line)"
crontab -l | sed 's/^/      /'

# --------------------------------------------------------------------------
say "6. Keep Android from killing it"
termux-wake-lock 2>/dev/null && echo "    wake lock held" || echo "    install Termux:API for the wake lock"
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/btcusdt-book <<BOOT
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
crond
BOOT
chmod +x ~/.termux/boot/btcusdt-book
echo "    boot script written to ~/.termux/boot/btcusdt-book"

cat <<DONE

Done. Three things left, and the first two are on the phone, not in here:

  1. Android settings -> Apps -> Termux -> Battery -> Unrestricted.
     Without this Android will kill crond within a day or two and the bot
     will simply stop, quietly.
  2. Install Termux:Boot from F-Droid and open it once, so the script above
     runs after a reboot. A phone that reboots at 3am and never restarts
     crond looks exactly like a phone that is working.
  3. Put your testnet keys in   $DIR/.env

Watch one decision by hand first:

  cd $DIR && set -a && . ./.env && set +a && \\
  BOOK_STORE=$DIR/data/live PYTHONPATH=$DIR python -m webapp.once

When you trust it, add --arm to the cron line:  crontab -e
Logs land in $DIR/book.log
DONE
