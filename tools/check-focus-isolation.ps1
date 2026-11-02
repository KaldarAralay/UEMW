param([switch]$Trace,[ValidateSet('vulkan','d3d11')][string]$RHI='d3d11',[switch]$CombinedOnly,[switch]$CaptureOnce,[switch]$NormalPlay,[switch]$NpcMotion,[switch]$WaterPlay,[switch]$CombatPlay,[switch]$VisualCheck,[switch]$OutdoorCheck,[switch]$TextureCheck,[switch]$TerrainCheck,[switch]$StabilityCheck,[switch]$DisplayTiming,[switch]$CompositionTiming,[switch]$NativeOnly,[string]$Checkpoint='UEMW Broad Quest Complete')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment -Development
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$GameProcessId=0
& python -c 'import psutil'
if($LASTEXITCODE){throw 'Optional focus diagnostics require an existing psutil installation. No game was started or dependency installed.'}
if($DisplayTiming -and ($CombinedOnly -or $NormalPlay -or $NpcMotion -or $WaterPlay -or $CombatPlay -or $VisualCheck -or $OutdoorCheck -or $TextureCheck -or $TerrainCheck)){throw 'Elevated display isolation requires three phases without gameplay fixtures. No game was started.'}
if($CompositionTiming -and ($NormalPlay -or $NpcMotion -or $WaterPlay -or $CombatPlay -or $VisualCheck -or $OutdoorCheck -or $TextureCheck -or $TerrainCheck)){throw 'Composition check must be separate from gameplay fixtures. No game was started.'}
if($NativeOnly -and ($DisplayTiming -or $CombinedOnly -or $NormalPlay -or $NpcMotion -or $WaterPlay -or $CombatPlay -or $VisualCheck -or $OutdoorCheck -or $TextureCheck -or $TerrainCheck)){throw 'Native-only cannot launch a renderer or elevated observer. No game was started.'}
if($DisplayTiming -and !(Test-Path -LiteralPath (Join-Path $ProjectRoot 'local\bin\PresentMon-2.3.1-x64.exe'))){throw 'Missing optional pinned display observer. No game was started.'}
try {
    & (Join-Path $PSScriptRoot 'start-game.ps1')
    $GameProcessId=[int](Get-Content -LiteralPath (Join-Path $ProjectRoot 'local\bridge\game.pid'))
    $Python=(Get-Command python).Source
    $TestDeadline=if($StabilityCheck -and ($env:UEMW_LIGHTING_LABEL -or $env:UEMW_WATER_ATMOSPHERE -or $env:UEMW_WATER_REFLECTION -or $env:UEMW_CHARACTER_LABEL -or $env:UEMW_EFFECT_LABEL -or $env:UEMW_INTERIOR_LABEL -or $env:UEMW_CLEAN_TEXTURE_LABEL -or $env:UEMW_FOLIAGE_LABEL)){300}else{180}
    $Deadline=Start-Process -FilePath $Python -ArgumentList @("`"$(Join-Path $ProjectRoot 'bridge\process_deadline.py')`"",'--pid',$GameProcessId,'--seconds',$TestDeadline) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $ProjectRoot 'logs\focus-isolation-deadline.stdout.log') -RedirectStandardError (Join-Path $ProjectRoot 'logs\focus-isolation-deadline.stderr.log')
    @{pid=$GameProcessId;phase='awaiting_disposable_load'}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $ProjectRoot 'local\bridge\focus-isolation-control.json')
    $TraceArgs=@();if($Trace){$TraceArgs+='--trace'}
    if($CombinedOnly){$TraceArgs+='--combined-only'}
    if($CaptureOnce){$TraceArgs+='--capture-once'}
    if($NormalPlay){$TraceArgs+='--normal-play'}
    if($WaterPlay){$TraceArgs+='--water-play'}
    if($CombatPlay){$TraceArgs+='--combat-play'}
    if($OutdoorCheck){$TraceArgs+='--outdoor-check'}
    if($TextureCheck){$TraceArgs+='--texture-check'}
    if($TerrainCheck){$TraceArgs+='--terrain-check'}
    if($StabilityCheck){$TraceArgs+='--stability-check'}
    if($VisualCheck){$TraceArgs+='--visual-check'}
    if($NpcMotion){$TraceArgs+='--npc-motion'}
    if($DisplayTiming){$TraceArgs+='--display-timing'}
    if($CompositionTiming){$TraceArgs+='--composition-timing'}
    if($NativeOnly){$TraceArgs+='--native-only'}
    $TraceArgs+=@('--checkpoint',$Checkpoint)
    & $Python (Join-Path $ProjectRoot 'dev\diagnostics\check_focus_stages.py') --pid $GameProcessId --rhi $RHI @TraceArgs
    if($LASTEXITCODE){throw 'Isolation stopped with a failed stage; see logs/focus-isolation.json.'}
} finally {
    if($GameProcessId){
        try {& (Join-Path $PSScriptRoot 'stop-renderer.ps1')}
        catch {Write-Warning "View-only cutoff did not acknowledge; proceeding to exact private-session cleanup: $_"}
        finally {& (Join-Path $PSScriptRoot 'stop-session.ps1')}
    }
}


