$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$Folder=Join-Path $ProjectRoot 'local\bridge'
$ExpectedExe=Join-Path $ProjectRoot 'local\client\Windows\UEMorrowind\Binaries\Win64\UEMorrowind.exe'
$State=Read-UEMWAtomicJson -Path (Join-Path $Folder 'renderer-guard.json')
$RendererId=[int]$State.renderer_pid
$Renderer=Get-CimInstance Win32_Process -Filter "ProcessId=$RendererId"
if(!$Renderer){Write-Output 'The UE view is already closed. Original Morrowind was not touched.';return}
if($Renderer.ExecutablePath -ine $ExpectedExe -or $Renderer.CommandLine -notmatch '(?i)(?:^|\s)-UEMWManaged(?:\s|$)'){throw 'Recorded renderer is not this project managed client; nothing was stopped.'}
$GuardId=[int]$State.guard_pid
$Guard=Get-CimInstance Win32_Process -Filter "ProcessId=$GuardId"
if(!$Guard -or $Guard.CommandLine -notlike "*$(Join-Path $ProjectRoot 'bridge\renderer_guard.py')*" -or $State.event -ne 'started'){throw 'The matching cutoff is unavailable. Use Stop-UEMW.cmd to close the private session.'}
$Request=Join-Path $Folder 'renderer-stop.json'
@{protocol='uemw.renderer-stop';version=1;renderer_pid=$RendererId;game_pid=$State.game_pid;run_token=$State.run_token}|ConvertTo-Json -Compress|Set-Content -LiteralPath "$Request.launch.tmp" -Encoding utf8
Move-Item -LiteralPath "$Request.launch.tmp" -Destination $Request -Force
$Until=[datetime]::UtcNow.AddSeconds(5)
do {
    $Current=Read-UEMWAtomicJson -Path (Join-Path $Folder 'renderer-guard.json')
    if($Current.run_token -eq $State.run_token -and $Current.event -eq 'stopped'){
        Write-Output "UE view stopped: $($Current.reason). Original Morrowind remains open.";return
    }
    Start-Sleep -Milliseconds 100
}while([datetime]::UtcNow -lt $Until)
throw 'UE cutoff did not acknowledge the stop request. Use Stop-UEMW.cmd to close the private session.'
