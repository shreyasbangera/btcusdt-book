"""Runtime credential entry — TESTNET ONLY, and deliberately awkward for anything else.

Accepting an API key through a browser form is safe when the key controls play
money and unsafe when it does not, so this module refuses on three independent
checks rather than trusting a label:

  1. it only accepts keys while BOT_MODE=test
  2. it VERIFIES the key against the testnet base URL before storing it - a
     production key fails that call, so a mis-pasted live key is rejected rather
     than used
  3. it holds the key in memory only.  Nothing is written to disk, and a restart
     forgets it.

Live credentials are never accepted here.  They come from the environment, where
they are visible to you and to your machine and to nothing else.
"""
import hmac, hashlib, time, urllib.parse, json, subprocess
from . import config

_MEM = {"key": None, "secret": None}


def verify_testnet(key, secret):
    """Signed /fapi/v2/balance against TESTNET.  Returns (ok, detail)."""
    p = {"timestamp": int(time.time() * 1000), "recvWindow": 5000}
    q = urllib.parse.urlencode(p)
    sig = hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    url = f"{config.FAPI_TEST}/fapi/v2/balance?{q}&signature={sig}"
    r = subprocess.run(["curl", "-sS", "--max-time", "15",
                        "-H", f"X-MBX-APIKEY: {key}", url],
                       capture_output=True, text=True)
    if r.returncode:
        return False, f"could not reach testnet: {r.stderr[:200]}"
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return False, f"unexpected reply: {r.stdout[:200]}"
    if isinstance(data, dict) and data.get("code"):
        return False, f"testnet rejected the key: {data.get('msg', data)}"
    if isinstance(data, list):
        usdt = next((b for b in data if b.get("asset") == "USDT"), None)
        bal = usdt.get("balance") if usdt else "?"
        return True, f"verified against testnet, USDT balance {bal}"
    return False, f"unexpected reply shape: {str(data)[:200]}"


def set_testnet(key, secret):
    if config.MODE != "test":
        raise PermissionError(
            f"BOT_MODE is {config.MODE!r}. Keys can only be entered through the "
            f"browser while BOT_MODE=test, where they control play money. "
            f"Live credentials come from the environment.")
    ok, detail = verify_testnet(key, secret)
    if not ok:
        raise ValueError(detail)
    _MEM["key"], _MEM["secret"] = key, secret
    return detail


def get():
    return _MEM["key"], _MEM["secret"]


def clear():
    _MEM["key"] = _MEM["secret"] = None


def fingerprint():
    k = _MEM["key"]
    return f"...{k[-4:]} (entered in this session)" if k else None
