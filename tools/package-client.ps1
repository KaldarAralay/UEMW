param([string]$EngineRoot)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$EngineRoot=Resolve-UEMWEngineRoot -EngineRoot $EngineRoot
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$UProject=Join-Path $ProjectRoot 'ue\UEMorrowind\UEMorrowind.uproject'
$UAT=Join-Path $EngineRoot 'Engine\Build\BatchFiles\RunUAT.bat'
$Compiler=Join-Path (Get-UEMWToolchain) 'bin\Hostx64\x64\cl.exe'
foreach($Required in @($UAT,$Compiler,(Join-Path $EngineRoot 'Engine\Binaries\Win64\UnrealEditor-Cmd.exe'))){if(!(Test-Path -LiteralPath $Required)){throw "Missing packaging prerequisite: $Required. Nothing was installed."}}
$Output=Join-Path $ProjectRoot 'local\client'
if(Get-CimInstance Win32_Process -Filter "Name='UEMorrowind.exe'" | Where-Object {$_.ExecutablePath -like "$Output\*"}){throw 'Close this project client before rebuilding. The running session was left untouched.'}
$BuildTemp=Join-Path $ProjectRoot 'local\build-temp'
New-Item -ItemType Directory -Force -Path $Output,$BuildTemp,(Join-Path $ProjectRoot 'logs')|Out-Null
$PreviousTemp=$env:TEMP;$PreviousTmp=$env:TMP
try {
 $env:TEMP=$BuildTemp;$env:TMP=$BuildTemp
 & (Join-Path $PSScriptRoot 'build-read-batch.ps1') *> (Join-Path $ProjectRoot 'logs\native-read-batch-build.log')
 if($LASTEXITCODE){throw 'External x64 read-batch prerequisite failed.'}
 & (Join-Path $PSScriptRoot 'build-native-startup.ps1') *> (Join-Path $ProjectRoot 'logs\native-startup-build.log')
 if($LASTEXITCODE){throw 'Native Steam startup bootstrap build failed.'}
 # The installed editor is a build dependency only. The resulting game client
 # runs independently and contains cooked project-owned shader assets.
 & (Join-Path $PSScriptRoot 'build.ps1') -EngineRoot $EngineRoot
 if($LASTEXITCODE){throw 'Editor build prerequisite failed.'}
 $MaterialScript=Join-Path $PSScriptRoot 'build_materials.py'
 $MaterialInputs=@($MaterialScript)+@(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'shaders') -Filter '*.hlsl' | Sort-Object Name | ForEach-Object {$_.FullName})
 $MaterialDigest=(@($MaterialInputs|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash}) -join ':')
 $MaterialStamp=Join-Path $BuildTemp 'materials.sha256'
 $MaterialFiles=@('Opaque','Masked','Foliage','Translucent','Additive','Premultiplied','Modulate','Water','Terrain','Hair','Glass')|ForEach-Object{'MW_'+$_;'MW_'+$_+'_Skin'}
 $MaterialFiles+=@('Opaque','Masked','Foliage','Translucent','Additive','Premultiplied','Modulate','Hair','Glass')|ForEach-Object{'MW_'+$_+'_Env';'MW_'+$_+'_Env_Skin'}
 $MaterialFiles+=@('MW_WaterFog','MW_NeutralDetail','MW_TerrainColorFallback','MW_TerrainDetailFallback')
 $MaterialFiles+='MW_AmbientProbe'
 $MaterialFiles+='MW_NativeAttenuation'
 $Missing=@($MaterialFiles|Where-Object {!(Test-Path -LiteralPath (Join-Path $ProjectRoot "ue\UEMorrowind\Content\UEMW\Materials\$_.uasset"))})
 if($Missing.Count -or !(Test-Path -LiteralPath $MaterialStamp) -or (Get-Content -LiteralPath $MaterialStamp -Raw).Trim() -ne $MaterialDigest){
  & (Join-Path $PSScriptRoot 'build-materials.ps1') -EngineRoot $EngineRoot *> (Join-Path $ProjectRoot 'logs\material-build-command.log')
  Set-Content -LiteralPath $MaterialStamp -Value $MaterialDigest
 }
 $ProbeScript=Join-Path $PSScriptRoot 'build_ambient_probe.py'
 $ProbeInputs=@($ProbeScript,(Join-Path $ProjectRoot 'ue\UEMorrowind\Source\UEMorrowind\MWBuildLibrary.cpp'),(Join-Path $ProjectRoot 'ue\UEMorrowind\Source\UEMorrowind\MWOutdoor.cpp'),(Join-Path $ProjectRoot 'ue\UEMorrowind\Source\UEMorrowind\MWOutdoor.h'))
 $ProbeDigest=(@($ProbeInputs|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash}) -join ':')
 $ProbeStamp=Join-Path $BuildTemp 'ambient-probe.sha256'
 if(!(Test-Path -LiteralPath (Join-Path $ProjectRoot 'ue\UEMorrowind\Content\UEMW\Materials\MW_OutdoorAmbientProbe.uasset')) -or !(Test-Path -LiteralPath (Join-Path $ProjectRoot 'ue\UEMorrowind\Content\UEMW\Materials\MW_InteriorAmbientProbe.uasset')) -or !(Test-Path -LiteralPath $ProbeStamp) -or (Get-Content -LiteralPath $ProbeStamp -Raw).Trim() -ne $ProbeDigest){
  & (Join-Path $EngineRoot 'Engine\Binaries\Win64\UnrealEditor-Cmd.exe') $UProject -EnablePlugins=PythonScriptPlugin -run=pythonscript "-script=$($ProbeScript.Replace('\','/'))" -unattended -nosplash -nullrhi -stdout "-abslog=$(Join-Path $ProjectRoot 'logs\ambient-probe-build.log')" *> (Join-Path $ProjectRoot 'logs\ambient-probe-build-command.log')
  if($LASTEXITCODE){throw 'Ambient probe build failed.'}
  Set-Content -LiteralPath $ProbeStamp -Value $ProbeDigest
 }
 & $UAT BuildCookRun "-project=$UProject" -noP4 -platform=Win64 -clientconfig=Development -build -cook -stage -pak -archive "-archivedirectory=$Output" -map=/Engine/Maps/Entry -SkipCookingEditorContent -NoDebugInfo -unattended -utf8output 2>&1 | Tee-Object -FilePath (Join-Path $ProjectRoot 'logs\client-package.log')
 if($LASTEXITCODE){throw "Client packaging failed: $LASTEXITCODE"}
 $ShaderFailures=Select-String -LiteralPath (Join-Path $ProjectRoot 'logs\client-package.log') -Pattern 'Failed to compile Material|Failed to compile global shader|error X[0-9]+|/Engine/Generated/Material.*error:'
 if($ShaderFailures){throw 'Packaging produced fallback/failed shaders; this is not a usable client build. See logs/client-package.log.'}
 $Exe=Join-Path $Output 'Windows\UEMorrowind\Binaries\Win64\UEMorrowind.exe'
 if(!(Test-Path -LiteralPath $Exe)){throw 'Packaged runtime executable was not produced.'}
 $Pak=Join-Path $Output 'Windows\UEMorrowind\Content\Paks\UEMorrowind-Windows.pak'
 $SourceFiles=@(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'ue\UEMorrowind\Source') -Recurse -File)+@(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'ue\UEMorrowind\Config') -File)+@(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'bridge') -Filter '*.py' -File)+@(Get-Item -LiteralPath (Join-Path $ProjectRoot 'native\read_batch.cpp'))+@($MaterialInputs|ForEach-Object{Get-Item -LiteralPath $_})
 $Sources=@($SourceFiles | Sort-Object FullName -Unique | ForEach-Object { [pscustomobject]@{path=[IO.Path]::GetRelativePath($ProjectRoot,$_.FullName);sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash} })
 $Sources+=@(Get-Item -LiteralPath $ProbeScript | ForEach-Object {[pscustomobject]@{path=[IO.Path]::GetRelativePath($ProjectRoot,$_.FullName);sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}})
 @{version=1;built_utc=[datetime]::UtcNow.ToString('o');configuration='Development';rhi='d3d11';launcher_route='steam-managed-private-bootstrap';native_startup_manifest='local/bin/native-startup-build.json';native_startup_exe_sha256=(Get-FileHash -LiteralPath (Join-Path $ProjectRoot 'local\bin\uemw-game-start.exe')).Hash;launcher_rhi_thread=$false;camera_preparation='separate-process';producer_requested_hz=60;native_material_capture='prepared read-many identity-fenced';read_batch_abi=1;read_batch_sha256=(Get-FileHash -LiteralPath (Join-Path $ProjectRoot 'local\bin\read-batch.dll') -Algorithm SHA256).Hash;transport=5;shared_channel=1;state_metadata_version=1;geometry=6;binary_formats=@('UFB1','UFB2','UFB3');native_attributes=1;mesh_format=3;environment=1;material_frames=1;material_values=1;scene_preparation='async';executable_sha256=(Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash;pak_sha256=(Get-FileHash -LiteralPath $Pak -Algorithm SHA256).Hash;sources=$Sources} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Output 'build-info.json') -Encoding utf8
 Write-Output "Packaged runtime: $Exe"
}finally{$env:TEMP=$PreviousTemp;$env:TMP=$PreviousTmp}
