@echo off
call "%~dp0..\..\tools\run-powershell.cmd" -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\tools\start-session.ps1" -Overlay %*
if errorlevel 1 pause
