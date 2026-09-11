"""Binance USD-M futures, signed REST.  Testnet and live share this code; only
the base URL and the credentials differ.

NOT EXERCISED.  The endpoints are unreachable from the environment this was
written in, so every call here is written against Binance's documented API and
has never returned a real response.  Run it against TESTNET first and read every
reply before pointing it at anything else.
"""
import hmac, hashlib, time, urllib.parse, json, subprocess
from .base import Broker, Position
from .. import config


class BinanceFutures(Broker):
    def __init__(self, mode="test", symbol="BTCUSDT", recv_window=5000):
        self.mode = mode
        self.symbol = symbol
        self.recv = recv_window
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

    def _signed(self, method, path, params=None):
        p = dict(params or {})
        p["timestamp"] = int(time.time() * 1000)
        p["recvWindow"] = self.recv
        q = urllib.parse.urlencode(p)
        sig = hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        url = f"{self.base}{path}?{q}&signature={sig}"
        return self._curl(["-X", method, "-H", f"X-MBX-APIKEY: {self.key}", url])

    def _public(self, path, params=None):
        q = "?" + urllib.parse.urlencode(params) if params else ""
        return self._curl([f"{self.base}{path}{q}"])

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
        if self.mode == "live":
            config.guard_live()
        return self._signed("POST", "/fapi/v1/order", {
            "symbol": self.symbol, "side": side, "type": kind,
            "stopPrice": f"{stop:.1f}", "quantity": f"{abs(qty):.3f}",
            "reduceOnly": "true", "workingType": "MARK_PRICE"})

    def cancel_all(self):
        return self._signed("DELETE", "/fapi/v1/allOpenOrders", {"symbol": self.symbol})

    def open_orders(self):
        return self._signed("GET", "/fapi/v1/openOrders", {"symbol": self.symbol})
