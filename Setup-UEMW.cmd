@echo off
setlocal
call "%~dp0tools\run-powershell.cmd" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" %*
set "UEMW_EXIT=%errorlevel%"
if not defined UEMW_NO_PAUSE pause
exit /b %UEMW_EXIT%
