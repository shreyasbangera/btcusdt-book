@echo off
REM One attempt at the current 12h bar, for Windows Task Scheduler.
REM
REM Safe to run as often as you like: --once-per-bar makes every run after the
REM first of a bar exit immediately having done nothing. Put this on an HOURLY
REM trigger - a laptop cannot be relied on to be awake at 05:35 and 17:35 IST,
REM and hourly means the bar gets decided whenever the machine is next open.
REM
REM Pass --arm to actually place orders:  run.bat --arm
setlocal enabledelayedexpansion
cd /d "%~dp0.."
set "ROOT=%CD%"

REM Load .env. eol=# skips the comment lines; blank lines are skipped by for /f.
if exist "%ROOT%\.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ROOT%\.env") do set "%%a=%%b"
)

set "BOOK_STORE=%ROOT%\data\live"
set "PYTHONPATH=%ROOT%"
REM Force UTF-8. Redirected output on Windows uses the ANSI codepage with
REM strict errors, so one non-ASCII character in a sleeve label crashes the run
REM - but only when writing to the log, never when you watch it in a console.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PY=%ROOT%\.venv\Scripts\python.exe"

echo --- %DATE% %TIME% >> "%ROOT%\book.log"
"%PY%" live\fetch.py update >> "%ROOT%\book.log" 2>&1
if errorlevel 1 echo fetch failed; deciding on what we have >> "%ROOT%\book.log"
"%PY%" -m webapp.once --once-per-bar %* >> "%ROOT%\book.log" 2>&1
endlocal
