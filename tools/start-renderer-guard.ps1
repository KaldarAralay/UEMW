$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$StateRoot=Join-Path $ProjectRoot 'local\bridge'
$Script=Join-Path $ProjectRoot 'bridge\renderer_guard.py'
$RendererExe=Join-Path $ProjectRoot 'local\client\Windows\UEMorrowind\Binaries\Win64\UEMorrowind.exe'
$RendererProcessId=[int](Get-Content -LiteralPath (Join-Path $StateRoot 'renderer.pid'))
$GameProcessId=[int](Get-Content -LiteralPath (Join-Path $StateRoot 'game.pid'))
$Renderer=Get-CimInstance Win32_Process -Filter "ProcessId=$RendererProcessId"
if(!$Renderer -or $Renderer.ExecutablePath -ine $RendererExe -or $Renderer.CommandLine -notmatch '(?i)(?:^|\s)-UEMWManaged(?:\s|$)'){throw 'Cutoff requires this project managed packaged renderer.'}
$GuardFile=Join-Path $StateRoot 'renderer-guard.pid'
$Guard=$null
if(Test-Path -LiteralPath $GuardFile){
    $GuardId=[int](Get-Content -LiteralPath $GuardFile)
    $Guard=Get-CimInstance Win32_Process -Filter "ProcessId=$GuardId"
    if($Guard -and $Guard.CommandLine -notlike "*$Script*"){
        Remove-Item -LiteralPath $GuardFile -Force
        $Guard=$null
    }
    if($Guard -and ($Guard.CommandLine -notmatch "--renderer\s+$RendererProcessId(\s|$)" -or $Guard.CommandLine -notmatch "--pid\s+$GameProcessId(\s|$)")){
        Stop-Process -Id $GuardId -ErrorAction Stop;$Guard=$null
    }
}
if(!$Guard){
    $Guard=Start-UEMWPythonProcess -Script $Script -ScriptArguments @('--pid',"$GameProcessId",'--renderer',"$RendererProcessId",'--renderer-exe',"`"$RendererExe`"") -StandardOutput (Join-Path $ProjectRoot 'logs\renderer-guard.stdout.log') -StandardError (Join-Path $ProjectRoot 'logs\renderer-guard.stderr.log')
    $GuardId=$Guard.Id
    Set-Content -LiteralPath $GuardFile $GuardId
}
$Confirmed=$false
$Until=[datetime]::UtcNow.AddSeconds(5)
do {
    try {
        $State=Get-Content -LiteralPath (Join-Path $StateRoot 'renderer-guard.json') -Raw -ErrorAction Stop|ConvertFrom-Json
        if($State.guard_pid -eq $GuardId -and $State.renderer_pid -eq $RendererProcessId -and $State.game_pid -eq $GameProcessId -and $State.event -eq 'started'){$Confirmed=$true;break}
    }catch{}
    Start-Sleep -Milliseconds 100
}while([datetime]::UtcNow -lt $Until)
if(!$Confirmed){throw 'Renderer cutoff did not initialize. See logs/renderer-guard.stderr.log.'}
Write-Output 'Independent UE cutoff ready. Stop-UE-View.cmd closes UE and stops its bridge; original Morrowind remains open.'
