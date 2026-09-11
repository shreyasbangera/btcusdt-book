#!/usr/bin/env python3
"""The coverage arithmetic in webapp/journal.py.

    python tests/journal_coverage.py

The numbers this file checks are the ones a laptop user will quote back at
themselves months from now ("it made 40% over three months"), so being wrong
here is worse than being absent.
"""
import sys, os, json, tempfile, pathlib, datetime as dt

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from webapp import journal

UTC = dt.timezone.utc


def bar(day, hour):
    return dt.datetime(2026, 9, day, hour, tzinfo=UTC)


def write(store, rows):
    """rows: (bar, sent) or (bar, sent, reason)."""
    with open(journal.path(store), "w") as f:
        for row in rows:
            b, sent = row[0], row[1]
            reason = row[2] if len(row) > 2 else ""
            f.write(json.dumps(dict(ts=b.isoformat(), bar=b.isoformat(),
                                    sent=sent, reason=reason, target=0)) + "\n")


def main():
    store = pathlib.Path(tempfile.mkdtemp(prefix="journal-"))

    # floor_bar: a decision at any time belongs to the 12h bar that opened it
    assert journal.floor_bar(dt.datetime(2026, 9, 11, 0, 5, tzinfo=UTC)) == bar(11, 0)
    assert journal.floor_bar(dt.datetime(2026, 9, 11, 11, 59, tzinfo=UTC)) == bar(11, 0)
    assert journal.floor_bar(dt.datetime(2026, 9, 11, 12, 0, tzinfo=UTC)) == bar(11, 12)
    assert journal.floor_bar(dt.datetime(2026, 9, 11, 23, 59, tzinfo=UTC)) == bar(11, 12)
    print("  ok  floor_bar puts a run on the right bar")

    # decision_bar is floor_bar minus one bar: at 20:03 the bar named 12:00 is
    # still being built, so the newest bar a run can decide is 00:00. Being one
    # bar out here is how the bot came to trade on half-formed data.
    assert journal.decision_bar(dt.datetime(2026, 9, 11, 20, 3, tzinfo=UTC)) == bar(11, 0)
    assert journal.decision_bar(dt.datetime(2026, 9, 11, 0, 5, tzinfo=UTC)) == bar(10, 12)
    assert journal.decision_bar(dt.datetime(2026, 9, 11, 12, 5, tzinfo=UTC)) == bar(11, 0)
    print("  ok  decision_bar is the last CLOSED bar, not the one being built")

    # expected: inclusive of both ends, two a day
    exp = journal.expected(bar(1, 0), bar(3, 12))
    assert len(exp) == 6, len(exp)
    assert exp[0] == bar(1, 0) and exp[-1] == bar(3, 12)
    print(f"  ok  expected() spans {len(exp)} bars over 3 days")

    # a complete record
    write(store, [(bar(1, 0), True), (bar(1, 12), True), (bar(2, 0), True)])
    c = journal.coverage(store, now=dt.datetime(2026, 9, 2, 18, tzinfo=UTC))
    assert c["expected"] == 3 and c["sent"] == 3 and c["missed"] == [], c
    assert c["pct"] == 100.0
    print("  ok  a complete record reads 100% with nothing missed")

    # a laptop that was shut for a day and a half
    write(store, [(bar(1, 0), True), (bar(1, 12), True),
                  (bar(3, 12), True), (bar(4, 0), True)])
    c = journal.coverage(store, now=dt.datetime(2026, 9, 4, 18, tzinfo=UTC))
    assert c["expected"] == 7, c["expected"]
    assert c["sent"] == 4, c["sent"]
    assert c["missed"] == [bar(2, 0), bar(2, 12), bar(3, 0)], c["missed"]
    assert abs(c["pct"] - 400/7) < 1e-9, c["pct"]
    print(f"  ok  3 shut-laptop bars found: {[f'{b:%d %HZ}' for b in c['missed']]}")

    # bars that RAN but were refused are not decisions. A dry run proves the
    # laptop was awake; it does not put a trade on the bar.
    write(store, [(bar(1, 0), True), (bar(1, 12), False), (bar(2, 0), True)])
    c = journal.coverage(store, now=dt.datetime(2026, 9, 2, 18, tzinfo=UTC))
    assert c["ran"] == 3 and c["sent"] == 2, (c["ran"], c["sent"])
    assert c["missed"] == [bar(1, 12)], c["missed"]
    print("  ok  a run that did not send counts as ran, not as decided")

    # the tail of the range comes from NOW, not from the last entry: a laptop
    # that stopped a week ago must not report 100%
    write(store, [(bar(1, 0), True), (bar(1, 12), True)])
    c = journal.coverage(store, now=dt.datetime(2026, 9, 8, 6, tzinfo=UTC))
    assert c["expected"] == 14, c["expected"]
    assert c["sent"] == 2 and len(c["missed"]) == 12, (c["sent"], len(c["missed"]))
    print("  ok  a bot that stopped a week ago reports 2/14, not 2/2")

    # empty and malformed files are reports, not crashes
    (store / journal.NAME).write_text("")
    assert journal.coverage(store)["empty"]
    (store / journal.NAME).write_text('{"bar": "2026-09-01T00:00:00+00:00", "sent": true}\n'
                                      '{ half a line\n')
    c = journal.coverage(store, now=bar(2, 0))
    assert c["expected"] == 2 and c["sent"] == 1, c
    print("  ok  an empty or half-written journal reports rather than crashes")

    # the line every run prints
    write(store, [(bar(1, 0), True)])
    line = journal.summary_line(store, now=dt.datetime(2026, 9, 3, 6, tzinfo=UTC))
    assert "MISSED" in line, line
    print(f"  ok  summary line says so: {line.strip()}")

    # A bar you deliberately did not trade is not a bar you missed. Every run
    # before arming says "not armed", and counting those as misses made a
    # correct first day print "0/1 bars decided (0%) - 1 MISSED".
    write(store, [(bar(1, 0), False, "not armed"),
                  (bar(1, 12), False, "not armed")])
    c = journal.coverage(store, now=dt.datetime(2026, 9, 2, 0, tzinfo=UTC))
    assert c["missed"] == [], c["missed"]
    assert c["dry"] == [bar(1, 0), bar(1, 12)], c["dry"]
    line = journal.summary_line(store, now=dt.datetime(2026, 9, 2, 0, tzinfo=UTC))
    assert "MISSED" not in line and "dry run" in line, line
    print(f"  ok  unarmed runs are dry, not missed: {line.strip()}")

    # But a bar with no entry at all, in a range where you WERE armed, still is.
    write(store, [(bar(1, 0), False, "not armed"),
                  (bar(1, 12), True),
                  (bar(2, 12), True)])
    c = journal.coverage(store, now=dt.datetime(2026, 9, 3, 0, tzinfo=UTC))
    assert c["dry"] == [bar(1, 0)], c["dry"]
    assert c["missed"] == [bar(2, 0)], c["missed"]
    assert c["sent"] == 2 and abs(c["pct"] - 200/3) < 1e-9, (c["sent"], c["pct"])
    print("  ok  coverage is measured over the bars you meant to trade (2/3)")

    # A refusal that is NOT "not armed" - stale data - stays a miss.
    write(store, [(bar(1, 0), True),
                  (bar(1, 12), False, "data is 20h old (limit 13h)")])
    c = journal.coverage(store, now=dt.datetime(2026, 9, 2, 0, tzinfo=UTC))
    assert c["missed"] == [bar(1, 12)], c["missed"]
    assert c["dry"] == [], c["dry"]
    print("  ok  a stale-data refusal is still a miss, not a dry run")

    print("\nPASS  journal coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
