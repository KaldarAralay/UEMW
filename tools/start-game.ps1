param([switch]$CaptureCrashes)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$PrivateGame=Join-Path $ProjectRoot 'local\Morrowind'
if((Get-FileHash -LiteralPath (Join-Path $PrivateGame 'Morrowind.exe') -Algorithm SHA256).Hash -ne 'EAC72E1B3524EE0012D080D3C2E2E00E401464E41EE54F9AFD6AAAADF2C221F5'){throw 'Unsupported private executable; launch refused.'}
if(Get-Process -Name Morrowind -ErrorAction SilentlyContinue){throw 'A Morrowind process is already running; use the existing private test session or close it first.'}
$AppIdFile=Join-Path $PrivateGame 'steam_appid.txt'
if(!(Test-Path -LiteralPath $AppIdFile) -or (Get-Content -LiteralPath $AppIdFile -Raw).Trim() -ne '22320'){throw 'Private Steam app-ID context is missing or invalid. No game was started; run tools/prepare.ps1 with the game closed.'}
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot 'local\bridge') | Out-Null
$PidFile=Join-Path $ProjectRoot 'local\bridge\game.pid'
if($CaptureCrashes){
    $Helper=Join-Path $ProjectRoot 'local\bin\crash-watchdog.exe'
    if(!(Test-Path -LiteralPath $Helper)){throw 'Build the optional x86 helper first: .\tools\build-diagnostics.ps1'}
}
# Steam initialization must run normally. Launching this build under DEBUG_PROCESS
# produced a Steam load error. The optional helper waits for initialized controllers
# before attaching; no DRM/executable bytes or registry settings are changed.
. (Join-Path $PSScriptRoot 'native-startup.ps1')
$Process=Start-UEMWSteamPrivateGame -ProjectRoot $ProjectRoot
$GameProcessId=$Process.Id
Set-Content -LiteralPath $PidFile -Value $GameProcessId
if($CaptureCrashes){
    $Watchdog=Start-Process -FilePath $Helper -ArgumentList @('--attach',$GameProcessId) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath (Join-Path $ProjectRoot 'local\bridge\watchdog.pid') -Value $Watchdog.Id
    Write-Output 'Crash helper is waiting for normal initialization, then attaches externally. Check local/crashes/*/events.jsonl for started/failed status.'
}
Write-Output "Private original game PID: $GameProcessId"
Write-Output 'Use only disposable saves in this private copy. Run start-bridge.ps1 separately.'
