@echo off
setlocal
set "UEMW_PS_EXE=%UEMW_POWERSHELL%"
if not defined UEMW_PS_EXE if exist "%~dp0..\local\powershell.path" set /p UEMW_PS_EXE=<"%~dp0..\local\powershell.path"
if defined UEMW_PS_EXE if not exist "%UEMW_PS_EXE%" set "UEMW_PS_EXE="
rem Resolve an existing PowerShell 7 without changing the user's PATH.
for %%P in (
    "%ProgramFiles%\PowerShell\7\pwsh.exe"
    "%USERPROFILE%\AppData\Local\Programs\PowerShell\7\pwsh.exe"
    "%USERPROFILE%\AppData\Local\Microsoft\PowerShell\7\pwsh.exe"
) do if not defined UEMW_PS_EXE if exist "%%~P" set "UEMW_PS_EXE=%%~P"
if not defined UEMW_PS_EXE for /f "delims=" %%P in ('where.exe pwsh.exe 2^>nul') do if not defined UEMW_PS_EXE set "UEMW_PS_EXE=%%P"
if not defined UEMW_PS_EXE (
    echo PowerShell 7 was not found in the installed locations or on PATH.
    echo Nothing was started or installed.
    echo Install PowerShell 7: https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows
    echo For a portable installation, set UEMW_POWERSHELL to its pwsh.exe path.
    exit /b 2
)
rem Child tools can also find this same runtime; this change is local to launch.
for %%P in ("%UEMW_PS_EXE%") do set "PATH=%%~dpP;%PATH%"
"%UEMW_PS_EXE%" %*
exit /b %errorlevel%
