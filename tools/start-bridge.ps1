param([int]$GamePid=0,[ValidateRange(1,60)][int]$Hz=60,[switch]$Diagnostic,[switch]$Background,[switch]$FileTransport)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$ProjectRoot=Split-Path -Parent $PSScriptRoot
if(!$GamePid){$GamePid=[int](Get-Content -LiteralPath (Join-Path $ProjectRoot 'local\bridge\game.pid'))}
$Producer=if($Diagnostic){'live_probe.py'}else{'geometry_stream.py'}
$TransportArgs=@();if($FileTransport -and !$Diagnostic){$TransportArgs+='--file-transport'}
if($Background){
    $Script=Join-Path $ProjectRoot ('bridge\'+$Producer)
    $Process=Start-UEMWPythonProcess -Script $Script -ScriptArguments (@('--pid',"$GamePid",'--seconds','-1','--hz',"$Hz")+$TransportArgs) -StandardOutput (Join-Path $ProjectRoot 'logs\bridge-session.stdout.log') -StandardError (Join-Path $ProjectRoot 'logs\bridge-session.stderr.log')
    Set-Content -LiteralPath (Join-Path $ProjectRoot 'local\bridge\reader.pid') $Process.Id
    Write-Output "Bridge PID: $($Process.Id)"
    return
}
& python (Join-Path $ProjectRoot ('bridge\'+$Producer)) --pid $GamePid --seconds -1 --hz $Hz @TransportArgs
if($LASTEXITCODE){throw "Bridge failed: $LASTEXITCODE"}
