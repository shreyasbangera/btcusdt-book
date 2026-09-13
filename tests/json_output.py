#!/usr/bin/env python3
"""`--json` must put a JSON document on stdout and nothing else.

    python tests/json_output.py

WHY THIS EXISTS
---------------
`webapp/once.py --json > plan.json` wrote a valid plan object followed by a
human line:

    }
      not sent - not armed

so the file was not JSON. The GitHub Actions workflow copied it to
`status/latest.json` and pushed it; `webapp/status.py` did `json.loads`, caught
JSONDecodeError, and returned its cache - which on a cold dashboard is None. A
dashboard with a broken feed and a dashboard with no data yet looked identical,
and the published file stayed broken for days.

Every element of that is the same failure this project keeps hitting: output
that nobody parses, an exception that nobody surfaces, and two code paths where
only one was guarded. The journal summary line WAS guarded by `if not a.json`.
The SENT line beside it was not.

So this pins the contract rather than the one line: under `--json`, stdout
parses as exactly one JSON object. Anything human goes to stderr, where it is
still visible in a log and cannot corrupt a document.

No network: runs against the paper broker on a synthetic store.
"""
import sys, os, json, pathlib, subprocess, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

FAIL = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


def main():
    import synth, pandas as pd
    store = pathlib.Path(tempfile.mkdtemp(prefix="jsonout-"))
    # A bar that closed an hour ago, so the run is tradeable rather than stale.
    last = (pd.Timestamp.now(tz="UTC").floor("12h") - pd.Timedelta(hours=12))
    synth.write(store, last)

    env = dict(os.environ, BOOK_STORE=str(store), BOT_MODE="paper",
               PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-m", "webapp.once", "--json", "--dry-run"],
                       capture_output=True, text=True, cwd=str(ROOT), env=env)

    print("1. stdout is a document")
    check("the command ran", r.returncode in (0, 1), f"exit {r.returncode}")
    check("stdout is not empty", bool(r.stdout.strip()), f"{len(r.stdout)} bytes")
    try:
        obj = json.loads(r.stdout)
        check("stdout parses as JSON with nothing trailing", True,
              f"{len(r.stdout)} bytes, {len(obj)} keys")
    except json.JSONDecodeError as e:
        check("stdout parses as JSON with nothing trailing", False, str(e))
        print("\n  last 120 bytes of stdout:")
        print("   ", repr(r.stdout[-120:]))
        obj = None

    print("\n2. it is the plan, not some other object")
    for k in ("ts", "strategy", "mode", "price", "bar", "position", "target",
              "sleeves", "conflict"):
        check(f"carries '{k}'", isinstance(obj, dict) and k in obj)

    print("\n3. the human lines went to stderr, not into the document")
    check("the SENT/not-sent line is on stderr",
          "sent" in r.stderr.lower(), repr(r.stderr.strip()[-70:]))
    check("and is absent from stdout", "not sent" not in r.stdout)
    check("the journal summary is absent from stdout", "record:" not in r.stdout)

    print()
    if FAIL:
        print(f"FAILED: {len(FAIL)} check(s): {', '.join(FAIL)}")
        return 1
    print("PASS  --json emits one JSON object and nothing else")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
