<#
.SYNOPSIS
    Set up the BTCUSDT book on a Windows laptop, end to end.

.DESCRIPTION
    Checks that Binance serves this machine, installs Python dependencies into
    a virtualenv, runs the tests, seeds 36 months of market data, and registers
    two scheduled tasks.

    WHY HOURLY AND NOT TWICE A DAY. The book decides at 00:05 and 12:05 UTC -
    05:35 and 17:35 IST. A server is awake then; a laptop is shut, or in a bag,
    or flat. So the task runs every hour and each run carries --once-per-bar:
    the first run of a 12h bar decides, and every other run that day exits
    immediately having done nothing. A laptop shut at 05:35 catches that bar
    whenever it next opens, and there is no UTC arithmetic in the trigger to
    get wrong - hourly is hourly in every time zone.

    WHY A SECOND TASK. The hourly one only helps while the machine is awake.
    S93 measured the alternative: missing 20% of bars in three-day blocks costs
    17.9 points of CAGR, against 7.7 for being three hours late on every single
    one. So missing days matters more than twice as much as being slow, and the
    fix is a task that can WAKE a sleeping laptop.

    It fires twice a day rather than hourly, five minutes after each bar closes.
    Hourly wake-ups all night are how you end up disabling your own bot, and the
    bar only changes twice a day - two wakes cover everything the other
    twenty-two could.

    This only works from SLEEP or hibernate. Nothing can wake a machine that is
    shut down. Use -NoWake to skip it.

    The tasks are registered as a DRY RUN. Re-run with -Arm when you are ready
    for them to actually place orders.

.EXAMPLE
    .\deploy\laptop-setup.ps1
    .\deploy\laptop-setup.ps1 -Arm
    .\deploy\laptop-setup.ps1 -Arm -NoWake
