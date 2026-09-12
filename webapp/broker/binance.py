"""Binance USD-M futures, signed REST.  Testnet and live share this code; only
the base URL and the credentials differ.

The market-order path was exercised the moment the bot was first armed.  The
CONDITIONAL path was not, and it was broken the whole time: Binance moved
STOP_MARKET / TAKE_PROFIT_MARKET off POST /fapi/v1/order to a separate Algo
Service on 2025-12-09, and the old endpoint now answers -4120 "Order type not
supported for this endpoint".  Every stop and take-profit this bot ever tried
to place was rejected, and three separate things hid it:

  * `curl -sS` has no -f, so an HTTP 400 is not a failure and the JSON error
    body parsed as if it were a fill;
  * `execute()` reported sent=True without looking at what came back;
  * `once.py` printed SENT and never logged the replies.

So a position ran with no stop behind a log that said everything worked.  The
fix is the four endpoints below plus `_check`, which turns an error payload
into an exception instead of a plausible-looking dict.

    place        POST   /fapi/v1/algoOrder        algoType=CONDITIONAL, triggerPrice
    list open    GET    /fapi/v1/openAlgoOrders
    cancel one   DELETE /fapi/v1/algoOrder        algoId
    cancel all   DELETE /fapi/v1/algoOpenOrders

Plain (non-conditional) orders still use /fapi/v1/order, and the two kinds are
listed and cancelled separately - so anything touching resting orders has to do
both, or it silently ignores every stop the book has.
"""
import hmac, hashlib, time, urllib.parse, json, subprocess
from .base import Broker, Position
from .. import config


class BinanceError(RuntimeError):
    """A rejection Binance actually sent, rather than one we invented."""

    def __init__(self, payload, path=""):
        self.code = payload.get("code")
        self.msg = payload.get("msg", "")
        self.path = path
        super().__init__(f"{path} rejected: [{self.code}] {self.msg}")


