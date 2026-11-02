@echo off
setlocal
set "UEMW_TEXTURE_UPGRADES=0"
call "%~dp0..\..\Start-UEMW.cmd"
exit /b %errorlevel%
