"""Where this checkout keeps its data and results.

Every research script used to hardcode /home/user/quant, which is a path that
exists on exactly one machine.  These resolve from this file's location instead,
so a clone works anywhere, and both can be overridden with BOOK_DATA / BOOK_RESULTS
for a machine that keeps its cache on another disk.
"""
import os, pathlib

ROOT = pathlib.Path(__file__).resolve().parent
DATA = pathlib.Path(os.environ.get("BOOK_DATA", ROOT / "data"))
RESULTS = pathlib.Path(os.environ.get("BOOK_RESULTS", ROOT / "results"))
DATA.mkdir(parents=True, exist_ok=True)
RESULTS.mkdir(parents=True, exist_ok=True)
