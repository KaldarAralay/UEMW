$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$UemwSdk=Get-UEMWWindowsSDK
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$Compiler=Get-UEMWToolchain
$SDK=$UemwSdk.root
$SDKVersion=$UemwSdk.version
$Cl=Join-Path $Compiler 'bin\Hostx64\x64\cl.exe'
foreach($Required in @($Cl,(Join-Path $SDK "Lib\$SDKVersion\um\x64\dbghelp.lib"))){if(!(Test-Path -LiteralPath $Required)){throw "Missing prerequisite: $Required. Nothing was installed."}}
$Output=Join-Path $ProjectRoot 'local\bin'
New-Item -ItemType Directory -Force -Path $Output | Out-Null
$PreviousPath=$env:PATH
try {
 $env:PATH=(Join-Path $Compiler 'bin\Hostx64\x64')+';'+$env:PATH
 & $Cl /nologo /std:c++17 /EHsc /W4 /O2 /MT /DUNICODE /D_UNICODE "/I$Compiler\include" "/I$SDK\Include\$SDKVersion\ucrt" "/I$SDK\Include\$SDKVersion\shared" "/I$SDK\Include\$SDKVersion\um" (Join-Path $ProjectRoot 'native\renderer_stacks.cpp') "/Fo$Output\renderer-stacks.obj" "/Fe$Output\renderer-stacks.exe" /link "/LIBPATH:$Compiler\lib\x64" "/LIBPATH:$SDK\Lib\$SDKVersion\ucrt\x64" "/LIBPATH:$SDK\Lib\$SDKVersion\um\x64" kernel32.lib dbghelp.lib
 if($LASTEXITCODE){throw 'UE diagnostic build failed'}
}finally{$env:PATH=$PreviousPath}
