param([ValidateRange(128,8192)][int]$Width=1920,[ValidateRange(96,8192)][int]$Height=1080,[switch]$TwoWindows=$true,[switch]$Editor,[string]$EngineRoot)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
if($Editor){$EngineRoot=Resolve-UEMWEngineRoot -EngineRoot $EngineRoot}
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$StateRoot=Join-Path $ProjectRoot 'local\bridge'
$PrivateExe=Join-Path $ProjectRoot 'local\Morrowind\Morrowind.exe'
$UProject=Join-Path $ProjectRoot 'ue\UEMorrowind\UEMorrowind.uproject'
$ControllerScript=Join-Path $ProjectRoot 'bridge\presentation.py'
$GameProcessId=[int](Get-Content -LiteralPath (Join-Path $StateRoot 'game.pid'))
$RendererProcessId=[int](Get-Content -LiteralPath (Join-Path $StateRoot 'renderer.pid'))
$Game=Get-CimInstance Win32_Process -Filter "ProcessId=$GameProcessId"
$Renderer=Get-CimInstance Win32_Process -Filter "ProcessId=$RendererProcessId"
. (Join-Path $PSScriptRoot 'client-path.ps1')
$RendererExe=Get-UEMWRenderer -ProjectRoot $ProjectRoot -EngineRoot $EngineRoot -Editor:$Editor
if(!$Game -or $Game.ExecutablePath -ine $PrivateExe){throw 'Presentation requires the verified private game.'}
if(!$Renderer -or $Renderer.ExecutablePath -ine $RendererExe -or ($Editor -and $Renderer.CommandLine -notlike "*$UProject*") -or $Renderer.CommandLine -notmatch '(?i)(?:^|\s)-UEMWManaged(?:\s|$)'){throw 'Presentation requires this project managed renderer.'}
if([bool]($Renderer.CommandLine -match '(?i)(?:^|\s)-UEMWSeparate(?:\s|$)') -ne [bool]$TwoWindows){throw 'Renderer window mode differs. Use start-session.ps1 with the desired mode to restart only the renderer.'}
$Mode=if($TwoWindows){'side-by-side'}else{'overlay'}
$ModePath=Join-Path $StateRoot 'presentation-mode.json'
@{version=1;mode=$Mode;viewport=@($Width,$Height);generation=[guid]::NewGuid().ToString()}|ConvertTo-Json -Compress|Set-Content -LiteralPath "$ModePath.launch.tmp" -Encoding utf8
Move-Item -LiteralPath "$ModePath.launch.tmp" -Destination $ModePath -Force
$ControllerFile=Join-Path $StateRoot 'presentation.pid'
$Controller=$null
if(Test-Path -LiteralPath $ControllerFile){
    $ControllerProcessId=[int](Get-Content -LiteralPath $ControllerFile)
    $Controller=Get-CimInstance Win32_Process -Filter "ProcessId=$ControllerProcessId"
    if($Controller -and $Controller.CommandLine -notlike "*$ControllerScript*"){
        Remove-Item -LiteralPath $ControllerFile -Force
        $Controller=$null
    }
    if($Controller -and ($Controller.CommandLine -notmatch "--pid\s+$GameProcessId(\s|$)" -or $Controller.CommandLine -notmatch "--renderer\s+$RendererProcessId(\s|$)")){
        Stop-Process -Id $ControllerProcessId -ErrorAction Stop
        $Controller=$null
    }
}
if(!$Controller){
    $ControllerArgs=@('--pid',"$GameProcessId",'--renderer',"$RendererProcessId",'--renderer-exe',"`"$RendererExe`"")
    if($TwoWindows){$ControllerArgs+='--separate'}
    $Controller=Start-UEMWPythonProcess -Script $ControllerScript -ScriptArguments $ControllerArgs -StandardOutput (Join-Path $ProjectRoot 'logs\presentation.stdout.log') -StandardError (Join-Path $ProjectRoot 'logs\presentation.stderr.log')
    Set-Content -LiteralPath $ControllerFile $Controller.Id
}
Write-Output "Presentation controller PID: $($Controller.ProcessId ?? $Controller.Id); mode: $Mode"
if($TwoWindows){Write-Output 'Keep original Morrowind focused; native UI remains beside the passive UE view. No recording.'}
else{Write-Output 'Keep original Morrowind focused. UE presents its native HUD and menus; loading/unsupported UI uncovers the original. No recording.'}
