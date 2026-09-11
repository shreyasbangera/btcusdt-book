#!/usr/bin/env python3
"""The book's output survives a Windows codepage.

    python tests/windows_encoding.py

Reproduces the failure on Linux by opening a file with the same encodings a
redirected stdout gets on Windows, because that is the only place the bug
exists: a Windows CONSOLE handles Unicode fine, and `>> book.log` does not.
Which is why it would have passed every manual test and failed the first night
it ran unattended on a schedule.
"""
import sys, io, pathlib, subprocess, tempfile, datetime as dt

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

# Every non-ASCII character the bot prints: sleeve labels, status lines, figures.
SAMPLE = "#1 exp 3.0 · 3.0ATR ×2.0R · 14d — not sent — backtest −12.3%"
CODEPAGES = ["cp1252", "cp850", "cp437"]


def main():
    import consoleio

    # 1. The bug is real: strict encoding raises on the codepages Windows uses.
    broke = []
    for cp in CODEPAGES:
        try:
            SAMPLE.encode(cp)
        except UnicodeEncodeError:
            broke.append(cp)
    assert broke == CODEPAGES, f"expected all of {CODEPAGES} to fail, got {broke}"
    print(f"  ok  strict encoding really does fail on {', '.join(broke)}")

    # 2. consoleio.relax() makes the same write succeed on all of them.
    for cp in CODEPAGES:
        buf = io.TextIOWrapper(io.BytesIO(), encoding=cp, errors="strict",
                               write_through=True)
        real_out, sys.stdout = sys.stdout, buf
        try:
            consoleio.relax()
            print(SAMPLE)                     # would raise without relax()
            buf.flush()
            written = buf.buffer.getvalue().decode(cp)
        finally:
            sys.stdout = real_out
        assert "not sent" in written and "exp 3.0" in written, written
        assert "\\u" in written or written.strip() == SAMPLE  # escaped, not lost
        print(f"  ok  {cp:8} writes without raising: ...{written.strip()[-34:]}")

    # 3. End to end: a real decision, with stdout redirected to a cp1252 file,
    #    in a subprocess - which is exactly what Task Scheduler does.
    import synth
    from webapp import journal
    store = pathlib.Path(tempfile.mkdtemp(prefix="wincp-"))
    bar = journal.decision_bar(dt.datetime.now(dt.timezone.utc))
    synth.write(store, bar)
    (store / "v7_plan.json").write_bytes((ROOT / "plans/v7_plan.json").read_bytes())

    log = store / "book.log"
    import os
    env = dict(os.environ, BOOK_STORE=str(store), PYTHONPATH=str(ROOT),
               BOT_MODE="paper", BOT_STRATEGY="v7",
               PYTHONIOENCODING="cp1252")     # what Windows does to a redirect
    env.pop("PYTHONUTF8", None)
    with open(log, "wb") as f:
        r = subprocess.run([sys.executable, "-m", "webapp.once", "--arm"],
                           stdout=f, stderr=subprocess.STDOUT, env=env, cwd=ROOT)
    text = log.read_bytes().decode("cp1252")
    if r.returncode != 0:
        print(text)
        raise SystemExit(f"the run exited {r.returncode} under cp1252")
    assert "SENT" in text, text
    assert "exp" in text, text
    print(f"  ok  a real decision logs cleanly under cp1252 ({len(text)} bytes, SENT)")

    print("\nPASS  windows encoding")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
