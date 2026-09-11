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
