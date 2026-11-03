param([string]$EngineRoot,[switch]$Events,[ValidateRange(0,86400)][double]$StartSeconds=0,[ValidateRange(0,86400)][double]$EndSeconds=86400,[ValidatePattern('^[A-Za-z0-9_*,.: -]+$')][string]$Threads='*',[ValidatePattern('^[A-Za-z0-9_*,.: -]+$')][string]$Timers='*')
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
if($EndSeconds -le $StartSeconds){throw 'Trace end must follow trace start.'}
$Invariant=[System.Globalization.CultureInfo]::InvariantCulture
$StartText=$StartSeconds.ToString($Invariant);$EndText=$EndSeconds.ToString($Invariant)
$Command=if($Events){"TimingInsights.ExportTimingEvents $Csv -columns=* -startTime=$StartText -endTime=$EndText -threads=$Threads -timers=$Timers"}else{"TimingInsights.ExportTimerStatistics $Csv -startTime=$StartText -endTime=$EndText"}
$ArgsList=@('-NoUI','-AutoQuit','-notraceserver',"-OpenTraceFile=`"$Trace`"","-ExecOnAnalysisCompleteCmd=`"$Command`"","-abslog=`"$Log`"")
$Analysis=Start-Process -FilePath $Insights -ArgumentList $ArgsList -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
if(!$Analysis.WaitForExit(45000)){Stop-Process -Id $Analysis.Id -ErrorAction SilentlyContinue;throw 'Trace analysis exceeded 45 seconds.'}
if($Analysis.ExitCode -or !(Test-Path -LiteralPath $Csv)){throw "Trace analysis did not export timers. See $Log"}
Write-Output "Engine timing export: $Csv"
