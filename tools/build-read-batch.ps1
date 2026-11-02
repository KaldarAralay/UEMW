param([switch]$AllowNewerCompiler)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$UemwSdk=Get-UEMWWindowsSDK
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$Compiler=Get-UEMWToolchain -AllowNewerCompiler:$AllowNewerCompiler
$SDK=$UemwSdk.root
$SDKVersion=$UemwSdk.version
$Cl=Join-Path $Compiler 'bin\Hostx64\x64\cl.exe'
$Source=Join-Path $ProjectRoot 'native\read_batch.cpp'
foreach($Required in @($Cl,$Source,(Join-Path $SDK "Lib\$SDKVersion\um\x64\kernel32.lib"))){if(!(Test-Path -LiteralPath $Required)){throw "Missing read-batch prerequisite: $Required. Nothing was installed."}}
$Output=Join-Path $ProjectRoot 'local\bin'
New-Item -ItemType Directory -Force -Path $Output | Out-Null
$Dll=Join-Path $Output 'read-batch.dll'
$Stamp=Join-Path $Output 'read-batch.json'
$SourceDigest=(Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash
$ScriptDigest=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
if((Test-Path -LiteralPath $Dll) -and (Test-Path -LiteralPath $Stamp)){
 try {
  $Cached=Get-Content -LiteralPath $Stamp -Raw|ConvertFrom-Json
  if($Cached.abi -eq 1 -and $Cached.architecture -eq 'x64' -and $Cached.source_sha256 -eq $SourceDigest -and $Cached.build_script_sha256 -eq $ScriptDigest -and $Cached.dll_sha256 -eq (Get-FileHash -LiteralPath $Dll -Algorithm SHA256).Hash){Write-Output 'Verified external read-batch helper reused.';return}
 }catch{Write-Verbose 'Read-batch manifest unavailable; rebuilding.'}
}
$PreviousPath=$env:PATH
try {
 $env:PATH=(Join-Path $Compiler 'bin\Hostx64\x64')+';'+$env:PATH
 & $Cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MT /LD /DUNICODE /D_UNICODE "/I$Compiler\include" "/I$SDK\Include\$SDKVersion\ucrt" "/I$SDK\Include\$SDKVersion\shared" "/I$SDK\Include\$SDKVersion\um" $Source "/Fo$Output\read-batch.obj" "/Fe$Dll" /link "/LIBPATH:$Compiler\lib\x64" "/LIBPATH:$SDK\Lib\$SDKVersion\ucrt\x64" "/LIBPATH:$SDK\Lib\$SDKVersion\um\x64" kernel32.lib
 if($LASTEXITCODE){throw 'External x64 read-batch build failed'}
 @{abi=1;architecture='x64';dll_sha256=(Get-FileHash -LiteralPath $Dll -Algorithm SHA256).Hash;source_sha256=$SourceDigest;build_script_sha256=$ScriptDigest}|ConvertTo-Json|Set-Content -LiteralPath $Stamp -Encoding utf8
 Write-Output "Built external read-only bridge helper: $Dll"
}finally{$env:PATH=$PreviousPath}
