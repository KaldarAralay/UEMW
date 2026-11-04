param([string]$EngineRoot,[switch]$Editor,[switch]$TwoWindows=$true,[ValidateRange(128,8192)][int]$Width=1920,[ValidateRange(96,8192)][int]$Height=1080,[ValidateRange(15,60)][int]$MaxFPS=60,[switch]$DiagnosticScreenshots,[switch]$DiagnosticTrace,[switch]$PresentationStats,[switch]$DisableRHIThread,[ValidateRange(0,600)][int]$RecordSeconds=0,[ValidateSet('d3d11','d3d12','vulkan')][string]$RHI='d3d12',[ValidateSet('immediate','mailbox','fifo','auto')][string]$VulkanPresentMode='auto')
$ErrorActionPreference='Stop'
if(!$PSBoundParameters.ContainsKey('DisableRHIThread')){$DisableRHIThread=$RHI -ne 'd3d12'}
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
if($Editor){$EngineRoot=Resolve-UEMWEngineRoot -EngineRoot $EngineRoot}
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$UProject=Join-Path $ProjectRoot 'ue\UEMorrowind\UEMorrowind.uproject'
. (Join-Path $PSScriptRoot 'client-path.ps1')
$RendererExe=Get-UEMWRenderer -ProjectRoot $ProjectRoot -EngineRoot $EngineRoot -Editor:$Editor
if(!(Test-Path -LiteralPath $RendererExe)){throw "Renderer build missing: $RendererExe. Run tools/package-client.ps1 first."}
if(!$Editor){Test-UEMWClientPackage -ProjectRoot $ProjectRoot}
$InitialWidth=$Width;$InitialHeight=$Height
$ArgsList=@('/Engine/Maps/Entry','-game','-windowed','-UEMWPassive','-UEMWManaged',"-ResX=$InitialWidth","-ResY=$InitialHeight","-$RHI",'-NoSplash','-NoSound',"`"-UEMWRoot=$ProjectRoot`"","`"-abslog=$(Join-Path $ProjectRoot 'logs\ue-runtime.log')`"")
if($Editor){$ArgsList=@("`"$UProject`"")+$ArgsList}
$ArgsList+="-UEMWMaxFPS=$MaxFPS"
$ArgsList+=Get-UEMWAllocatorArgument
if($TwoWindows){$ArgsList+='-UEMWSeparate'}
if($RHI -eq 'vulkan' -and $VulkanPresentMode -ne 'auto'){
    # Opt-in diagnostic comparison only. Immediate mode did not fix the
    # measured acquire-fence stall, so ordinary launch retains engine choice.
    $PresentMode=@{immediate=0;mailbox=1;fifo=2}[$VulkanPresentMode]
    $ArgsList+="-vulkanpresentmode=$PresentMode"
}
if($DiagnosticScreenshots){$ArgsList+='-UEMWDiagnosticScreenshots'}
if($PresentationStats){$ArgsList+='-UEMWPresentationStats'}
if($DiagnosticTrace){$ArgsList+=@('-trace=cpu,frame,gpu,bookmark','-tracefiletrunc',"-tracefile=`"$(Join-Path $ProjectRoot 'logs\client-performance.utrace')`"")}
# D3D12 uses the validated separate submission thread. D3D11/Vulkan retain
# their bounded legacy path. This changes no driver or engine installation.
if($DisableRHIThread){$ArgsList+='-norhithread'}else{$ArgsList+='-rhithread'}
if($RecordSeconds){$ArgsList+="-UEMWRecordSeconds=$RecordSeconds"}
# Keep shader warmup from taking keyboard focus. The managed controller shows
# the passive window without activation once it is ready.
$Renderer=Start-Process -FilePath $RendererExe -WorkingDirectory (Split-Path $RendererExe) -ArgumentList $ArgsList -WindowStyle Hidden -PassThru
Set-Content (Join-Path $ProjectRoot 'local\bridge\renderer.pid') $Renderer.Id
Write-Output "UE renderer PID: $($Renderer.Id)"
if(!$Editor){
    try {& (Join-Path $PSScriptRoot 'start-renderer-guard.ps1')}
    catch {Stop-Process -Id $Renderer.Id -ErrorAction SilentlyContinue;throw}
}
& (Join-Path $PSScriptRoot 'start-presentation.ps1') -TwoWindows:$TwoWindows -EngineRoot $EngineRoot -Editor:$Editor -Width $Width -Height $Height
