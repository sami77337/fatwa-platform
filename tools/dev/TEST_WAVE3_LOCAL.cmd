@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0..\.."
if errorlevel 1 exit /b 2
if defined FATWA_PYTHON goto selected_python
if exist ".venv\Scripts\python.exe" (
  set "FATWA_PYTHON=%CD%\.venv\Scripts\python.exe"
) else (
  set "FATWA_PYTHON=python"
)
:selected_python
"%FATWA_PYTHON%" tools\dev\wave3_qa.py %*
set "FATWA_RUN_EXIT=%ERRORLEVEL%"
popd
echo.
echo Wave3 exit code: %FATWA_RUN_EXIT%
if not defined FATWA_NO_PAUSE pause
exit /b %FATWA_RUN_EXIT%
