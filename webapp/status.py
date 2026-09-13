"""Reading the last decision that GitHub Actions published.

The dashboard does not need to compute anything.  Actions already decides twice
a day and knows everything worth showing, so it publishes a small JSON and the
dashboard reads it.  That removes the dashboard's need for market-data panels
entirely - no disk, no 36-month seed on every cold start, and it works on a free
tier that offers neither.

If local panels ARE present the app computes live as before; this is the
fallback, not a replacement.
"""
import json, os, subprocess, sys, time

URL = os.environ.get("STATUS_URL", "")
_CACHE = {"at": 0.0, "data": None}
TTL = 120


def configured():
    return bool(URL)


def fetch(force=False):
    if not URL:
        return None
    if not force and _CACHE["data"] and time.time() - _CACHE["at"] < TTL:
        return _CACHE["data"]
    r = subprocess.run(["curl", "-sSL", "--max-time", "15", URL],
                       capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        return _CACHE["data"]
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        # Say so. This swallowed the error and returned the cache, so a status
        # file that was not JSON - and for a while the published one was not,
        # carrying a trailing "not sent" line after the object - looked exactly
        # like a dashboard with nothing to show yet. A parse failure is a fault,
        # not an empty state.
        print(f"status: {URL} is not valid JSON ({e}); "
              f"first 120 bytes: {r.stdout[:120]!r}", file=sys.stderr)
        return _CACHE["data"]
    data["_source"] = "published by GitHub Actions"
    data["_fetched_at"] = time.time()
    _CACHE.update(at=time.time(), data=data)
    return data
