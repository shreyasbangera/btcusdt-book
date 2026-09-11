"""Put the project root on sys.path once, computed from this file's location.

Every module here used to do `sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))`, which is
a path that exists on exactly one machine.  It was harmless in development and
broke nothing visibly, because inserting a non-existent path is not an error -
it just silently failed to help anywhere else.
"""
import sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import consoleio          # noqa: E402 - needs the path above
consoleio.relax()         # see consoleio.py: Windows, redirected output
