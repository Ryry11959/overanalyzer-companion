@echo off
rem ---------------------------------------------------------------------------
rem OverAnalyzer capture app -- DEBUG launcher. Runs with a visible console
rem (python.exe) and keeps the window open so any startup error / traceback
rem stays on screen. Use "OverAnalyzer.cmd" for normal (silent) launching.
rem ---------------------------------------------------------------------------
cd /d "%~dp0"
echo Launching OverAnalyzer capture app (debug)...
echo The app window should open. Close it (or Ctrl+C here) to stop.
echo -------------------------------------------------------------------
"%~dp0..\.venv\Scripts\python.exe" -m overanalyzer_agent
echo -------------------------------------------------------------------
echo App exited with code %errorlevel%.
pause
