param([string]$GameRoot,[string]$EngineRoot,[string]$SteamExe)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$ProjectRoot=Get-UEMWRoot
$GameRoot=Resolve-UEMWGameRoot -GameRoot $GameRoot -SteamExe $SteamExe
$SteamExe=Get-UEMWSteamExe -SteamExe $SteamExe
$Python=Get-UEMWPython
& $Python (Join-Path $PSScriptRoot 'prepare_game.py') --root $ProjectRoot --game $GameRoot --steam $SteamExe
if($LASTEXITCODE){throw 'Private game preparation failed; see the error above.'}
& (Join-Path $PSScriptRoot 'setup-graphics.ps1')
Write-Output 'Private game prepared. Installed game and existing saves were not modified.'
