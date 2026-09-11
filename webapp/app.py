#!/usr/bin/env python3
"""Local dashboard for the BTCUSDT books.  Binds to 127.0.0.1 only.

    pip install fastapi uvicorn pandas numpy pyarrow
    python -m webapp.app

Then open http://127.0.0.1:8000

Modes, set with BOT_MODE:
    paper  (default)  no exchange contact; fills simulated at real prices with
                      the backtest's own costs
    test              Binance USD-M futures TESTNET
    live              real money; also needs ALLOW_LIVE=yes and arming here

Keys come from the environment only.  This app never accepts a key through the
browser, never writes one to disk and never logs one.
"""
import os, sys, json, pathlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import pandas as pd

from webapp import config, engine, scheduler, keys, auth, status as pubstatus
from webapp.strategies.registry import discover, get
from webapp.broker.paper import PaperBroker

app = FastAPI(title="BTCUSDT book")
app.middleware("http")(auth.middleware)


@app.get("/healthz")
def healthz():
    """Unauthenticated on purpose: a platform health check cannot present a
    password, so pointing one at an authenticated route fails every deploy.
    Returns liveness only - no account data, no configuration."""
    return dict(ok=True)
STATIC = pathlib.Path(__file__).parent / "static"
STATE = {"armed": False, "strategy": "v7", "equity": 10_000.0, "risk": 0.08,
         "last_plan": None}


def make_broker():
    if config.MODE in ("test", "live"):
        from webapp.broker.binance import BinanceFutures
        b = BinanceFutures.__new__(BinanceFutures)
        k, sec = keys.get() if config.MODE == "test" else (None, None)
        if k and sec:                      # keys entered in this session
            b.mode, b.symbol, b.recv = config.MODE, "BTCUSDT", 5000
            b.key, b.secret, b.base = k, sec, config.FAPI_TEST
            return b
        return BinanceFutures(config.MODE)
    df = pd.read_parquet(config.STORE / "panel_12h.parquet")
    return PaperBroker(lambda: float(df.close.iloc[-1]), STATE["equity"])


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text()


@app.get("/api/status")
def status():
    return dict(mode=config.MODE, allow_live=config.ALLOW_LIVE,
                key=keys.fingerprint() or config.key_fingerprint(),
                can_enter_keys=(config.MODE == "test"),
                armed=STATE["armed"], scheduler=scheduler.running(),
                next_decision=scheduler.next_decision().isoformat(timespec="minutes"),
                strategy=STATE["strategy"], equity=STATE["equity"], risk=STATE["risk"],
                strategies={n: c.description for n, c in discover().items()})


class Keys(BaseModel):
    key: str
    secret: str


@app.post("/api/keys")
def set_keys(k: Keys):
    """TESTNET ONLY. Verified against testnet before it is accepted, held in
    memory, never written to disk."""
    try:
        detail = keys.set_testnet(k.key.strip(), k.secret.strip())
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return dict(ok=True, detail=detail, key=keys.fingerprint())


@app.delete("/api/keys")
def clear_keys():
    keys.clear()
    STATE["armed"] = False
    return status()


@app.post("/api/scheduler/{action}")
async def sched(action: str):     # async so it runs ON the loop, not in a worker thread
    if action == "start":
        ok = scheduler.start(STATE, make_broker, get, engine, lambda: config.MODE)
    elif action == "stop":
        ok = scheduler.stop()
    else:
        raise HTTPException(400, "action must be start or stop")
    return dict(ok=ok, running=scheduler.running())


@app.get("/api/log")
def runtime_log():
    return list(scheduler.LOG)[-120:]


class Settings(BaseModel):
    strategy: str | None = None
    equity: float | None = None
    risk: float | None = None


@app.post("/api/settings")
def settings(s: Settings):
    if s.strategy:
        get(s.strategy)
        STATE["strategy"] = s.strategy
        STATE["armed"] = False          # changing strategy always disarms
    if s.equity is not None:
        STATE["equity"] = float(s.equity)
    if s.risk is not None:
        STATE["risk"] = max(0.0, min(float(s.risk), 0.25))
    return status()


class Arm(BaseModel):
    armed: bool
    confirm: str = ""


@app.post("/api/arm")
def arm(a: Arm):
    if a.armed and config.MODE == "live":
        config.guard_live()
        if a.confirm != "TRADE REAL MONEY":
            raise HTTPException(400, "live arming requires confirm='TRADE REAL MONEY'")
    STATE["armed"] = bool(a.armed)
    return status()


@app.get("/api/plan")
def plan():
    """Compute from local panels when they exist; otherwise show the last
    decision GitHub Actions published. A dashboard with no disk is the normal
    case on a free tier, not a degraded one."""
    try:
        strat = get(STATE["strategy"])()
        p = engine.plan_orders(strat, make_broker(), STATE["equity"], STATE["risk"])
        STATE["last_plan"] = p
        return p
    except FileNotFoundError as e:
        pub = pubstatus.fetch()
        if pub:
            pub["read_only"] = True
            return pub
        raise HTTPException(
            400, f"{e}. No local panels and STATUS_URL is not set or unreachable, "
                 f"so there is nothing to show. Either seed the panels or point "
                 f"STATUS_URL at the status file Actions publishes.")


@app.post("/api/execute")
def execute():
    if not STATE["last_plan"]:
        raise HTTPException(400, "call /api/plan first")
    r = engine.execute(STATE["last_plan"], make_broker(), STATE["armed"])
    return JSONResponse(r)


@app.post("/api/flatten")
def flatten():
    """Kill switch: cancel everything and close the position at market."""
    b = make_broker()
    b.cancel_all()
    p = b.position()
    if abs(p.qty) > 0:
        b.market("SELL" if p.qty > 0 else "BUY", abs(p.qty), note="KILL SWITCH")
    STATE["armed"] = False
    return dict(ok=True, closed=p.qty)


@app.get("/api/ledger")
def ledger():
    b = make_broker()
    return getattr(b, "b", {}).get("ledger", [])[-100:]


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 8000))
    auth.check_startup(host)
    print(f"mode={config.MODE}  key={config.key_fingerprint()}  "
          f"allow_live={config.ALLOW_LIVE}  "
          f"auth={'on' if auth.required() else 'OFF (localhost only)'}")
    uvicorn.run(app, host=host, port=port, log_level="info")
