param([ValidateRange(128,8192)][int]$Width=1920,[ValidateRange(96,8192)][int]$Height=1080,[ValidateRange(15,60)][int]$MaxFPS=60,[ValidateRange(1,60)][int]$StateHz=60,[switch]$CaptureCrashes,[switch]$Editor,[switch]$TwoWindows=$true,[switch]$Overlay,[switch]$DiagnosticScreenshots,[switch]$DiagnosticTrace,[switch]$PresentationStats,[string]$EngineRoot,[ValidateSet('d3d11','d3d12','vulkan')][string]$RHI='d3d11',[switch]$CheckOnly)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
if($Editor){$EngineRoot=Resolve-UEMWEngineRoot -EngineRoot $EngineRoot}
if($Overlay){$TwoWindows=$false}
$ProjectRoot=Split-Path -Parent $PSScriptRoot
if(!(Test-Path -LiteralPath (Join-Path $ProjectRoot 'local\venv\Scripts\python.exe'))){throw 'Project Python environment is missing. Run Setup-UEMW.cmd first. No game was started.'}
. (Join-Path $PSScriptRoot 'client-path.ps1')
$RendererExe=Get-UEMWRenderer -ProjectRoot $ProjectRoot -EngineRoot $EngineRoot -Editor:$Editor
if(!(Test-Path -LiteralPath $RendererExe)){throw "Renderer build missing: $RendererExe. Run tools/package-client.ps1 first. No game was started."}
if(!$Editor){Test-UEMWClientPackage -ProjectRoot $ProjectRoot}
& python -c 'import struct,numpy,PIL; assert struct.calcsize("P")==8, "Use 64-bit Python"'
if($LASTEXITCODE){throw 'Missing 64-bit Python/NumPy/Pillow prerequisite. Nothing was installed or started.'}
& python -c 'import sys;sys.path.insert(0,sys.argv[1]);from native_read_batch import helper;assert helper() is not None, "External read-batch helper missing or stale. Run tools/package-client.ps1 or tools/build-read-batch.ps1 before launch."' (Join-Path $ProjectRoot 'bridge')
if($LASTEXITCODE){throw 'Native read-batch prerequisite failed. No game was started.'}
. (Join-Path $PSScriptRoot 'native-startup.ps1')
if($CheckOnly){$null=Get-UEMWSteamStartup -ProjectRoot $ProjectRoot;Write-Output 'Launcher, Steam shortcut and native bootstrap prerequisites verified. No game, bridge or renderer was started.';return}
$PrivateExe=Join-Path $ProjectRoot 'local\Morrowind\Morrowind.exe'
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot 'local\bridge'),(Join-Path $ProjectRoot 'logs') | Out-Null
$Games=@(Get-CimInstance Win32_Process -Filter "Name='Morrowind.exe'")
if($Games.Count -gt 1 -or ($Games.Count -eq 1 -and $Games[0].ExecutablePath -ine $PrivateExe)){
    throw 'Another/non-private Morrowind session exists. Close it before using this private prototype launcher.'
}
if(!$Games.Count){
    & (Join-Path $PSScriptRoot 'start-game.ps1') -CaptureCrashes:$CaptureCrashes
    $GameProcessId=[int](Get-Content -LiteralPath (Join-Path $ProjectRoot 'local\bridge\game.pid'))
}else{
    $GameProcessId=[int]$Games[0].ProcessId
    Set-Content -LiteralPath (Join-Path $ProjectRoot 'local\bridge\game.pid') $GameProcessId
    if($CaptureCrashes){Write-Output 'Existing private game reused; crash capture requires launching a new session with -CaptureCrashes.'}
}
# An explicit launch rearms the cutoff. Stop its old process before examining
# bridge stop requests, so an exiting old renderer cannot race this launch.
& (Join-Path $PSScriptRoot 'stop-renderer-guard.ps1')
$ReaderFile=Join-Path $ProjectRoot 'local\bridge\reader.pid'
$Reader=$null
if(Test-Path -LiteralPath $ReaderFile){
    $ReaderProcessId=[int](Get-Content -LiteralPath $ReaderFile)
    $Reader=Get-CimInstance Win32_Process -Filter "ProcessId=$ReaderProcessId"
    if($Reader -and $Reader.CommandLine -notlike "*$(Join-Path $ProjectRoot 'bridge\geometry_stream.py')*"){
        Remove-Item -LiteralPath $ReaderFile -Force
        $Reader=$null
        Write-Output 'Discarded a stale bridge PID record; the unrelated process was left untouched.'
    }
    if($Reader -and ($Reader.CommandLine -notmatch "--pid\s+$GameProcessId(\s|$)" -or $Reader.CommandLine -notmatch "--hz\s+$StateHz(\s|$)")){
        Stop-Process -Id $ReaderProcessId -ErrorAction Stop
        Write-Output 'Restarting this project bridge for the requested private game PID/sample cap.'
        $Reader=$null
    }
}
if($Reader){
    $StopFile=Join-Path $ProjectRoot 'local\bridge\source-stop.json'
    $LatestFile=Join-Path $ProjectRoot 'local\bridge\latest.json'
    if((Test-Path -LiteralPath $StopFile) -and (Test-Path -LiteralPath $LatestFile)){
        $Stop=Get-Content -LiteralPath $StopFile -Raw|ConvertFrom-Json
        $Latest=Get-Content -LiteralPath $LatestFile -Raw|ConvertFrom-Json
        if($Stop.protocol -eq 'uemw.source-stop' -and $Stop.version -eq 1 -and $Stop.game_pid -eq $GameProcessId -and $Stop.session -eq $Latest.session){
            Stop-Process -Id $ReaderProcessId -ErrorAction SilentlyContinue
            $Reader=$null
        }
    }
}
if(!$Reader){& (Join-Path $PSScriptRoot 'start-bridge.ps1') -GamePid $GameProcessId -Hz $StateHz -Background}
# Wait for this producer's actual shared-channel publication. An exited native
# startup or reader must not be followed by an unrelated blank UE window.
$ReaderProcessId=[int](Get-Content -LiteralPath $ReaderFile)
$LiveReader=Get-Process -Id $ReaderProcessId -ErrorAction SilentlyContinue
$BridgeReady=$false;$Until=[datetime]::UtcNow.AddSeconds(6)
while($LiveReader -and !$LiveReader.HasExited -and [datetime]::UtcNow -lt $Until){
    try {
        $Published=Get-Content -LiteralPath (Join-Path $ProjectRoot 'local\bridge\latest.json') -Raw -ErrorAction Stop|ConvertFrom-Json
        $BridgeReady=$Published.protocol -eq 'uemw.channel' -and $Published.version -eq 1 -and $Published.pid -eq $GameProcessId -and $Published.writer_pid -eq $ReaderProcessId
        if(!$BridgeReady -and $Published.protocol -eq 'uemw.live' -and $Published.pid -eq $GameProcessId){
            $StartedNs=([DateTimeOffset]$LiveReader.StartTime.ToUniversalTime()).ToUnixTimeMilliseconds()*1000000.0
            $NowNs=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()*1000000.0
            $BridgeReady=$Published.sample_unix_ns -ge $StartedNs -and $NowNs-$Published.sample_unix_ns -ge 0 -and $NowNs-$Published.sample_unix_ns -lt 2000000000
        }
    }catch{}
    if($BridgeReady){break};Start-Sleep -Milliseconds 100
}
if(!$BridgeReady){
    $Details=(Get-Content -LiteralPath (Join-Path $ProjectRoot 'logs\bridge-session.stderr.log') -Tail 8 -ErrorAction SilentlyContinue)-join "`n"
    throw "The native bridge did not initialize for private PID $GameProcessId. UE was not started.`n$Details"
}
Write-Output "Native bridge connection verified: $ReaderProcessId"
$UProject=Join-Path $ProjectRoot 'ue\UEMorrowind\UEMorrowind.uproject'
$Renderers=@(Get-CimInstance Win32_Process -Filter "Name='UnrealEditor.exe' OR Name='UEMorrowind.exe'" | Where-Object {$_.ExecutablePath -ieq $RendererExe -and $_.CommandLine -match '(?i)(?:^|\s)-UEMWManaged(?:\s|$)' -and (!$Editor -or $_.CommandLine -like "*$UProject*")})
if($Renderers.Count -gt 1){throw 'Multiple project renderers exist; launch refused.'}
if($Renderers.Count -and ($Renderers[0].CommandLine -notmatch "(?i)(?:^|\s)-UEMWMaxFPS=$MaxFPS(?:\s|$)" -or $Renderers[0].CommandLine -notmatch '(?i)(?:^|\s)-norhithread(?:\s|$)' -or $Renderers[0].CommandLine -notmatch "(?i)(?:^|\s)-ResX=$Width(?:\s|$)" -or $Renderers[0].CommandLine -notmatch "(?i)(?:^|\s)-ResY=$Height(?:\s|$)" -or $Renderers[0].CommandLine -notmatch "(?i)(?:^|\s)-$RHI(?:\s|$)" -or [bool]($Renderers[0].CommandLine -match '(?i)(?:^|\s)-UEMWSeparate(?:\s|$)') -ne [bool]$TwoWindows)){
    # Retain this verified bridge when explicitly changing client settings.
    & (Join-Path $PSScriptRoot 'stop-renderer-guard.ps1')
    Stop-Process -Id $Renderers[0].ProcessId -ErrorAction Stop
    $Renderers=@()
    Write-Output "Restarting this project renderer with managed presentation and $RHI."
}
if(!$Renderers.Count){& (Join-Path $PSScriptRoot 'start-renderer.ps1') -EngineRoot $EngineRoot -Editor:$Editor -TwoWindows:$TwoWindows -RHI $RHI -Width $Width -Height $Height -MaxFPS $MaxFPS -DiagnosticScreenshots:$DiagnosticScreenshots -DiagnosticTrace:$DiagnosticTrace -PresentationStats:$PresentationStats}
else{
    Set-Content -LiteralPath (Join-Path $ProjectRoot 'local\bridge\renderer.pid') $Renderers[0].ProcessId
    if(!$Editor){
        try {& (Join-Path $PSScriptRoot 'start-renderer-guard.ps1')}
        catch {Stop-Process -Id $Renderers[0].ProcessId -ErrorAction SilentlyContinue;throw}
    }
    & (Join-Path $PSScriptRoot 'start-presentation.ps1') -TwoWindows:$TwoWindows -EngineRoot $EngineRoot -Editor:$Editor -Width $Width -Height $Height
    Write-Output "Existing project renderer reused: $($Renderers[0].ProcessId)"
}
Write-Output 'Private processes started. Use a disposable native save or new game in original Morrowind. The UE view appears when shaders and live geometry are ready.'
if($TwoWindows){Write-Output 'Keep original Morrowind focused; its native UI stays visible beside UE. No recording is enabled.'}
else{Write-Output 'Keep original Morrowind focused; UE covers its play area and uncovers native UI automatically. No recording is enabled.'}
