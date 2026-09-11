# Running it always-on for nothing

The twice-daily bot is small. Verified on every run by `tests/no_heavy_deps.py`,
which blocks both modules outright and then makes a real decision: it needs
**pandas and numpy only**. Not numba — the heavy part, ranking 200
configurations, happens quarterly somewhere else and arrives as a committed plan
file. Not pyarrow either, as of now: `panelstore.py` stores the panels as pickle
when no parquet engine is installed, which is what unblocks an Android phone.

So the machine can be almost anything. It has to clear two bars.

## The only test that matters

Every option below lives or dies on one question, and one command answers it.
Run it **on the candidate machine**, not on your laptop:

```bash
curl -s https://fapi.binance.com/fapi/v1/time
```

* `{"serverTime":1757...}` — Binance serves this machine. It can run the bot.
* `{"code":0,"msg":"Service unavailable from a restricted location..."}` — it
  cannot, and nothing else about the machine matters. Stop there.

Nothing in this repository can work around that message. It is Binance deciding
about the IP address, before any key is involved.

The second bar is trivial by comparison: the machine must be **awake at 00:05
and 12:05 UTC** — 05:35 and 17:35 IST. It can sleep the other 23 hours.

Being late is survivable, and measured: S92 put a 30-minute delay at 67.4% CAGR
against 73.2% on time, a 3-hour delay at 65.5%, and a 6-hour delay at 51.7%.
Under three hours is inside the noise. Six hours is real damage.

---

## Option 1 — an old Android phone

**The fewest unknowns of anything here, and now unblocked.** No capacity queue,
no reclamation policy, no card, no bill, and — the part that actually decides
it — a home connection, which Binance serves if you are in India. Full steps in
[ANDROID.md](ANDROID.md).

The blocker used to be `pyarrow`, which has no Termux build. The panels are no
longer parquet unless a parquet engine is present, so that is gone:

```bash
pkg install python git      # Termux, from F-Droid
pip install pandas numpy    # and nothing else
```

A phone from 2018 with a cracked screen is a better host for this than any free
cloud tier, because the one thing you cannot buy back is an IP Binance serves.

## Option 2 — anything already switched on in your house

A desktop that stays on, a media box, a Raspberry Pi, an old laptop with the lid
shut and suspend disabled. The bot uses a few seconds of CPU twice a day. If
something in the house already runs all night, that is the cheapest answer there
is, and the setup is the same as the phone's minus Termux: clone, `pip install
pandas numpy`, add two cron lines.

On a laptop, the lid is the trap. `sudo systemctl mask sleep.target
suspend.target hibernate.target hybrid-sleep.target`, and in
`/etc/systemd/logind.conf` set `HandleLidSwitch=ignore`.

## Option 3 — Oracle Always Free, if the problem is fixable

[ORACLE.md](ORACLE.md) has the full walkthrough. Three things go wrong, and they
have different answers — it is worth knowing which one you hit:

| what you saw | what it is | what to do |
|---|---|---|
| "Out of host capacity" | ARM (A1.Flex) capacity is exhausted in Mumbai/Hyderabad, routinely for days | create `VM.Standard.E2.1.Micro` instead — AMD, smaller, and almost always available. The bot needs a fraction of it |
| Signup rejected, or the card declined | Oracle's identity check refuses a lot of Indian cards, and retrying with the same card usually fails the same way | a different card sometimes clears it. Often it does not, and this is not worth more evenings |
| It worked, then the instance vanished | Oracle reclaims Always Free compute it judges idle, and a job that runs twice a day is idle by that definition | nothing reliable. This is the reason not to build on it |

The third row is why Oracle is third on this list rather than first. Even when
it works it is a host that may quietly stop existing.

## Option 4 — Google Cloud Run, in Mumbai

The best of the no-hardware options, and the one I have **not** tested.

The mechanics do work out. Cloud Run's free tier is a spending-based discount
computed at Tier 1 rates — 240,000 vCPU-seconds and 450,000 GiB-seconds a month
— and `asia-south1` (Mumbai) is a Tier 1 region, so it is not confined to the US
regions the way Compute Engine's always-free `e2-micro` is. Cloud Scheduler
gives 3 free jobs per billing account, and one cron entry covers both daily
fires. A job that runs 3 minutes twice a day is about 11,000 vCPU-seconds a
month against 240,000.

What I cannot tell you from here is the only thing that matters: whether Binance
serves Google's Mumbai egress. Both Binance hosts are blocked from this
container, so I cannot run the test, and I am not going to assert it. If you
want this route, get a shell in `asia-south1` and run the `curl` above first.
**Ask me and I will build the container, the job and the scheduler** — it is a
Dockerfile and three `gcloud` commands, and it needs a small GCS bucket for the
panel because Cloud Run jobs keep no disk.

Two ways it costs money if you are careless: Artifact Registry's free storage is
0.5 GB and a pandas image is not far under it, and a job that hangs bills for
the whole time it hangs. Set a budget alert at ₹100 before you start.

## What does not work, and why

| | why |
|---|---|
| GitHub-hosted runners | Binance refuses them by eligibility — measured, on this repo's own workflow |
| Compute Engine always-free `e2-micro` | its free regions are `us-central1`/`us-east1`/`us-west1`, all restricted |
| Render / Railway / Koyeb free web services | they sleep when idle, so the schedule does not fire |
| Vercel / Netlify Hobby cron | once-a-day accuracy, a 60s function ceiling, and no disk |
| AWS free tier | twelve months, then it bills |
| PythonAnywhere free | outbound requests go through an allowlist proxy, and Binance is not on it |
| Cloudflare Workers | the Python runtime cannot carry pandas, and CPU time is capped far below this |
| Hugging Face Spaces free | US hosts, and free Spaces sleep after 48h |

The pattern is not that free tiers are stingy. It is that free tiers are
*American*, and Binance does not serve there. This is why a phone beats all of
them.

## If none of these are available — your own laptop

Not a fallback to be embarrassed about, and no longer a manual one. See
[LAPTOP.md](LAPTOP.md).

The arrangement is an **hourly** schedule with `--once-per-bar`, rather than a
twice-daily one: the first run of each 12h bar decides and the rest are no-ops,
so a laptop that was shut at 05:35 catches the bar whenever it next opens. That
removes both the sleeping-laptop problem and every time zone bug along with it.

It still misses bars, and the point is that you can see which. Every run appends
to `decisions.jsonl`, and `python -m webapp.journal` reports how many 12h bars
actually got a decision and lists the ones that did not:

```
bars        29 expected, 24 ran, 22 decided
coverage    75.9%
```

A partial record honestly labelled is worth something. A partial record you
later mistake for a complete one is worth less than nothing, because you will
conclude something about the strategy from a sample that was really about your
week.
