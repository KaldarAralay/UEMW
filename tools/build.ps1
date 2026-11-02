param([string]$EngineRoot)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$EngineRoot=Resolve-UEMWEngineRoot -EngineRoot $EngineRoot
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$UProject=Join-Path $ProjectRoot 'ue\UEMorrowind\UEMorrowind.uproject'
$BuildTemp=Join-Path $ProjectRoot 'local\build-temp'
New-Item -ItemType Directory -Force -Path $BuildTemp | Out-Null
$PreviousTemp=$env:TEMP
$PreviousTmp=$env:TMP
try {
    $env:TEMP=$BuildTemp
    $env:TMP=$BuildTemp
    # Re-gather the UE build environment instead of retaining stale temporary
    # paths in cached makefiles. All project build temporaries stay local.
    & (Join-Path $EngineRoot 'Engine\Build\BatchFiles\Build.bat') UEMorrowindEditor Win64 Development "-Project=$UProject" -NoUBTMakefiles -WaitMutex -NoHotReloadFromIDE "-log=$(Join-Path $ProjectRoot 'logs\ue-build.log')"
    if($LASTEXITCODE){throw "UE build failed: $LASTEXITCODE"}
} finally {
    $env:TEMP=$PreviousTemp
    $env:TMP=$PreviousTmp
}
