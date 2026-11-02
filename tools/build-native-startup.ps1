$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$UemwSdk=Get-UEMWWindowsSDK
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$Compiler=Get-UEMWToolchain
$SDK=$UemwSdk.root;$SDKVersion=$UemwSdk.version
$Cl=Join-Path $Compiler 'bin\Hostx64\x64\cl.exe'
foreach($File in @($Cl,(Join-Path $SDK "Lib\$SDKVersion\um\x64\bcrypt.lib"))){if(!(Test-Path -LiteralPath $File)){throw "Missing native startup build prerequisite: $File. Nothing was installed."}}
$Output=Join-Path $ProjectRoot 'local\bin';New-Item -ItemType Directory -Force -Path $Output | Out-Null
$OldPath=$env:PATH
try {
 $env:PATH=(Join-Path $Compiler 'bin\Hostx64\x64')+';'+$env:PATH
 $Source=Join-Path $ProjectRoot 'native\game_start.cpp';$Exe=Join-Path $Output 'uemw-game-start.exe'
 & $Cl /nologo /std:c++17 /EHsc /W4 /O2 /MT /DUNICODE /D_UNICODE "/I$Compiler\include" "/I$SDK\Include\$SDKVersion\ucrt" "/I$SDK\Include\$SDKVersion\shared" "/I$SDK\Include\$SDKVersion\um" $Source "/Fo$Output\game-start.obj" "/Fe$Exe" /link /SUBSYSTEM:WINDOWS "/LIBPATH:$Compiler\lib\x64" "/LIBPATH:$SDK\Lib\$SDKVersion\ucrt\x64" "/LIBPATH:$SDK\Lib\$SDKVersion\um\x64" kernel32.lib user32.lib bcrypt.lib
 if($LASTEXITCODE){throw 'Native startup build failed'}
 @{version=1;built_utc=[datetime]::UtcNow.ToString('o');source_sha256=(Get-FileHash -LiteralPath $Source).Hash;exe_sha256=(Get-FileHash -LiteralPath $Exe).Hash}|ConvertTo-Json|Set-Content (Join-Path $Output 'native-startup-build.json')
}finally{$env:PATH=$OldPath}
Write-Output "Built private startup bootstrap: $Exe"
