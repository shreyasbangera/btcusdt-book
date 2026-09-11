# One attempt at the current 12h bar.  This is what Task Scheduler runs.
#
#   .\deploy\run.ps1          decide and print; never sends
#   .\deploy\run.ps1 -Arm     decide and, if there is an order, send it
#
# Safe to run as often as you like: --once-per-bar makes every run after the
# first of a bar exit immediately having done nothing.  That is why the
# schedule is hourly - a laptop cannot be relied on to be awake at 05:35 and
# 17:35 IST, and hourly means the bar gets decided whenever the machine is
# next open.
param([switch]$Arm)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Load .env: skip comments and blanks, split on the FIRST '=' only, and use
# SetEnvironmentVariable rather than Set-Item because an empty value (a key you
# have not filled in yet) makes Set-Item throw.
if (Test-Path "$Root\.env") {
    foreach ($line in Get-Content "$Root\.env") {
        if ($line -match '^\s*(#|$)') { continue }
        $i = $line.IndexOf('=')
        if ($i -lt 1) { continue }
        $k = $line.Substring(0, $i).Trim()
        $v = $line.Substring($i + 1).Trim()
        [Environment]::SetEnvironmentVariable($k, $v, "Process")
    }
}

$env:BOOK_STORE = Join-Path $Root "data\live"
$env:PYTHONPATH = $Root
# Force UTF-8. Redirected output on Windows is encoded with the ANSI codepage
# and strict errors, so a single non-ASCII character in a sleeve label would
# crash the run with UnicodeEncodeError - but only when writing to the log,
# never when you are watching it in a console. Exactly the kind of failure that
# shows up at 3am and not in testing.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
# ...and the other half of the same problem: PowerShell decodes a native
# command's output using [Console]::OutputEncoding, which on Windows PowerShell
# 5.1 is the OEM codepage. Without this, Python emits correct UTF-8 and
# PowerShell mangles it again on the way into the log.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$py  = Join-Path $Root ".venv\Scripts\python.exe"
$log = Join-Path $Root "book.log"
if (-not (Test-Path $py)) { throw "no virtualenv at $py - run deploy\laptop-setup.ps1 first" }

"--- {0:yyyy-MM-ddTHH:mm:ss}Z" -f (Get-Date).ToUniversalTime() | Add-Content -Encoding utf8 $log
& $py live\fetch.py update *>&1 | Add-Content -Encoding utf8 $log
if ($LASTEXITCODE -ne 0) { "fetch failed; deciding on what we have" | Add-Content -Encoding utf8 $log }

$decide = @("-m", "webapp.once", "--once-per-bar")
if ($Arm) { $decide += "--arm" }
& $py @decide *>&1 | Add-Content -Encoding utf8 $log
exit $LASTEXITCODE
