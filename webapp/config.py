"""Settings, credentials and the three modes.

Keys are read from the environment or a local .env and are NEVER accepted from
the web UI, never written to disk by this app, and never logged.  The dashboard
shows the key's last four characters so you can tell which key is loaded, and
nothing else.
"""
import os, pathlib

ROOT = pathlib.Path(__file__).resolve().parent
STORE = pathlib.Path(os.environ.get("BOOK_STORE", pathlib.Path.home() / "quant/data/live"))

# paper  - no exchange contact at all, fills simulated at real prices + backtest costs
# test   - Binance USD-M futures TESTNET, fake money, real order plumbing
# live   - real money.  Requires ALLOW_LIVE=yes AND arming in the UI.
MODE = os.environ.get("BOT_MODE", "paper").lower()
ALLOW_LIVE = os.environ.get("ALLOW_LIVE", "").lower() == "yes"

FAPI_LIVE = "https://fapi.binance.com"
FAPI_TEST = "https://testnet.binancefuture.com"

# Fraction of equity risked to the stop at FULL conviction, split across the
# three sleeves.  The actual bet is this times |conviction|, which averages
# around 0.2, so a typical trade risks 2-3% of equity rather than the headline.
#
# 0.144 is the size at which the backtest's own worst losing streak came out at
# -20%.  That is ONE run of history and it was a favourable one.  Reshuffled in
# 90-day blocks the same book at this size has a typical worst streak of -25%,
# with a quarter of runs worse than -28% and one in twenty worse than -33%.
# Chosen deliberately, with that understood:
#
#     risk    yearly    typical worst    1-in-20 worse than
#     8.0%       86%             -14%                  -19%
#    12.0%      143%             -21%                  -28%
#    14.4%      179%             -25%                  -33%
#    20.0%      287%             -33%                  -43%
#
# ONE definition, read by both the web app and `python -m webapp.once`.  They
# used to carry separate literals - the same shape as the conditional-order and
# clock bugs: two places to change, and one of them gets missed.
RISK = float(os.environ.get("BOT_RISK", "0.144"))


def _env(name):
    v = os.environ.get(name, "").strip()
    return v or None


def credentials(mode=None):
    m = mode or MODE
    if m == "test":
        return _env("BINANCE_TEST_KEY"), _env("BINANCE_TEST_SECRET"), FAPI_TEST
    if m == "live":
        return _env("BINANCE_KEY"), _env("BINANCE_SECRET"), FAPI_LIVE
    return None, None, None


def key_fingerprint(mode=None):
    k, _, _ = credentials(mode)
    return f"...{k[-4:]}" if k else "not set"


def guard_live():
    """Every path to a real order goes through here."""
    if MODE != "live":
        return
    if not ALLOW_LIVE:
        raise PermissionError(
            "MODE=live but ALLOW_LIVE is not 'yes'. Set ALLOW_LIVE=yes in the "
            "environment if you genuinely intend to trade real money.")
    k, s, _ = credentials("live")
    if not (k and s):
        raise PermissionError("MODE=live but BINANCE_KEY/BINANCE_SECRET are not set.")
