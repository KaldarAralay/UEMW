param([string]$EngineRoot)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$EngineRoot=Resolve-UEMWEngineRoot -EngineRoot $EngineRoot
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$Editor=Join-Path $EngineRoot 'Engine\Binaries\Win64\UnrealEditor-Cmd.exe'
if(!(Test-Path -LiteralPath $Editor)){throw "Missing material build prerequisite: $Editor"}
# UE's quoted Python commandlet argument interprets backslash escapes.
$ScriptPath=(Join-Path $PSScriptRoot 'build_materials.py').Replace('\','/')
& $Editor (Join-Path $ProjectRoot 'ue\UEMorrowind\UEMorrowind.uproject') -EnablePlugins=PythonScriptPlugin -run=pythonscript "-script=$ScriptPath" -unattended -nosplash -nullrhi -stdout -FullStdOutLogOutput "-abslog=$(Join-Path $ProjectRoot 'logs\material-build.log')"
if($LASTEXITCODE){throw "Material build failed: $LASTEXITCODE"}
