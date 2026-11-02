param([switch]$IncludeTests)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$UemwSdk=Get-UEMWWindowsSDK
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$Compiler=Get-UEMWToolchain
$SDK=$UemwSdk.root
$SDKVersion=$UemwSdk.version
$Cl=Join-Path $Compiler 'bin\Hostx64\x86\cl.exe'
foreach($Required in @($Cl,(Join-Path $SDK "Lib\$SDKVersion\um\x86\dbghelp.lib"))){
    if(!(Test-Path -LiteralPath $Required)){throw "Missing diagnostic-build prerequisite: $Required. Nothing was installed."}
}
$Output=Join-Path $ProjectRoot 'local\bin'
New-Item -ItemType Directory -Force -Path $Output | Out-Null
$PreviousPath=$env:PATH
try {
    $env:PATH=(Join-Path $Compiler 'bin\Hostx64\x86')+';'+$env:PATH
    $Common=@('/nologo','/std:c++17','/EHsc','/W4','/O2','/MT','/DUNICODE','/D_UNICODE',"/I$Compiler\include","/I$SDK\Include\$SDKVersion\ucrt","/I$SDK\Include\$SDKVersion\shared","/I$SDK\Include\$SDKVersion\um")
    $Libraries=@("/LIBPATH:$Compiler\lib\x86","/LIBPATH:$SDK\Lib\$SDKVersion\ucrt\x86","/LIBPATH:$SDK\Lib\$SDKVersion\um\x86",'kernel32.lib','bcrypt.lib','dbghelp.lib')
    & $Cl @Common (Join-Path $ProjectRoot 'native\crash_watchdog.cpp') "/Fo$Output\crash-watchdog.obj" "/Fe$Output\crash-watchdog.exe" /link @Libraries
    if($LASTEXITCODE){throw 'Diagnostic helper build failed'}
    if($IncludeTests){
        $TestOutput=Join-Path $ProjectRoot 'local\diagnostics-tests'
        New-Item -ItemType Directory -Force -Path $TestOutput | Out-Null
        & $Cl @Common '/DUEMW_WATCHDOG_TEST_ONLY' (Join-Path $ProjectRoot 'native\crash_watchdog.cpp') "/Fo$Output\watchdog-test.obj" "/Fe$Output\watchdog-test.exe" /link @Libraries
        if($LASTEXITCODE){throw 'Diagnostic test helper build failed'}
        & $Cl @Common (Join-Path $ProjectRoot 'native\crash_test_target.cpp') "/Fo$TestOutput\crash-target.obj" "/Fe$TestOutput\crash-target.exe" /link @Libraries
        if($LASTEXITCODE){throw 'Crash target build failed'}
    }
} finally {$env:PATH=$PreviousPath}
Write-Output 'Built x86 crash diagnostic helper locally; no installed files or registry settings changed.'
