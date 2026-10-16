@echo off
setlocal DisableDelayedExpansion
where node >nul 2>nul
if errorlevel 1 goto missing_node
node "%~dp0host.mjs" test-db
set "FATWA_RUN_EXIT=%ERRORLEVEL%"
:result
echo.
echo Report: tools\dev\.local\a6-test-db-result.json
if not defined FATWA_NO_PAUSE pause
exit /b %FATWA_RUN_EXIT%
:missing_node
echo Node.js is unavailable. Install or enable the existing local Node runtime, then retry.
if not defined FATWA_NO_PAUSE pause
exit /b 2