#>
param(
    [switch]$Arm,
    [switch]$NoWake,
    [string]$TaskName = "BTCUSDT book",
    [string]$WakeTaskName = "BTCUSDT book (wake)"
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
Say "6. Schedule"
$RunPs1 = Join-Path $Root "deploy\run.ps1"
$psArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunPs1`""
if ($Arm) { $psArgs += " -Arm" }
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $psArgs -WorkingDirectory $Root

# Every one of these matters on a laptop:
#   AllowStartIfOnBatteries / DontStopIfGoingOnBatteries - the defaults are the
#     opposite, and they will silently stop the bot the moment you unplug. This
#     is the single most common way a Windows schedule dies without a trace.
#   StartWhenAvailable - run a missed occurrence once the machine is back.
#   IgnoreNew - never let two decisions overlap.
$common = @{
    AllowStartIfOnBatteries    = $true
    DontStopIfGoingOnBatteries = $true
    StartWhenAvailable         = $true
    MultipleInstances          = "IgnoreNew"
    ExecutionTimeLimit         = (New-TimeSpan -Minutes 30)
}

function RegisterTask([string]$name, $trigger, $settings, [string]$desc) {
    try {
        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
            -Settings $settings -Force -Description $desc | Out-Null
        return $true
    } catch {
        Die @"
    Could not register the scheduled task '$name':
      $($_.Exception.Message)

    This usually means it needs elevation. Close this window, right-click
    Windows PowerShell, 'Run as administrator', then:
        cd '$Root'
        .\deploy\laptop-setup.ps1$(if ($Arm) { ' -Arm' })$(if ($NoWake) { ' -NoWake' })

    Everything before this step is already done, so the re-run will be quick.
"@
    }
}

# (a) THE HOURLY TASK - catch-up while the machine is awake. Deliberately does
# NOT wake anything: an hourly wake-up all night is how you end up disabling
# your own bot, and the bar only changes twice a day.
RegisterTask $TaskName `
    (New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
       -RepetitionInterval (New-TimeSpan -Hours 1) `
       -RepetitionDuration (New-TimeSpan -Days 3650)) `
    (New-ScheduledTaskSettingsSet @common) `
    "BTCUSDT book: hourly catch-up, --once-per-bar." | Out-Null
Write-Host "    '$TaskName' - hourly, no wake"

# (b) THE WAKE TASK - twice a day, five minutes after each 12h bar closes, and
# allowed to wake a sleeping machine. Two wakes a day rather than twenty-four,
# at the only two moments that can possibly matter.
#
# Triggers fire on LOCAL time, so the two UTC bar closes are converted here at
# setup. Moving the machine to another time zone silently shifts them; re-run
# this script after travelling. (India has no DST, so they are stable here.)
if (-not $NoWake) {
    $utcMid = (Get-Date).ToUniversalTime().Date
    $t1 = [System.TimeZoneInfo]::ConvertTimeFromUtc($utcMid.AddMinutes(5), [System.TimeZoneInfo]::Local)
    $t2 = [System.TimeZoneInfo]::ConvertTimeFromUtc($utcMid.AddHours(12).AddMinutes(5), [System.TimeZoneInfo]::Local)
    $wakeSettings = New-ScheduledTaskSettingsSet @common -WakeToRun
    RegisterTask $WakeTaskName `
        @((New-ScheduledTaskTrigger -Daily -At $t1),
          (New-ScheduledTaskTrigger -Daily -At $t2)) `
        $wakeSettings `
        "BTCUSDT book: wake the machine just after each 12h bar closes." | Out-Null
    Write-Host ("    '$WakeTaskName' - daily at {0:HH:mm} and {1:HH:mm} local, WAKES the machine" -f $t1, $t2)

    # Windows ignores WakeToRun unless wake timers are permitted by the power
    # plan, and they are commonly off by default. Set it for AC only: waking on
    # battery is a good way to find the laptop flat in the morning.
    #
    # ErrorActionPreference is relaxed around these: powercfg writes "Access
    # denied" to stderr when it wants elevation, and under Stop that becomes a
    # terminating NativeCommandError which would kill the script AFTER the tasks
    # were registered - leaving the setup half done and the reason invisible.
    # The same trap that ate a Python traceback in run.ps1.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $okA = $okB = $false
    try {
        & powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 2>&1 | Out-Null
        $okA = ($LASTEXITCODE -eq 0)
        & powercfg /setactive SCHEME_CURRENT 2>&1 | Out-Null
        $okB = ($LASTEXITCODE -eq 0)
    } catch { }
    $sleepStates = ""
    try { $sleepStates = ((& powercfg /a) 2>&1 | Out-String) } catch { }
    $ErrorActionPreference = $prev

    if ($okA -and $okB) {
        Write-Host "    wake timers enabled on AC power"
    } else {
        Write-Host "    could not set wake timers - do it by hand:" -ForegroundColor Yellow
        Write-Host "      Control Panel > Power Options > Change plan settings >" -ForegroundColor Yellow
        Write-Host "      Change advanced power settings > Sleep > Allow wake timers > Enable" -ForegroundColor Yellow
    }

    # Modern Standby laptops (S0 low-power idle) often suppress wake timers by
    # OEM policy regardless of the Windows setting. Worth knowing up front
    # rather than deducing it later from a journal full of missed bars.
    if ($sleepStates -match "S0 Low Power Idle") {
        Write-Host "    NOTE: this machine uses Modern Standby (S0). Wake timers are" -ForegroundColor Yellow
        Write-Host "      often suppressed there whatever Windows says. If the journal" -ForegroundColor Yellow
        Write-Host "      shows missed bars on days you were away, that is why." -ForegroundColor Yellow
    }
    Write-Host "    SLEEP the laptop rather than shutting it down, and leave it plugged"
    Write-Host "    in. Nothing can wake a machine that is powered off."
} else {
    Unregister-ScheduledTask -TaskName $WakeTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "    no wake task (-NoWake)"
}

$mode = if ($Arm) { "ARMED - this will place orders on the testnet" } else { "dry run - it will not place anything" }
Write-Host "    $mode"

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

  5. SLEEP the laptop rather than shutting it down, and leave it plugged in
     when you are away. The wake task can rouse a sleeping machine twice a day;
     nothing can rouse one that is powered off.

  To check on them:   Get-ScheduledTask -TaskName 'BTCUSDT book*' | Get-ScheduledTaskInfo
  To stop everything: Get-ScheduledTask -TaskName 'BTCUSDT book*' | Unregister-ScheduledTask
"@ -ForegroundColor Green
