@echo off
rem One command for the whole report on Windows:  run_report 2026Q3            (whole country)
rem                                                run_report 2026Q3 toshkent   (Tashkent)
rem Extra options go at the end, e.g.:             run_report 2026Q3 respublika --no-ai
rem Needs ANTHROPIC_API_KEY set (setx ANTHROPIC_API_KEY "..." once, then open a new window).
setlocal
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
if "%~1"=="" (
  echo Usage: run_report PERIOD [respublika^|toshkent] [options]   e.g. run_report 2026Q3
  exit /b 2
)
set SCOPE=%~2
if "%SCOPE%"=="" set SCOPE=respublika
python -m uyjoy report --period %1 --scope %SCOPE% %3 %4 %5
exit /b %ERRORLEVEL%
