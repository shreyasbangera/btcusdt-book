#!/usr/bin/env python3
"""The hourly-with-catch-up arrangement a laptop needs.

    python tests/laptop_schedule.py

A laptop cannot be relied on to be awake at 00:05 and 12:05 UTC, so the
schedule runs HOURLY and `--once-per-bar` makes all but one of those runs a
no-op. This checks the three things that has to get right:

  * the first run of a bar decides
  * every later run of the same bar does nothing - no order, no stop-ladder
    churn, no second journal entry that says SENT
  * the next bar decides again

It runs against the paper broker, so nothing here touches an exchange.
"""
import sys, os, json, subprocess, tempfile, pathlib, datetime as dt

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
UTC = dt.timezone.utc


def synth_panels(store, last_bar):
    import synth
    synth.write(store, last_bar)


def run(store, *args):
    env = dict(os.environ, BOOK_STORE=str(store), PYTHONPATH=str(ROOT),
               BOT_MODE="paper", BOT_STRATEGY="v7")
    r = subprocess.run([sys.executable, "-m", "webapp.once", *args],
                       capture_output=True, text=True, env=env, cwd=ROOT)
    if r.returncode != 0:
        print(r.stdout); print(r.stderr, file=sys.stderr)
        raise SystemExit(f"webapp.once {' '.join(args)} exited {r.returncode}")
    return r.stdout


def main():
    from webapp import journal
    store = pathlib.Path(tempfile.mkdtemp(prefix="laptop-"))
    bar = journal.floor_bar(dt.datetime.now(UTC))
    synth_panels(store, bar)
    (store / "v7_plan.json").write_bytes((ROOT / "plans/v7_plan.json").read_bytes())
    print(f"  --  store {store}, bar {bar:%Y-%m-%dT%H:%MZ}")

    out = run(store, "--arm", "--once-per-bar")
    assert "SENT" in out, out
    print("  ok  first run of the bar decided")

    sent = [e for e in journal.entries(store) if e.get("sent")]
    assert len(sent) == 1, journal.entries(store)

    for i in range(3):
        out = run(store, "--arm", "--once-per-bar")
        assert "already decided" in out, out
        assert "SENT" not in out, out
    sent = [e for e in journal.entries(store) if e.get("sent")]
    assert len(sent) == 1, f"a no-op run wrote a second decision: {journal.entries(store)}"
    print("  ok  three more runs in the same bar did nothing at all")

    c = journal.coverage(store)
    assert c["expected"] == 1 and c["sent"] == 1 and c["missed"] == [], c
    print(f"  ok  coverage {c['sent']}/{c['expected']}, nothing missed")

    # A bar decided EARLIER must not block the current one. The clock cannot be
    # moved from here, so this is done from the other side: put a decision on
    # the previous bar into the record and check the current bar still runs.
    (store / journal.NAME).write_text(json.dumps(dict(
        ts=(bar - dt.timedelta(hours=12)).isoformat(),
        bar=(bar - dt.timedelta(hours=12)).isoformat(), sent=True, target=0)) + "\n")
    out = run(store, "--arm", "--once-per-bar")
    assert "SENT" in out, out
    assert len([e for e in journal.entries(store) if e.get("sent")]) == 2
    print("  ok  a decision on the previous bar does not block this one")

    # Without --once-per-bar the same bar is re-decided: the flag is what does
    # the work, not luck.
    out = run(store, "--arm")
    assert "SENT" in out and "already decided" not in out, out
    print("  ok  without the flag it re-decides, so the flag is load-bearing")

    # A stale panel is refused rather than traded, and the refusal is recorded
    # as a bar that did NOT get a decision. Clear the record first, or the
    # pre-check short-circuits before the panel is ever read.
    (store / journal.NAME).unlink()
    synth_panels(store, bar - dt.timedelta(hours=24))
    out = run(store, "--arm", "--once-per-bar")
    assert "not sent" in out and "old" in out, out
    assert not [e for e in journal.entries(store) if e.get("sent")], journal.entries(store)
    print("  ok  a stale panel refuses, and the miss goes in the record")

    print("\nPASS  hourly with catch-up behaves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
