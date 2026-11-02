param([string]$GameRoot,[string]$EngineRoot,[string]$SteamExe,[string]$PythonPath,[string]$ToolchainRoot,[string]$SdkRoot,[string]$SdkVersion,[switch]$CheckOnly,[switch]$SkipBuild)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
$Root=Get-UEMWRoot
Write-Output 'Checking all build prerequisites before making changes...'
$Report=Get-UEMWPrerequisites -GameRoot $GameRoot -EngineRoot $EngineRoot -SteamExe $SteamExe -PythonPath $PythonPath -ToolchainRoot $ToolchainRoot -SdkRoot $SdkRoot -SdkVersion $SdkVersion
foreach($Check in $Report.checks.GetEnumerator()){Write-Output ('{0}: {1}' -f $Check.Key,$Check.Value)}
foreach($Path in $Report.paths.GetEnumerator()){Write-Output ('{0}: {1}' -f $Path.Key,$Path.Value)}
if(!$Report.passed){$Report.errors | ForEach-Object {Write-Output $_};throw 'Prerequisites are missing or unsupported. No installation/configuration changes were made. See docs/SETUP.md.'}
if($CheckOnly){Write-Output 'Dependency check passed. No files, packages or application settings were changed.';return}
$Local=Join-Path $Root 'local';$Logs=Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $Local,$Logs | Out-Null
$Config=[ordered]@{version=1};foreach($Pair in $Report.paths.GetEnumerator()){$Config[$Pair.Key]=$Pair.Value}
$Config|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $Local 'config.json') -Encoding utf8
$Venv=Join-Path $Local 'venv';$Python=Join-Path $Venv 'Scripts\python.exe'
Write-Output 'Preparing the project-local Python environment...'
if(!(Test-Path -LiteralPath $Python)){& $Report.paths.python_base -m venv $Venv;if($LASTEXITCODE){throw 'Python virtual environment creation failed.'}}
& $Python -c 'import sys,struct;assert sys.implementation.name=="cpython" and sys.version_info[:2]==(3,12) and struct.calcsize("P")==8'
if($LASTEXITCODE){throw 'Existing local/venv is not CPython 3.12 x64. Move that environment aside and rerun setup; it was not overwritten.'}
& $Python -m pip install --disable-pip-version-check --only-binary=:all: -r (Join-Path $Root 'requirements.txt')
if($LASTEXITCODE){throw 'Project Python dependency installation failed. See the pip error above; system Python was not modified.'}
Initialize-UEMWEnvironment
Write-Output 'Preparing or verifying the private vanilla game copy...'
& (Join-Path $PSScriptRoot 'prepare.ps1') -GameRoot $Report.paths.game_root -EngineRoot $Report.paths.engine_root -SteamExe $Report.paths.steam_exe
if(!$SkipBuild){
    Write-Output 'Building helpers, generating materials and packaging UE. The first shader build can take several minutes. Log: logs/setup-build.log'
    try{& (Join-Path $PSScriptRoot 'package-client.ps1') -EngineRoot $Report.paths.engine_root *> (Join-Path $Logs 'setup-build.log')}
    catch{Get-Content -LiteralPath (Join-Path $Logs 'setup-build.log') -Tail 24;throw}
    Write-Output 'Running owned-data Python and packaged UE tests...'
    & $Python (Join-Path $PSScriptRoot 'run_tests.py') *> (Join-Path $Logs 'setup-python-tests.log')
    if($LASTEXITCODE){throw 'Python tests failed. See logs/setup-python-tests.log.'}
    & (Join-Path $PSScriptRoot 'test-client-headless.ps1') *> (Join-Path $Logs 'setup-renderer-tests.log')
}
Write-Output 'Checking the one-time Steam shortcut...'
$Context=& $Python (Join-Path $Root 'bridge\steam_startup.py') --root $Root
$SteamReady=$LASTEXITCODE -eq 0
@{version=1;dependencies=$true;built=(!$SkipBuild);steam_shortcut=$SteamReady;ready_to_launch=(!$SkipBuild -and $SteamReady)}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $Local 'setup-result.json')
if($SkipBuild){Write-Output 'Environment and private game prepared. Run Setup-UEMW.cmd without -SkipBuild to build and test the renderer.'}
elseif($SteamReady){Write-Output 'Setup complete. Keep Steam running and double-click Start-UEMW.cmd.'}
else{
    Write-Output "Build complete. In Steam, choose Add a Game > Add a Non-Steam Game > Browse, then add: $(Join-Path $Local 'bin\uemw-game-start.exe')"
    Write-Output 'Only add that bootstrap once. Then keep Steam running and use Start-UEMW.cmd. Doctor-UEMW.cmd verifies the shortcut. Setup does not edit your Steam library.'
}