class BinanceFutures(Broker):
    # Binance rejects any signed request timestamped more than 1000ms AHEAD of
    # its own clock, and that ceiling is hard - recvWindow only widens the
    # tolerance for being late, never for being early. A laptop one second fast
    # therefore fails every order with -1021 while looking perfectly healthy to
    # its owner, which is what happened the first evening this ran unattended.
    # So the timestamp is taken from the exchange's clock, not the machine's.
    CLOCK_TTL = 1800.0                       # re-read the offset every 30 min

    def __init__(self, mode="test", symbol="BTCUSDT", recv_window=5000):
        self.mode = mode
        self.symbol = symbol
        self.recv = recv_window
        self._skew = None                    # serverTime - localTime, in ms
        self._skew_at = 0.0
        self.key, self.secret, self.base = config.credentials(mode)
        if not (self.key and self.secret):
            raise PermissionError(f"no API credentials for mode={mode!r}")
        if mode == "live":
            config.guard_live()

    # -- transport ---------------------------------------------------------
    def _curl(self, args):
        r = subprocess.run(["curl", "-sS", "--max-time", "20", *args],
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"request failed: {r.stderr[:300]}")
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"non-JSON reply: {r.stdout[:300]}")

    @staticmethod
    def _check(reply, path=""):
        """Binance signals rejection in the BODY, not the exit status.

        `curl -sS` without -f treats HTTP 400 as success, so every error arrives
        here as a perfectly valid dict {"code": -4120, "msg": "..."}. Without
        this, a rejected order is indistinguishable from a filled one.
        Successful payloads never carry a negative `code`.
        """
        if isinstance(reply, dict):
            code = reply.get("code")
            if isinstance(code, int) and code < 0:
                raise BinanceError(reply, path)
        return reply

    def _skew_ms(self, force=False):
        """How far this machine's clock is behind Binance's, in milliseconds.

        Measured against GET /fapi/v1/time and cached, because one request per
        order to ask the time is wasteful and one per half hour is plenty for
        drift this size.
        """
        if force or self._skew is None or time.time() - self._skew_at > self.CLOCK_TTL:
            t = self._curl([f"{self.base}/fapi/v1/time"])
            self._skew = int(t["serverTime"]) - int(time.time() * 1000)
            self._skew_at = time.time()
        return self._skew

    def _signed(self, method, path, params=None, _retry=True):
        p = dict(params or {})
        p["timestamp"] = int(time.time() * 1000) + self._skew_ms()
        p["recvWindow"] = self.recv
        q = urllib.parse.urlencode(p)
        sig = hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        url = f"{self.base}{path}?{q}&signature={sig}"
        try:
            return self._check(
                self._curl(["-X", method, "-H", f"X-MBX-APIKEY: {self.key}", url]),
                f"{method} {path}")
        except BinanceError as e:
            # -1021 timestamp outside recvWindow, -1022 bad signature: both can
            # mean the cached offset went stale (the machine's clock stepped, or
            # it woke from sleep). Re-read the exchange clock and try once more.
            # Only once - a retry loop against an order endpoint is how one
            # intended trade becomes several.
            if _retry and e.code in (-1021, -1022):
                self._skew_ms(force=True)
                return self._signed(method, path, params, _retry=False)
            raise

    def _public(self, path, params=None):
        q = "?" + urllib.parse.urlencode(params) if params else ""
        return self._check(self._curl([f"{self.base}{path}{q}"]), f"GET {path}")

    # -- Broker ------------------------------------------------------------
    def price(self):
        return float(self._public("/fapi/v1/ticker/price",
                                  {"symbol": self.symbol})["price"])

    def position(self):
        acct = self._signed("GET", "/fapi/v2/account")
        eq = float(acct["totalWalletBalance"]) + float(acct["totalUnrealizedProfit"])
        for p in acct.get("positions", []):
            if p["symbol"] == self.symbol:
                return Position(float(p["positionAmt"]), float(p["entryPrice"]), eq)
        return Position(0.0, 0.0, eq)

    def market(self, side, qty, note=""):
        if self.mode == "live":
            config.guard_live()
        return self._signed("POST", "/fapi/v1/order", {
            "symbol": self.symbol, "side": side, "type": "MARKET",
            "quantity": f"{abs(qty):.3f}", "newOrderRespType": "RESULT"})

    def place_stop(self, side, qty, stop, kind="STOP_MARKET"):
        """One reduce-only conditional order on the Algo endpoint.

        Three things differ from a plain order and all three are mandatory:
        the path, `algoType=CONDITIONAL`, and `triggerPrice` where a plain
        order would say `stopPrice`.
        """
        if self.mode == "live":
            config.guard_live()
        q = f"{abs(qty):.3f}"
        if float(q) <= 0:
            # BTCUSDT steps in 0.001. A sleeve smaller than that rounds to
            # "0.000", which Binance rejects - and a silent skip here would
            # leave the position short of protection with nothing in the log.
            raise BinanceError(
                {"code": -1111,
                 "msg": f"quantity {abs(qty):.6f} rounds to {q}, below the "
                        f"0.001 step - cannot place {kind}"},
                "POST /fapi/v1/algoOrder")
        return self._signed("POST", "/fapi/v1/algoOrder", {
            "symbol": self.symbol, "side": side,
            "algoType": "CONDITIONAL", "type": kind,
            "triggerPrice": f"{stop:.1f}", "quantity": q,
            "reduceOnly": "true", "workingType": "MARK_PRICE"})

    def cancel_all(self):
        """Both order books. Conditional orders are NOT covered by
        allOpenOrders, so cancelling only that leaves every stop resting.

        A cancel is allowed to fail: "there was nothing to cancel" is a normal
        state, and aborting the run over it would leave the position with no
        ladder at all. The rejection is RETURNED rather than swallowed, so the
        caller can put it in the log - which is the distinction that made this
        whole class of bug invisible in the first place.
        """
        out = {}
        for name, path in (("plain", "/fapi/v1/allOpenOrders"),
                           ("algo", "/fapi/v1/algoOpenOrders")):
            try:
                out[name] = self._signed("DELETE", path, {"symbol": self.symbol})
            except BinanceError as e:
                out[name] = {"code": e.code, "msg": e.msg}
        return out

    def open_orders(self):
        """Plain and conditional together, so a caller counting resting orders
        sees the stops. Querying only /fapi/v1/openOrders returns [] for a
        position that is fully protected."""
        plain = self._signed("GET", "/fapi/v1/openOrders", {"symbol": self.symbol})
        algo = self._signed("GET", "/fapi/v1/openAlgoOrders", {"symbol": self.symbol})
        out = list(plain) if isinstance(plain, list) else []
        out += list(algo) if isinstance(algo, list) else []
        return out
