$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment -Development
$Root=Get-UEMWRoot
$Failures=@()
Get-ChildItem -LiteralPath (Join-Path $Root 'tools') -Filter '*.ps1' | ForEach-Object {
    $Tokens=$null;$ParseErrors=$null
    [void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$Tokens,[ref]$ParseErrors)
    if($ParseErrors){$Failures+=@($ParseErrors | ForEach-Object {$_.ToString()})}
}
if($Failures){$Failures|Write-Output;throw 'PowerShell source parse failed.'}
$Fixture=Join-Path $Root ('local\test-temp\portable tools '+[guid]::NewGuid().ToString('N'))
if(![IO.Path]::GetFullPath($Fixture).StartsWith([IO.Path]::GetFullPath((Join-Path $Root 'local\test-temp'))+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Fixture path escaped the project.'}
New-Item -ItemType Directory -Force -Path $Fixture|Out-Null
$OriginalConfigFunction=(Get-Command Get-UEMWConfig).ScriptBlock
try {
    function Get-UEMWConfig {return @{}}
    $SteamFolder=Join-Path $Fixture 'Steam Client';$Library=Join-Path $Fixture 'Other drive library'
    $Game=Join-Path $Library 'steamapps\common\Morrowind GOTY'
    New-Item -ItemType Directory -Force -Path (Join-Path $SteamFolder 'steamapps'),$Game|Out-Null
    $SteamExe=Join-Path $SteamFolder 'steam.exe';Set-Content -LiteralPath $SteamExe -Value 'owned fixture'
    Set-Content -LiteralPath (Join-Path $Game 'Morrowind.exe') -Value 'owned fixture'
    Set-Content -LiteralPath (Join-Path $SteamFolder 'steamapps\libraryfolders.vdf') -Value ('"libraryfolders" { "0" { "path" "'+$Library.Replace('\','\\')+'" } }')
    Set-Content -LiteralPath (Join-Path $Library 'steamapps\appmanifest_22320.acf') -Value '"AppState" { "appid" "22320" "installdir" "Morrowind GOTY" }'
    if((Resolve-UEMWGameRoot -SteamExe $SteamExe) -ine $Game){throw 'Nondefault Steam-library discovery failed.'}
    $Compiler=Join-Path $Fixture 'VS BuildTools\VC\Tools\MSVC\14.34.31933'
    New-Item -ItemType Directory -Force -Path (Join-Path $Compiler 'bin\Hostx64\x64')|Out-Null
    Set-Content -LiteralPath (Join-Path $Compiler 'bin\Hostx64\x64\cl.exe') -Value 'owned fixture'
    if((Get-UEMWToolchain -ToolchainRoot $Compiler) -ine $Compiler){throw 'Nondefault compiler discovery failed.'}
    $Sdk=Join-Path $Fixture 'Other SDK';$Version='10.0.19041.0'
    foreach($Relative in @("Include\$Version\um\Windows.h","Include\$Version\ucrt\stdlib.h","Lib\$Version\um\x64\kernel32.lib","Lib\$Version\ucrt\x64\ucrt.lib")){
        $Path=Join-Path $Sdk $Relative;New-Item -ItemType Directory -Force -Path (Split-Path $Path)|Out-Null;Set-Content -LiteralPath $Path -Value 'owned fixture'
    }
    if((Get-UEMWWindowsSDK -SdkRoot $Sdk -SdkVersion $Version).version -ne $Version){throw 'Nondefault SDK discovery failed.'}
}finally{Set-Item -Path Function:Get-UEMWConfig -Value $OriginalConfigFunction}

$Script=Join-Path $Fixture 'owned worker.py';$Ready=Join-Path $Fixture 'worker ready.json'
Set-Content -LiteralPath $Script -Value @'
import json,os,sys,time
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps(dict(pid=os.getpid())))
time.sleep(20)
'@ -Encoding utf8
$Worker=$null
try {
    $Worker=Start-UEMWPythonProcess -Script $Script -ScriptArguments @("`"$Ready`"") -StandardError (Join-Path $Fixture 'worker.stderr.log')
    $Until=[datetime]::UtcNow.AddSeconds(5)
    while(!(Test-Path -LiteralPath $Ready) -and [datetime]::UtcNow -lt $Until){Start-Sleep -Milliseconds 25}
    $State=Get-Content -LiteralPath $Ready -Raw|ConvertFrom-Json
    if($State.pid -ne $Worker.Id){throw 'The venv redirector PID was recorded instead of the actual Python worker.'}
}finally{if($Worker -and !$Worker.HasExited){Stop-Process -Id $Worker.Id -ErrorAction SilentlyContinue}}
Write-Output 'PowerShell syntax, nondefault Steam/compiler/SDK paths, spaces and actual Python worker PID checks passed.'
