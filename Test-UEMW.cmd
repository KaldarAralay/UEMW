@echo off
setlocal
call "%~dp0tools\run-powershell.cmd" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\test.ps1" %*
set "UEMW_EXIT=%errorlevel%"
if not "%UEMW_EXIT%"=="0" if not defined UEMW_NO_PAUSE pause
exit /b %UEMW_EXIT%
