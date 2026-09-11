#!/usr/bin/env python3
"""Run every test.  No pytest, on purpose: the whole argument of this project
is that the bot needs pandas and numpy and nothing else, and a test runner that
needs a third package undercuts it.

    python tests/all.py
"""
import sys, subprocess, pathlib

HERE = pathlib.Path(__file__).resolve().parent
SKIP = {"all.py", "synth.py"}          # the runner, and a helper with no tests


def main():
    files = sorted(p for p in HERE.glob("*.py") if p.name not in SKIP)
    failed = []
    for f in files:
        print(f"\n=== {f.name} " + "=" * (60 - len(f.name)))
        if subprocess.run([sys.executable, str(f)]).returncode:
            failed.append(f.name)
    print("\n" + "=" * 68)
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(f"all {len(files)} test files passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
