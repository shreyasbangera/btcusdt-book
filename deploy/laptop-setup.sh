#!/usr/bin/env bash
#
# Run the book on a laptop (macOS or Linux). For Windows, deploy/LAPTOP.md has
# the Task Scheduler steps - the Python side is identical.
#
#   git clone https://github.com/shreyasbangera/btcusdt-book
#   cd btcusdt-book && bash deploy/laptop-setup.sh
#
# WHY HOURLY AND NOT TWICE A DAY
# ------------------------------
# The book decides at 00:05 and 12:05 UTC. A server can be relied on to be
# awake then; a laptop cannot, and a schedule that fires twice a day onto a
# closed lid simply misses the bar. So this installs an HOURLY job with
# --once-per-bar: the first run of each 12h bar decides, every other run that
# day exits immediately having done nothing, and a laptop that was shut at
# 05:35 catches the bar whenever it next opens.
#
# That is a DELAYED decision, not a free one. S92 measured it: on time 73.2%
# CAGR, 30 minutes late 67.4%, three hours 65.5%, six hours 51.7%. Under three
# hours is inside the noise. Past thirteen the run refuses to trade at all,
# because acting on a bar that closed yesterday takes the backtest's trades at
# prices that have already moved through most of what the signal predicted.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
say() { printf "\n\033[1m%s\033[0m\n" "$*"; }

# --------------------------------------------------------------------------
say "1. Does Binance serve this laptop?"
RESP="$(curl -s --max-time 20 https://fapi.binance.com/fapi/v1/time || true)"
case "$RESP" in
  *serverTime*) echo "    yes - $RESP" ;;
  *restricted*|*Eligibility*)
    echo "    NO. Binance refuses this connection:"
    echo "    $RESP"
    echo
    echo "    This is decided by your IP address, before any key is involved."
    echo "    If you are on a VPN, turn it off and try again - a VPN exit in a"
    echo "    restricted country looks exactly like this."
    exit 1 ;;
  "") echo "    no answer - is this laptop online?"; exit 1 ;;
  *)  echo "    unexpected answer: $RESP"; exit 1 ;;
esac

# --------------------------------------------------------------------------
say "2. Python"
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "    no python3 on PATH. Install Python 3.11+ and re-run."; exit 1; }
"$PY" -c 'import sys; assert sys.version_info >= (3,10), sys.version' \
  || { echo "    Python 3.10+ required; found $("$PY" -V)"; exit 1; }
echo "    $("$PY" -V) at $PY"

[ -d .venv ] || "$PY" -m venv .venv
VPY="$DIR/.venv/bin/python"
"$VPY" -m pip install -q --upgrade pip
"$VPY" -m pip install -q -r requirements.txt
echo "    installed: $("$VPY" -c 'import pandas,numpy;print("pandas",pandas.__version__,"numpy",numpy.__version__)')"

say "3. The tests, before anything touches an exchange"
"$VPY" tests/all.py >/dev/null && echo "    all passed" || { echo "    TESTS FAILED - stopping"; exit 1; }

# --------------------------------------------------------------------------
say "4. Keys"
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
say "5. Market data"
export BOOK_STORE="$DIR/data/live" PYTHONPATH="$DIR"
mkdir -p "$BOOK_STORE"
[ -f "$BOOK_STORE/v7_plan.json" ] || cp plans/v7_plan.json "$BOOK_STORE/v7_plan.json"
if "$VPY" panelstore.py | grep -q "rows, to"; then
  echo "    panels present, topping up"
  "$VPY" live/fetch.py update
else
  echo "    no panels yet - seeding. ~650 archive downloads, 10-20 minutes."
  "$VPY" live/fetch.py seed --months 36
fi
"$VPY" panelstore.py

# --------------------------------------------------------------------------
say "6. Schedule, hourly"
RUN="$DIR/run.sh"
cat > "$RUN" <<RUNEOF
#!/usr/bin/env bash
# One attempt at the current bar. Safe to run as often as you like: with
# --once-per-bar every run after the first of a bar exits having done nothing.
cd "$DIR"
set -a; . ./.env; set +a
export BOOK_STORE="$DIR/data/live" PYTHONPATH="$DIR"
{
  date -u +"--- %Y-%m-%dT%H:%M:%SZ"
  "$VPY" live/fetch.py update || echo "fetch failed; deciding on what we have"
  "$VPY" -m webapp.once --once-per-bar "\$@"
} >> "$DIR/book.log" 2>&1
RUNEOF
chmod +x "$RUN"
echo "    wrote $RUN"

# Hourly, on the hour. No UTC gymnastics needed: hourly is hourly in every time
# zone, and --once-per-bar decides which hour matters. This is the reason the
# schedule is hourly rather than twice daily - it removes an entire class of
# clock bug along with the sleeping-laptop problem.
CRON="0 * * * * $RUN"
( crontab -l 2>/dev/null | grep -v "btcusdt-book" || true ; echo "$CRON" ) | crontab -
echo "    cron installed (dry run - there is no --arm on that line)"
crontab -l | grep btcusdt-book | sed 's/^/      /'

cat <<DONE

Done. What is left:

  1. Put your testnet keys in   $DIR/.env
     (testnet.binancefuture.com -> API Key. Testnet only. Never a real key.)

  2. Watch one decision by hand:
         $RUN
         tail -30 $DIR/book.log

  3. When you trust it, arm it:
         crontab -e      # append  --arm  to the run.sh line

  4. Read the record weekly - this is the part that matters on a laptop:
         $VPY -m webapp.journal

     It tells you how many 12h bars actually got a decision and lists the ones
     that did not. A laptop WILL miss bars. Missing some is survivable; not
     knowing which ones is what turns a result into a wrong conclusion.

macOS: cron needs Full Disk Access. System Settings -> Privacy & Security ->
Full Disk Access -> + -> Cmd-Shift-G -> /usr/sbin/cron. Without it the job runs
but cannot read files in your home directory.

Linux laptops: a closed lid usually suspends. Either accept the gaps and read
the journal, or disable suspend:
    sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
    # and HandleLidSwitch=ignore in /etc/systemd/logind.conf
DONE
