param([ValidateSet('NativeAlphaComparison','WaterImageOwnership','NativeTopology','DistantScenery','NativeUI')][string]$Test='NativeAlphaComparison')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$ProjectRoot=Get-UEMWRoot
. (Join-Path $PSScriptRoot 'client-path.ps1')
Test-UEMWClientPackage -ProjectRoot $ProjectRoot
& python (Join-Path $PSScriptRoot 'make_client_test_fixture.py')
if($LASTEXITCODE){throw 'Owned alpha fixtures could not be generated'}
$Client=Join-Path $ProjectRoot 'local/client/Windows/UEMorrowind/Binaries/Win64/UEMorrowind.exe'
$Log=Join-Path $ProjectRoot $(switch($Test){NativeAlphaComparison{'logs/client-alpha-gpu.log'};WaterImageOwnership{'logs/client-reflection-gpu.log'};NativeTopology{'logs/client-topology-gpu.log'};DistantScenery{'logs/client-distant-gpu.log'};NativeUI{'logs/client-ui-gpu.log'}})
$Arguments=@('/Engine/Maps/Entry','-d3d11','-norhithread','-unattended','-nosound','-nosplash','-windowed','-ResX=128','-ResY=96','-UEMWPassive','-UEMWSeparate',"`"-UEMWRoot=$ProjectRoot`"","`"-ExecCmds=Automation RunTests UEMW.Renderer.$Test`"",'"-TestExit=Automation Test Queue Empty"',"`"-abslog=$Log`"")
$Started=[datetime]::UtcNow
$Run=Start-Process -FilePath $Client -ArgumentList $Arguments -WorkingDirectory (Split-Path $Client) -PassThru -WindowStyle Hidden
if(!$Run.WaitForExit(60000)){Stop-Process -Id $Run.Id;throw 'Owned GPU comparison exceeded its 60-second limit'}
if(!(Test-Path -LiteralPath $Log) -or (Get-Item -LiteralPath $Log).LastWriteTimeUtc -lt $Started){throw 'No fresh GPU comparison log'}
$Contents=Get-Content -LiteralPath $Log -Raw
if($Run.ExitCode -ne 0 -or $Contents -match '(Fatal error|Assertion failed|Ensure condition failed|Result=\{Fail)' -or $Contents -notmatch "Test Completed\. Result=\{Success\}.*$Test" -or $Contents -notmatch 'Queue Empty 1 tests performed'){throw "GPU comparison failed; see $Log"}
Write-Output "Passed owned GPU test ${Test}: $Log"
