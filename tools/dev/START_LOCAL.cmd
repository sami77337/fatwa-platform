@echo off
setlocal
cd /d "%~dp0..\.."
node "%~dp0host.mjs"
set "FATWA_RUN_EXIT=%ERRORLEVEL%"
echo.
echo Result: .local\host-result.json
pause
exit /b %FATWA_RUN_EXIT%
