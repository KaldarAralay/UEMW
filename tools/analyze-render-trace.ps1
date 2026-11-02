param([string]$EngineRoot,[switch]$Events)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$EngineRoot=Resolve-UEMWEngineRoot -EngineRoot $EngineRoot
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$Insights=Join-Path $EngineRoot 'Engine\Binaries\Win64\UnrealInsights.exe'
$Trace=Join-Path $ProjectRoot 'logs\client-performance.utrace'
$Csv=Join-Path $ProjectRoot $(if($Events){'logs\client-events.csv'}else{'logs\client-timers.csv'})
$Log=Join-Path $ProjectRoot 'logs\trace-analysis.log'
foreach($Required in @($Insights,$Trace)){if(!(Test-Path -LiteralPath $Required)){throw "Missing trace prerequisite: $Required"}}
$Command=if($Events){"TimingInsights.ExportTimingEvents $Csv -columns=*"}else{"TimingInsights.ExportTimerStatistics $Csv"}
$ArgsList=@('-NoUI','-AutoQuit','-notraceserver',"-OpenTraceFile=`"$Trace`"","-ExecOnAnalysisCompleteCmd=`"$Command`"","-abslog=`"$Log`"")
$Analysis=Start-Process -FilePath $Insights -ArgumentList $ArgsList -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
if(!$Analysis.WaitForExit(45000)){Stop-Process -Id $Analysis.Id -ErrorAction SilentlyContinue;throw 'Trace analysis exceeded 45 seconds.'}
if($Analysis.ExitCode -or !(Test-Path -LiteralPath $Csv)){throw "Trace analysis did not export timers. See $Log"}
Write-Output "Engine timing export: $Csv"
