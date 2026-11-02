param([string]$LogPrefix='performance')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment -Development
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$GameProcessId=[int](Get-Content -LiteralPath (Join-Path $ProjectRoot 'local\bridge\game.pid'))
$ReaderProcessId=[int](Get-Content -LiteralPath (Join-Path $ProjectRoot 'local\bridge\reader.pid'))
$Game=Get-CimInstance Win32_Process -Filter "ProcessId=$GameProcessId"
$Reader=Get-CimInstance Win32_Process -Filter "ProcessId=$ReaderProcessId"
if(!$Game -or $Game.ExecutablePath -ine (Join-Path $ProjectRoot 'local\Morrowind\Morrowind.exe')){throw 'Private game identity changed; refused.'}
if(!$Reader -or $Reader.CommandLine -notlike "*$(Join-Path $ProjectRoot 'bridge\geometry_stream.py')*" -or $Reader.CommandLine -notmatch "--pid\s+$GameProcessId(\s|$)"){throw 'Project producer identity changed; refused.'}
Stop-Process -Id $ReaderProcessId -ErrorAction Stop
try {
    & python (Join-Path $ProjectRoot 'dev\diagnostics\check_renderer_v2.py') --prefix $LogPrefix
    if($LASTEXITCODE){throw 'Real UE fault check failed'}
} finally {
    & (Join-Path $PSScriptRoot 'start-bridge.ps1') -GamePid $GameProcessId -Background
}
