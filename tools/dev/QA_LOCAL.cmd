@echo off
setlocal DisableDelayedExpansion
set "B6_PYTHON=%~dp0.local\venv\Scripts\python.exe"
if not exist "%B6_PYTHON%" set "B6_PYTHON=python"
"%B6_PYTHON%" "%~dp0qa.py" all
set "B6_EXIT=%ERRORLEVEL%"
if not defined FATWA_NO_PAUSE pause
exit /b %B6_EXIT%
