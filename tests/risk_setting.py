#!/usr/bin/env python3
"""The bet size, and the fact that there is exactly one of it.

    python tests/risk_setting.py

The two live failures this bot has had were both the same shape: a value that
existed in two places, changed in one. Conditional orders went to the retired
endpoint while the market path used the right one; the timestamp came from the
laptop's clock in one path and nowhere else checked it.

The risk fraction was the next one waiting to happen. `webapp/app.py` carried
`"risk": 0.08` for the dashboard and scheduler, and `webapp/once.py` carried
`default=0.08` for the scheduled task that actually trades on the laptop.
Changing the size in the UI and leaving the cron job at the old number would
have been completely silent - the log prints the size it used, and it would have
been telling the truth about the wrong number.

Both now read `config.RISK`. This pins that, and pins the environment override,
so the next person to change the size cannot change half of it.

No network, no exchange, no pandas.
"""
import sys, pathlib, os, importlib, argparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAIL = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


print("1. there is one definition, and both entry points read it")
from webapp import config  # noqa: E402

check("config exposes RISK", hasattr(config, "RISK"), f"{getattr(config, 'RISK', None)}")
check("RISK is a sane fraction, not a percentage",
      0.0 < config.RISK <= 0.25, f"{config.RISK}")

src_once = (ROOT / "webapp" / "once.py").read_text()
src_app = (ROOT / "webapp" / "app.py").read_text()
check("once.py takes its default from config, not a literal",
      "default=config.RISK" in src_once)
check("app.py seeds STATE from config, not a literal",
      '"risk": config.RISK' in src_app)
# The specific regression: a bare 0.08 next to the word risk in either file.
for tag, src in (("once.py", src_once), ("app.py", src_app)):
    bad = [ln.strip() for ln in src.splitlines()
           if "risk" in ln.lower() and ("0.08" in ln or "0.144" in ln)
           and "config.RISK" not in ln and not ln.strip().startswith("#")]
    check(f"no hard-coded risk literal left in {tag}", not bad, "; ".join(bad[:2]))

print("\n2. the scheduled task and the dashboard agree")
ap = argparse.ArgumentParser()
ap.add_argument("--risk", type=float, default=config.RISK)
cli_default = ap.parse_args([]).risk
from webapp import app as webapp_app  # noqa: E402

check("once.py's CLI default == config.RISK", cli_default == config.RISK,
      f"{cli_default}")
check("app.py's STATE['risk'] == config.RISK",
      webapp_app.STATE["risk"] == config.RISK, f"{webapp_app.STATE['risk']}")
check("they are the same number",
      cli_default == webapp_app.STATE["risk"],
      f"once {cli_default} vs app {webapp_app.STATE['risk']}")

print("\n3. the environment can still override it, for one run")
os.environ["BOT_RISK"] = "0.06"
try:
    importlib.reload(config)
    check("BOT_RISK is honoured", abs(config.RISK - 0.06) < 1e-12, f"{config.RISK}")
finally:
    del os.environ["BOT_RISK"]
    importlib.reload(config)
check("and the default comes back when it is unset",
      abs(config.RISK - 0.144) < 1e-12, f"{config.RISK}")

print("\n4. the UI cannot set a size the account cannot survive")
# app.py clamps whatever the dashboard posts. A fat finger of 2.5 instead of
# 0.25 would otherwise risk 250% of equity per bet.
check("app.py clamps the posted risk", 'min(float(s.risk), 0.25)' in src_app)

print()
if FAIL:
    print(f"FAILED: {len(FAIL)} check(s): {', '.join(FAIL)}")
    raise SystemExit(1)
print("risk setting: all checks passed")
