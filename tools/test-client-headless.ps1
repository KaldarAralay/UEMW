$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$Client=Join-Path $ProjectRoot 'local\client\Windows\UEMorrowind\Binaries\Win64\UEMorrowind.exe'
if(!(Test-Path -LiteralPath $Client)){throw 'Package the client first.'}
& python (Join-Path $PSScriptRoot 'make_client_test_fixture.py')
if($LASTEXITCODE){throw 'Could not create own synthetic test fixture.'}
$TestLog=Join-Path $ProjectRoot 'logs\client-headless-tests.log'
$ArgsList=@('/Engine/Maps/Entry','-nullrhi','-unattended','-nosound','-nosplash',"`"-UEMWRoot=$ProjectRoot`"",'"-ExecCmds=Automation RunTests UEMW.Renderer"','"-TestExit=Automation Test Queue Empty"',"`"-abslog=$TestLog`"")
$Token=[guid]::NewGuid().ToString('D')
$Fixture=Start-UEMWPythonProcess -Script (Join-Path $PSScriptRoot 'shared_channel_fixture.py') -ScriptArguments @($Token) -StandardError (Join-Path $ProjectRoot 'logs\shared-fixture.stderr.log')
try {
 $ReadyPath=Join-Path $ProjectRoot 'local\test-temp\client-fixture\shared-ready.json'
 $Ready=$false;$Until=[datetime]::UtcNow.AddSeconds(8)
 while([datetime]::UtcNow -lt $Until){
  if($Fixture.HasExited){throw 'Owned shared fixture exited before readiness. See logs/shared-fixture.stderr.log.'}
  if(Test-Path -LiteralPath $ReadyPath){try{$State=Get-Content -LiteralPath $ReadyPath -Raw|ConvertFrom-Json;$Ready=$State.token -eq $Token -and $State.pid -eq $Fixture.Id}catch{}}
  if($Ready){break};Start-Sleep -Milliseconds 50
 }
 if(!$Ready){throw 'Owned shared fixture did not become ready.'}
 $TestStarted=[datetime]::UtcNow
 $Run=Start-Process -FilePath $Client -WorkingDirectory (Split-Path $Client) -ArgumentList $ArgsList -WindowStyle Hidden -PassThru
 if(!$Run.WaitForExit(45000)){Stop-Process -Id $Run.Id -ErrorAction SilentlyContinue;throw 'Headless regression test timed out after 45 seconds.'}
 if($Run.ExitCode){throw "Headless test process failed: $($Run.ExitCode)"}
}finally{if(!$Fixture.HasExited -and !$Fixture.WaitForExit(1000)){$Fixture.Kill();$Fixture.WaitForExit()}}
if(!(Test-Path -LiteralPath $TestLog) -or (Get-Item -LiteralPath $TestLog).LastWriteTimeUtc -lt $TestStarted){throw 'UE did not produce a fresh test log; an old result cannot pass this run.'}
$Contents=Get-Content -LiteralPath $TestLog -Raw
if($Contents -notmatch 'NativeTopology'){throw 'Native topology test was not executed'}
if($Contents -notmatch 'DistantScenery'){throw 'Distant scenery test was not executed'}
if($Contents -notmatch 'NativeUI'){throw 'Native UI test was not executed'}
if($Contents -notmatch 'WaterImageOwnership'){throw 'Water image-ownership test was not executed'}
if($Contents -notmatch 'NativeAlphaComparison'){throw 'Native alpha comparison test was not executed'}
if($Contents -notmatch 'RigidComponentTransforms'){throw 'Rigid component transform test was not executed'}
if($Contents -notmatch 'ReflectionMembership'){throw 'Reflection membership test was not executed'}
if($Contents -notmatch 'NativeTextureStages'){throw 'Native texture-stage test was not executed'}
if($Contents -match '(?m)(Fatal error|Assertion failed|Ensure condition failed|Result=\{Fail)' -or $Contents -notmatch 'NativeTerrainBlend' -or $Contents -notmatch 'NativeTextureUpgrades' -or $Contents -notmatch 'NativeSurfaceDetail' -or $Contents -notmatch 'NativeMaskedCoverage' -or $Contents -notmatch 'NativeOutdoorMaterials' -or $Contents -notmatch 'NativeLighting' -or $Contents -notmatch 'NativeTextureMips' -or $Contents -notmatch 'NativeAffine' -or $Contents -notmatch 'RuntimeMeshMetadata' -or $Contents -notmatch 'CatalogProgressWithoutPackets' -or $Contents -notmatch 'NativeRainPresentation' -or $Contents -notmatch 'TargetedRenderSelection' -or $Contents -notmatch 'NativeTextureFrames' -or $Contents -notmatch 'NativeMaterialValues' -or $Contents -notmatch 'NativeVertexAttributes' -or $Contents -notmatch 'GeometryResourceProgress' -or $Contents -notmatch 'RigidResourceReuse' -or $Contents -notmatch 'CameraLatestSlot' -or $Contents -notmatch 'MaterialResourceContinuity' -or $Contents -notmatch 'FreshStreamingPoses' -or $Contents -notmatch 'NativePoseReuse' -or $Contents -notmatch 'AcceptedPoseWitness' -or $Contents -notmatch 'PackedNativeMetadata' -or $Contents -notmatch 'SharedChannel' -or $Contents -notmatch 'CatalogHandoffPlans' -or $Contents -notmatch 'NativeSkinPoses' -or ([regex]::Matches($Contents,'Test Completed\. Result=\{Success\}').Count -ne 37) -or $Contents -notmatch 'Queue Empty 37 tests performed'){
 throw "Headless verification did not confirm all tests: $TestLog"
}
Write-Output "Passed headless native affine and runtime mesh tests: $TestLog"

