param([ValidateSet('NativeAlphaComparison','WaterImageOwnership','NativeTopology','DistantScenery','NativeUI','NativeVertexAttributes','ReflectionMembership','RigidComponentTransforms','NativeSkinPoses','NativeTerrainBlend','NativeLighting','FirstPersonPresentation')][string]$Test='NativeAlphaComparison',[ValidateSet('d3d11','d3d12')][string]$RHI='d3d11',[switch]$EnableRHIThread)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$ProjectRoot=Get-UEMWRoot
. (Join-Path $PSScriptRoot 'client-path.ps1')
Test-UEMWClientPackage -ProjectRoot $ProjectRoot
& python (Join-Path $PSScriptRoot 'make_client_test_fixture.py')
if($LASTEXITCODE){throw 'Owned alpha fixtures could not be generated'}
# Tests must never inherit the live game's lights, geometry or source state.
$FixtureRoot=Join-Path $ProjectRoot ('local/test-temp/gpu-'+$Test+'-'+[guid]::NewGuid().ToString('N'))
$FixtureTarget=Join-Path $FixtureRoot 'local/test-temp/client-fixture'
New-Item -ItemType Directory -Path $FixtureTarget -Force|Out-Null
foreach($Item in Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'local/test-temp/client-fixture')){Copy-Item -LiteralPath $Item.FullName -Destination $FixtureTarget -Recurse -Force}
$Client=Join-Path $ProjectRoot 'local/client/Windows/UEMorrowind/Binaries/Win64/UEMorrowind.exe'
$Log=Join-Path $ProjectRoot $(switch($Test){FirstPersonPresentation{'logs/client-first-person-gpu.log'};NativeAlphaComparison{'logs/client-alpha-gpu.log'};WaterImageOwnership{'logs/client-reflection-gpu.log'};NativeTopology{'logs/client-topology-gpu.log'};DistantScenery{'logs/client-distant-gpu.log'};NativeUI{'logs/client-ui-gpu.log'};NativeVertexAttributes{'logs/client-mutable-gpu.log'};ReflectionMembership{'logs/client-reflection-membership-gpu.log'};RigidComponentTransforms{'logs/client-rigid-components-gpu.log'};NativeSkinPoses{'logs/client-skin-gpu.log'};NativeTerrainBlend{'logs/client-terrain-gpu.log'};NativeLighting{'logs/client-lighting-gpu.log'}})
if($RHI -ne 'd3d11' -or $EnableRHIThread){$Log=[IO.Path]::Combine([IO.Path]::GetDirectoryName($Log),[IO.Path]::GetFileNameWithoutExtension($Log)+'-'+$RHI+$(if($EnableRHIThread){'-thread'}else{'-no-thread'})+'.log')}
$ThreadFlag=if($EnableRHIThread){'-rhithread'}else{'-norhithread'}
$Arguments=@('/Engine/Maps/Entry',"-$RHI",'-sm5',$ThreadFlag,'-unattended','-nosound','-nosplash','-windowed','-ResX=128','-ResY=96','-UEMWPassive','-UEMWSeparate',"`"-UEMWRoot=$FixtureRoot`"","`"-ExecCmds=r.RHIThread.Enable,Automation RunTests UEMW.Renderer.$Test`"",'"-TestExit=Automation Test Queue Empty"',"`"-abslog=$Log`"")
$Started=[datetime]::UtcNow
$Arguments+=Get-UEMWAllocatorArgument
if($Test -eq 'NativeUI'){
    $Token=[guid]::NewGuid().ToString('D')
    $Fixture=Start-UEMWPythonProcess -Script (Join-Path $ProjectRoot 'tools/shared_channel_fixture.py') -ScriptArguments @($Token,"`"$FixtureTarget`"") -StandardError (Join-Path $ProjectRoot 'logs/ui-shared-gpu-fixture.stderr.log')
    $Until=[datetime]::UtcNow.AddSeconds(8);$Ready=$false
    while([datetime]::UtcNow -lt $Until){
        if($Fixture.HasExited){throw 'Owned shared UI fixture exited before readiness'}
        $ReadyPath=Join-Path $FixtureTarget 'shared-ready.json'
        if(Test-Path -LiteralPath $ReadyPath){try{$State=Get-Content -LiteralPath $ReadyPath -Raw|ConvertFrom-Json;$Ready=$State.token -eq $Token -and $State.pid -eq $Fixture.Id}catch{}}
        if($Ready){break};Start-Sleep -Milliseconds 50
    }
    if(!$Ready){$Fixture.Kill();throw 'Owned shared UI fixture readiness timed out'}
}
try {
$Run=Start-Process -FilePath $Client -ArgumentList $Arguments -WorkingDirectory (Split-Path $Client) -PassThru -WindowStyle Hidden
if(!$Run.WaitForExit(60000)){Stop-Process -Id $Run.Id;throw 'Owned GPU comparison exceeded its 60-second limit'}
} finally {
    if($Test -eq 'NativeUI' -and $Fixture){
        Set-Content -LiteralPath (Join-Path $FixtureTarget 'shared-exit.request') -Value 'stop'
        if(!$Fixture.WaitForExit(2000)){$Fixture.Kill();$Fixture.WaitForExit()}
    }
}
if(!(Test-Path -LiteralPath $Log) -or (Get-Item -LiteralPath $Log).LastWriteTimeUtc -lt $Started){throw 'No fresh GPU comparison log'}
$Contents=Get-Content -LiteralPath $Log -Raw
$ExpectedAllocator=(Get-UEMWAllocatorArgument).TrimStart('-').Replace('binnedmalloc','binned')
if($Contents -notmatch "LogInit: Allocator: $ExpectedAllocator"){throw 'GPU test did not confirm the requested allocator.'}
$ExpectedThread=if($EnableRHIThread){1}else{0}
if($Contents -notmatch "Using Forced RHI: $($RHI.ToUpperInvariant())" -or $Contents -notmatch "r.RHIThread.Enable.*Currently $ExpectedThread"){throw "Owned GPU test did not confirm the requested backend/thread mode: $Log"}
if($Run.ExitCode -ne 0 -or $Contents -match '(Fatal error|Assertion failed|Ensure condition failed|Result=\{Fail)' -or $Contents -notmatch "Test Completed\. Result=\{Success\}.*$Test" -or $Contents -notmatch 'Queue Empty 1 tests performed'){throw "GPU comparison failed; see $Log"}
Write-Output "Passed owned GPU test ${Test}: $Log"
