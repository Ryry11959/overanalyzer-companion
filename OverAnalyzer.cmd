@echo off
rem ---------------------------------------------------------------------------
rem OverAnalyzer capture app -- double-click to launch the app window.
rem
rem Uses the repo venv's *windowed* Python (pythonw.exe) so there's no console
rem window; the app's own window is the UI. Close the window (or click Quit) to
rem stop it. If nothing appears, run "OverAnalyzer (debug).cmd" to see any error.
rem ---------------------------------------------------------------------------
cd /d "%~dp0"
start "" "%~dp0..\.venv\Scripts\pythonw.exe" -m overanalyzer_agent
