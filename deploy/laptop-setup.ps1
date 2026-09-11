<#
.SYNOPSIS
    Set up the BTCUSDT book on a Windows laptop, end to end.

.DESCRIPTION
    Checks that Binance serves this machine, installs Python dependencies into
    a virtualenv, runs the tests, seeds 36 months of market data, and registers
    an HOURLY scheduled task.

    WHY HOURLY AND NOT TWICE A DAY. The book decides at 00:05 and 12:05 UTC -
    05:35 and 17:35 IST. A server is awake then; a laptop is shut, or in a bag,
    or flat. So the task runs every hour and each run carries --once-per-bar:
    the first run of a 12h bar decides, and every other run that day exits
    immediately having done nothing. A laptop shut at 05:35 catches that bar
    whenever it next opens, and there is no UTC arithmetic in the trigger to
    get wrong - hourly is hourly in every time zone.

    The task is registered as a DRY RUN. Re-run with -Arm when you are ready
    for it to actually place orders.

.EXAMPLE
    .\deploy\laptop-setup.ps1
    .\deploy\laptop-setup.ps1 -Arm
#>
param(
    [switch]$Arm,
    [string]$TaskName = "BTCUSDT book"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Say($msg) { Write-Host "`n$msg" -ForegroundColor Cyan }
function Die($msg) { Write-Host "`n$msg" -ForegroundColor Red; exit 1 }

# --------------------------------------------------------------------------
Say "1. Does Binance serve this laptop?"
# curl.exe, not curl: in PowerShell `curl` is an alias for Invoke-WebRequest,
# which behaves differently and would quietly make this check meaningless.
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    Die "    curl.exe not found. It ships with Windows 10 1803 and later; on an older Windows, update or install curl."
}
$resp = (& curl.exe -s --max-time 20 "https://fapi.binance.com/fapi/v1/time") -join ""
if ($resp -match "serverTime") {
    Write-Host "    yes - $resp"
} elseif ($resp -match "restricted|Eligibility") {
    Die @"
    NO. Binance refuses this connection:
    $resp

    This is decided by your IP address, before any key is involved, and nothing
    in this repository can work around it. If you are on a VPN, turn it off and
    try again - a VPN exit in a restricted country produces exactly this.
"@
} elseif (-not $resp) {
    Die "    no answer at all - is this laptop online?"
} else {
    Die "    unexpected answer: $resp"
}

# --------------------------------------------------------------------------
Say "2. Python"
$PyExe = $null
$PyPre = @()
if (Get-Command py -ErrorAction SilentlyContinue)          { $PyExe = "py"; $PyPre = @("-3") }
elseif (Get-Command python -ErrorAction SilentlyContinue)  { $PyExe = "python" }
else { Die "    No Python found. Install 3.11+ from python.org and TICK 'Add python.exe to PATH'." }

$ver = & $PyExe @PyPre -c "import sys;print('%d.%d' % sys.version_info[:2])"
if ($LASTEXITCODE -ne 0) { Die "    could not run Python" }
if ([version]$ver -lt [version]"3.10") { Die "    Python 3.10+ required; found $ver" }
Write-Host "    Python $ver"

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    & $PyExe @PyPre -m venv "$Root\.venv"
    if ($LASTEXITCODE -ne 0) { Die "    venv creation failed" }
}
& $VenvPy -m pip install --quiet --upgrade pip
& $VenvPy -m pip install --quiet -r "$Root\requirements.txt"
if ($LASTEXITCODE -ne 0) { Die "    pip install failed" }
Write-Host ("    " + (& $VenvPy -c "import pandas,numpy;print('pandas',pandas.__version__,'numpy',numpy.__version__)"))

# --------------------------------------------------------------------------
Say "3. The tests, before anything touches an exchange"
$env:PYTHONPATH = $Root
& $VenvPy "$Root\tests\all.py" | Out-Null
if ($LASTEXITCODE -ne 0) {
    & $VenvPy "$Root\tests\all.py"
    Die "    TESTS FAILED - stopping. Send me the output above."
}
Write-Host "    all passed"

