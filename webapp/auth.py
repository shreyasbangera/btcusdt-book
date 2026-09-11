"""A password gate, because the app can arm itself and place orders.

Anyone who can reach the port can arm the bot, so the moment this leaves
localhost it needs a lock.  This is deliberately the simplest thing that is
actually safe for one operator over HTTPS:

  * HTTP Basic, compared with `secrets.compare_digest` so the check does not
    leak the password's length or prefix through timing
  * the password comes from APP_PASSWORD in the environment - there is no
    default, and with none set the app refuses to start unless it is bound to
    localhost, so "I forgot to set it" cannot quietly publish an open bot
  * every route is covered, including the API, not just the dashboard

It is not a user system.  One operator, one password.  If several people need
access, put a real identity proxy in front instead of growing this.
"""
import os, secrets
from fastapi import Request, HTTPException
from fastapi.responses import Response

USER = os.environ.get("APP_USER", "trader")
PASSWORD = os.environ.get("APP_PASSWORD", "")
PUBLIC = os.environ.get("APP_PUBLIC", "").lower() == "yes"


def required():
    """True when a password must be presented."""
    return bool(PASSWORD)


def check_startup(host: str):
    """Refuse to serve the open internet without a password."""
    if PASSWORD:
        return
    if host not in ("127.0.0.1", "localhost", "::1") and not PUBLIC:
        raise SystemExit(
            f"refusing to bind {host} with no APP_PASSWORD set.\n"
            f"This app can arm itself and place orders, so an open port is an "
            f"open account.\n"
            f"Set APP_PASSWORD, or bind 127.0.0.1, or set APP_PUBLIC=yes if you "
            f"genuinely intend an unauthenticated bot on this interface.")


def _unauthorized():
    return Response(status_code=401, content="authentication required",
                    headers={"WWW-Authenticate": 'Basic realm="BTCUSDT book"'})


OPEN_PATHS = {"/healthz"}      # platform health checks cannot authenticate


async def middleware(request: Request, call_next):
    if request.url.path in OPEN_PATHS or not required():
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        import base64
        try:
            raw = base64.b64decode(header[6:]).decode("utf-8", "replace")
            user, _, pw = raw.partition(":")
        except Exception:
            return _unauthorized()
        ok_u = secrets.compare_digest(user, USER)
        ok_p = secrets.compare_digest(pw, PASSWORD)
        if ok_u and ok_p:
            return await call_next(request)
    return _unauthorized()
