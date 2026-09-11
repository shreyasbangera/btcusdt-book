"""An honest record of which decisions actually happened.

WHY THIS EXISTS
---------------
On a server this file would be pointless: the machine is up, the cron fires,
every bar gets a decision. On a laptop it is the most important file in the
project.

A laptop sleeps. It is shut at night, it is in a bag on a Tuesday, it runs out
of battery. Each of those is a 12h bar with no decision on it - and the P&L that
comes out the far end is then not a test of the strategy, it is a test of your
week. The failure is not that decisions get missed. Missing some is survivable
and measured: S92 puts a 3-hour delay inside the noise. The failure is
FORGETTING that they were missed, looking at a 40% return over three months and
concluding something about V7 when half the bars were never traded.

So every run appends a line here, and every run prints what the record covers.
A gap you can see is a caveat. A gap you cannot see is a wrong conclusion.

    python -m webapp.journal            # the coverage report
    python -m webapp.journal --lines 20 # the last 20 decisions

The file is append-only JSON Lines at $BOOK_STORE/decisions.jsonl. Nothing ever
rewrites it, so a bad week stays in the record.
"""
import os, sys, json, pathlib, datetime as dt

NAME = "decisions.jsonl"
BAR_HOURS = 12          # the book decides on 12h bars: 00:00 and 12:00 UTC


def path(store):
    return pathlib.Path(store) / NAME


def _parse(ts):
    if not ts:
        return None
    t = dt.datetime.fromisoformat(str(ts))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def floor_bar(t):
    """The last 12h boundary at or before t."""
    t = t.astimezone(dt.timezone.utc)
    return t.replace(hour=0 if t.hour < BAR_HOURS else BAR_HOURS,
                     minute=0, second=0, microsecond=0)


def expected(first, last):
    """Every 12h bar from first to last inclusive."""
    out, b = [], floor_bar(first)
    last = floor_bar(last)
    while b <= last:
        out.append(b)
        b += dt.timedelta(hours=BAR_HOURS)
    return out


def record(store, plan, result):
    """Append one run.  Never raises: a journalling failure must not stop a
    decision, and a decision that happened matters more than the note of it."""
    try:
        line = dict(
            ts=plan.get("ts"), bar=plan.get("bar"), strategy=plan.get("strategy"),
            mode=plan.get("mode"), sent=bool(result.get("sent")),
            reason=result.get("reason", ""), price=plan.get("price"),
            equity=plan.get("equity"), position=plan.get("position"),
            target=plan.get("target"), order=plan.get("order"),
            bar_age_hours=plan.get("bar_age_hours"))
        p = path(store)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps(line, default=str) + "\n")
        return p
    except Exception as e:                       # noqa: BLE001 - see docstring
        print(f"  (could not write the journal: {type(e).__name__}: {e})",
              file=sys.stderr)
        return None


def entries(store):
    p = path(store)
    if not p.exists():
        return []
    out = []
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue                             # a half-written line, not a crash
    return out


def decided(store, bar):
    """Has this exact 12h bar already had a decision SENT?

    The question an hourly schedule asks before doing anything. A laptop cannot
    reliably be awake at 00:05 and 12:05, so the honest arrangement is to run
    often and act once: whenever the machine happens to be on, the bar gets its
    decision, and every later run that hour is a no-op.
    """
    if bar is None:
        return False
    bar = bar.astimezone(dt.timezone.utc)
    return any(e.get("sent") and _parse(e.get("bar")) == bar for e in entries(store))


def coverage(store, now=None):
    """Which bars have a decision on them, and which do not.

    A bar counts as DECIDED only if a run on that bar actually sent. A dry run
    is a run, not a decision: it proves the machine was awake and nothing else.
    Both are counted, separately, because they answer different questions - "was
    my laptop on?" and "did the book trade?".
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    es = entries(store)
    if not es:
        return dict(empty=True, first=None, last=None, expected=0,
                    sent=0, ran=0, missed=[], pct=0.0)

    bars = [(_parse(e.get("bar")), bool(e.get("sent"))) for e in es]
    bars = [(b, s) for b, s in bars if b is not None]
    if not bars:
        return dict(empty=True, first=None, last=None, expected=0,
                    sent=0, ran=0, missed=[], pct=0.0)

    ran = {b for b, _ in bars}
    did = {b for b, s in bars if s}
    first, last = min(ran), floor_bar(now)
    exp = expected(first, last)
    missed = [b for b in exp if b not in did]
    return dict(empty=False, first=first, last=last, expected=len(exp),
                sent=len(did & set(exp)), ran=len(ran & set(exp)),
                missed=missed, pct=100.0 * len(did & set(exp)) / max(len(exp), 1))


def summary_line(store, now=None):
    """One line, printed after every run."""
    c = coverage(store, now)
    if c["empty"]:
        return "  record: this is the first entry"
    n = len(c["missed"])
    if n == 0:
        return f"  record: {c['sent']}/{c['expected']} bars decided — complete"
    return (f"  record: {c['sent']}/{c['expected']} bars decided ({c['pct']:.0f}%)"
            f" — {n} MISSED, see `python -m webapp.journal`")


def report(store, now=None):
    c = coverage(store, now)
    if c["empty"]:
        return (f"No decisions recorded yet in {path(store)}.\n"
                f"The record starts with the first run.")
    out = [f"record      {path(store)}",
           f"from        {c['first']:%Y-%m-%d %H:%MZ}",
           f"to          {c['last']:%Y-%m-%d %H:%MZ}",
           f"bars        {c['expected']} expected, {c['ran']} ran, {c['sent']} decided",
           f"coverage    {c['pct']:.1f}%"]
    if c["missed"]:
        out += ["", f"{len(c['missed'])} bars with no decision. Any conclusion you draw "
                    f"from the P&L is about", "these bars being absent as much as about "
                    "the strategy:"]
        show = c["missed"][-40:]
        if len(c["missed"]) > len(show):
            out.append(f"  ... {len(c['missed']) - len(show)} earlier, not listed")
        out += [f"  {b:%Y-%m-%d %H:%MZ}" for b in show]
    else:
        out += ["", "Every bar in the range has a decision on it. This record can be "
                    "read as a test of the strategy."]
    return "\n".join(out)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", default=os.environ.get(
        "BOOK_STORE", os.path.expanduser("~/quant/data/live")))
    ap.add_argument("--lines", type=int, default=0,
                    help="also print the last N entries")
    a = ap.parse_args(argv)
    print(report(a.store))
    if a.lines:
        print()
        for e in entries(a.store)[-a.lines:]:
            print(f"  {e.get('ts','?')}  bar {e.get('bar','?')}  "
                  f"{'SENT' if e.get('sent') else 'no  '}  "
                  f"target {e.get('target')}  {e.get('reason','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
