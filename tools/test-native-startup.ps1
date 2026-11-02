$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment -Development
$ProjectRoot=Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'native-startup.ps1')
& python (Join-Path $PSScriptRoot 'run_tests.py') --pattern test_steam_startup.py
if($LASTEXITCODE){throw 'Steam startup parser checks failed'}
$Context=Get-UEMWSteamStartup -ProjectRoot $ProjectRoot
if($Context.game_id -notmatch '^\d+$' -or $Context.bootstrap -ine (Join-Path $ProjectRoot 'local\bin\uemw-game-start.exe')){throw 'Resolved the wrong private bootstrap'}
Write-Output 'Six Steam startup parser checks and current shortcut/bootstrap prerequisites passed. No game or renderer was started.'