# --------------------------------------------------------------------------
Say "4. Keys"
$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) {
@"
# Binance USD-M futures TESTNET keys, from testnet.binancefuture.com.
# NEVER put a real-money key in here.
BINANCE_TEST_KEY=
BINANCE_TEST_SECRET=
BOT_MODE=test
BOT_STRATEGY=v7
BOT_EQUITY=10000
BOT_RISK=0.08
"@ | Set-Content -Path $EnvFile -Encoding ASCII
    Write-Host "    wrote .env - put your testnet keys in it"
} else {
    Write-Host "    .env already exists, leaving it alone"
}

# --------------------------------------------------------------------------
Say "5. Market data"
$Store = Join-Path $Root "data\live"
New-Item -ItemType Directory -Force -Path $Store | Out-Null
$env:BOOK_STORE = $Store
$env:PYTHONUTF8 = "1"
if (-not (Test-Path "$Store\v7_plan.json")) {
    Copy-Item "$Root\plans\v7_plan.json" "$Store\v7_plan.json"
}
$state = & $VenvPy "$Root\panelstore.py"
if ($state -match "rows, to") {
    Write-Host "    panels present, topping up"
    & $VenvPy "$Root\live\fetch.py" update
} else {
    Write-Host "    no panels yet - seeding. ~650 archive downloads, 10-20 minutes."
    & $VenvPy "$Root\live\fetch.py" seed --months 36
    if ($LASTEXITCODE -ne 0) { Die "    the seed failed - send me the output above" }
}
& $VenvPy "$Root\panelstore.py"

# --------------------------------------------------------------------------
Say "6. Schedule, hourly"
$RunPs1 = Join-Path $Root "deploy\run.ps1"
$psArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunPs1`""
if ($Arm) { $psArgs += " -Arm" }

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $psArgs -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
             -RepetitionInterval (New-TimeSpan -Hours 1) `
             -RepetitionDuration (New-TimeSpan -Days 3650)
# Every one of these matters on a laptop:
#   AllowStartIfOnBatteries / DontStopIfGoingOnBatteries - the defaults are the
#     opposite, and they will silently stop the bot the moment you unplug. This
#     is the single most common way a Windows schedule dies without a trace.
#   StartWhenAvailable - run a missed occurrence once the machine is back.
#   IgnoreNew - never let two decisions overlap.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
              -DontStopIfGoingOnBatteries -StartWhenAvailable `
              -MultipleInstances IgnoreNew `
              -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Force `
        -Description "Twice-daily BTCUSDT book, run hourly with --once-per-bar." | Out-Null
} catch {
    Die @"
    Could not register the scheduled task:
      $($_.Exception.Message)

    This usually means it needs elevation. Close this window, right-click
    Windows PowerShell, 'Run as administrator', then:
        cd '$Root'
        .\deploy\laptop-setup.ps1$(if ($Arm) { ' -Arm' })

    Everything before this step is already done, so the re-run will be quick.
"@
}

$mode = if ($Arm) { "ARMED - this will place orders on the testnet" } else { "dry run - it will not place anything" }
Write-Host "    registered '$TaskName', hourly, $mode"

# --------------------------------------------------------------------------
Write-Host @"

Done. What is left:

  1. Put your testnet keys in   $EnvFile
     testnet.binancefuture.com -> log in with Google or GitHub -> scroll to the
     API Key panel at the bottom. Testnet only. Never a real key.

  2. Watch one decision by hand:
         .\deploy\run.ps1
         Get-Content .\book.log -Tail 30

     Run it twice. The second time it should say 'already decided - nothing to
     do'. That is the guard that makes an hourly schedule safe.

  3. When you trust it, arm it:
         .\deploy\laptop-setup.ps1 -Arm

  4. Read the record weekly. This is the part that matters on a laptop:
         .\.venv\Scripts\python.exe -m webapp.journal

     It says how many 12h bars actually got a decision and lists the ones that
     did not. A laptop WILL miss bars. Missing some is survivable; not knowing
     which ones is what turns a result into a wrong conclusion.

  To check on the task:   Get-ScheduledTask -TaskName '$TaskName'
  To stop it:             Unregister-ScheduledTask -TaskName '$TaskName'
"@ -ForegroundColor Green
