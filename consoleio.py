#!/usr/bin/env python3
"""Never crash on a character.

THE BUG THIS PREVENTS
---------------------
On Windows, a redirected stdout is encoded with the system ANSI codepage and
`errors="strict"`. The book's own output contains four non-ASCII characters -
`·` and `×` in every sleeve label, `—` in most status lines, and `−` in a
couple of printed figures - and they do not all survive:

    cp1252   crashes on  −            (the standard Windows ANSI codepage)
    cp850    crashes on  — −
    cp437    crashes on  × — −

So `python -m webapp.once >> book.log` raises UnicodeEncodeError on Windows for
a reason that has nothing to do with trading, and - this is the nasty part -
only when the output is redirected. Watching it in a console works fine, so it
passes every test you would think to run and fails the first time it is left
alone on a schedule.

THE FIX
-------
Relax `errors` to `backslashreplace` rather than forcing UTF-8. Forcing UTF-8
onto a cp437 console turns the whole line into mojibake; this way the stream
keeps whatever encoding it has and the handful of characters it cannot carry
come out as `\\u2212`, which is ugly, readable, greppable and above all not an
exception.

`deploy/run.bat` and `deploy/run.ps1` additionally set PYTHONUTF8=1, so on the
scheduled path the log is proper UTF-8 and this never has to do anything.

No effect on Linux or macOS, where stdout is UTF-8 already.
"""
import sys


def relax():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass                 # not a TextIOWrapper (pytest, a pipe, a mock)
