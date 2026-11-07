# Shared, project-local configuration. Dot-sourcing this file changes only
# the current process environment; it installs nothing and writes no files.
function Get-UEMWRoot { Split-Path -Parent $PSScriptRoot }

function Read-UEMWAtomicJson {
    param([Parameter(Mandatory)][string]$Path)
    # Atomic publishers must be able to replace the name while a reader keeps
    # its complete previous snapshot open. Never deny FILE_SHARE_DELETE.
    $JsonStream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    try {
        $JsonReader=[IO.StreamReader]::new($JsonStream)
        try {$JsonText=$JsonReader.ReadToEnd()}finally{$JsonReader.Dispose()}
    }finally{$JsonStream.Dispose()}
    return $JsonText|ConvertFrom-Json
}

function Get-UEMWAllocatorArgument {
    # UE 5.2.1's built-in mimalloc reduces the measured temporary-page cleanup
    # stall. Garbage collection and memory-trim callbacks remain enabled.
    $Allocator=if($env:UEMW_ALLOCATOR){$env:UEMW_ALLOCATOR}else{'mimalloc'}
    switch($Allocator){
        'binned3' {return '-binnedmalloc3'}
        'binned2' {return '-binnedmalloc2'}
        'mimalloc' {return '-mimalloc'}
        default {throw 'UEMW_ALLOCATOR must be binned2, binned3 or mimalloc. Nothing was started.'}
    }
}

function Get-UEMWConfig {
    param([string]$ProjectRoot=(Get-UEMWRoot))
    $Path=Join-Path $ProjectRoot 'local\config.json'
    if(!(Test-Path -LiteralPath $Path)){return @{}}
    $Config=Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable
    if($Config.version -ne 1){throw 'Unsupported local/config.json version. See docs/SETUP.md.'}
    return $Config
}

function Initialize-UEMWEnvironment {
    param([switch]$Development)
    $Root=Get-UEMWRoot
    $Venv=Join-Path $Root 'local\venv\Scripts'
    if(Test-Path -LiteralPath (Join-Path $Venv 'python.exe')){
        if(($env:PATH -split ';')[0] -ine $Venv){$env:PATH=$Venv+';'+$env:PATH}
    }
    $Config=Get-UEMWConfig
    if($Config.toolchain_root){$env:UEMW_COMPILER_VERSION=Split-Path -Leaf $Config.toolchain_root}
    if($Config.sdk_version){$env:UEMW_SDK_VERSION=$Config.sdk_version}
    if($Development){
        $env:PYTHONPATH=((Join-Path $Root 'bridge'),(Join-Path $Root 'dev\diagnostics'),(Join-Path $Root 'tools'),$env:PYTHONPATH | Where-Object {$_}) -join ';'
    }
}

function Resolve-UEMWEngineRoot {
    param([string]$EngineRoot)
    if($EngineRoot){return [IO.Path]::GetFullPath($EngineRoot)}
    $Config=Get-UEMWConfig
    if($Config.engine_root){return $Config.engine_root}
    $Candidates=@()
    $Manifest=Join-Path $env:ProgramData 'Epic\UnrealEngineLauncher\LauncherInstalled.dat'
    if(Test-Path -LiteralPath $Manifest){
        try{$Candidates+=@((Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json).InstallationList | Where-Object {$_.AppName -eq 'UE_5.2'} | ForEach-Object {$_.InstallLocation})}catch{}
    }
    foreach($Key in @('HKLM:\SOFTWARE\EpicGames\Unreal Engine\5.2','HKLM:\SOFTWARE\WOW6432Node\EpicGames\Unreal Engine\5.2')){
        if(Test-Path $Key){$Candidates+=(Get-ItemProperty $Key).InstalledDirectory}
    }
    $Candidates+=Join-Path $env:ProgramFiles 'Epic Games\UE_5.2'
    foreach($Candidate in $Candidates){if($Candidate -and (Test-Path -LiteralPath (Join-Path $Candidate 'Engine\Build\Build.version'))){return $Candidate}}
    throw 'Unreal Engine 5.2.1 was not found. Install it in Epic Games Launcher or pass -EngineRoot. See docs/SETUP.md.'
}

function Get-UEMWSteamExe {
    param([string]$SteamExe)
    if($SteamExe){return [IO.Path]::GetFullPath($SteamExe)}
    $Config=Get-UEMWConfig
    if($Config.steam_exe){return $Config.steam_exe}
    $Key=Get-ItemProperty 'HKCU:\Software\Valve\Steam' -ErrorAction SilentlyContinue
    if($Key.SteamPath){return Join-Path $Key.SteamPath 'steam.exe'}
    throw 'Steam was not found for this Windows account. Install/sign in to Steam or pass -SteamExe.'
}

function Resolve-UEMWGameRoot {
    param([string]$GameRoot,[string]$SteamExe)
    if($GameRoot){return [IO.Path]::GetFullPath($GameRoot)}
    $Config=Get-UEMWConfig
    if($Config.game_root){return $Config.game_root}
    $Steam=Split-Path (Get-UEMWSteamExe -SteamExe $SteamExe)
    $Libraries=@($Steam);$Vdf=Join-Path $Steam 'steamapps\libraryfolders.vdf'
    if(Test-Path -LiteralPath $Vdf){
        $Text=Get-Content -LiteralPath $Vdf -Raw
        foreach($Match in [regex]::Matches($Text,'"path"\s+"((?:[^"\\]|\\.)*)"')){
            $Libraries+=$Match.Groups[1].Value.Replace('\\','\').Replace('\"','"')
        }
    }
    foreach($Library in ($Libraries | Select-Object -Unique)){
        $App=Join-Path $Library 'steamapps\appmanifest_22320.acf'
        if(!(Test-Path -LiteralPath $App)){continue}
        $Match=[regex]::Match((Get-Content -LiteralPath $App -Raw),'"installdir"\s+"([^"\\]+)"')
        if($Match.Success){$Candidate=Join-Path $Library ('steamapps\common\'+$Match.Groups[1].Value);if(Test-Path -LiteralPath (Join-Path $Candidate 'Morrowind.exe')){return $Candidate}}
    }
    throw 'Steam Morrowind (app 22320) was not found. Install GOTY or pass -GameRoot, including for nondefault Steam libraries.'
}

function Get-UEMWToolchain {
    param([string]$ToolchainRoot,[switch]$AllowNewerCompiler)
    $Config=Get-UEMWConfig
    if(!$ToolchainRoot -and $Config.toolchain_root){$ToolchainRoot=$Config.toolchain_root}
    $Candidates=@()
    if($ToolchainRoot){$Candidates=@(Get-Item -LiteralPath $ToolchainRoot -ErrorAction Stop)}else{
        $VsWhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
        if(!(Test-Path -LiteralPath $VsWhere)){throw 'Visual Studio 2022 C++ tools were not found. See docs/SETUP.md.'}
        $Installations=(& $VsWhere -products '*' -version '[17.0,18.0)' -format json | ConvertFrom-Json)
        foreach($Install in $Installations){$Candidates+=@(Get-ChildItem -LiteralPath (Join-Path $Install.installationPath 'VC\Tools\MSVC') -Directory -ErrorAction SilentlyContinue)}
    }
    $Candidates=@($Candidates | Where-Object {$_.Name -match '^14\.\d+\.\d+$' -and ($AllowNewerCompiler -or $_.Name -like '14.34.*')} | Sort-Object {[version]$_.Name} -Descending)
    foreach($Candidate in $Candidates){if(Test-Path -LiteralPath (Join-Path $Candidate.FullName 'bin\Hostx64\x64\cl.exe')){return $Candidate.FullName}}
    throw 'MSVC v143 14.34 (VS 2022 17.4 x64/x86 component) is required for UE 5.2.1. Newer toolsets alone do not satisfy this build. See docs/SETUP.md.'
}

function Get-UEMWWindowsSDK {
    param([string]$SdkRoot,[string]$SdkVersion)
    $Config=Get-UEMWConfig
    if(!$SdkRoot){$SdkRoot=$Config.sdk_root}
    if(!$SdkVersion){$SdkVersion=$Config.sdk_version}
    if(!$SdkRoot){$SdkRoot=(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots' -ErrorAction SilentlyContinue).KitsRoot10}
    if(!$SdkRoot){$SdkRoot=Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10'}
    $Versions=if($SdkVersion){@($SdkVersion)}else{@('10.0.26100.0','10.0.22621.0','10.0.19041.0')}
    foreach($Version in $Versions){
        $Required=@("Include\$Version\um\Windows.h","Include\$Version\ucrt\stdlib.h","Lib\$Version\um\x64\kernel32.lib","Lib\$Version\ucrt\x64\ucrt.lib")
        if(!@($Required | Where-Object {!(Test-Path -LiteralPath (Join-Path $SdkRoot $_))}).Count){return @{root=$SdkRoot;version=$Version}}
    }
    throw 'Windows SDK 10.0.26100.0, 10.0.22621.0 or 10.0.19041.0 was not found. See docs/SETUP.md or pass -SdkRoot and -SdkVersion.'
}

function Get-UEMWPython {
    param([string]$PythonPath,[switch]$Base)
    $Config=Get-UEMWConfig;$Candidates=@()
    if($PythonPath){$Candidates+=$PythonPath}
    if(!$Base){$Candidates+=Join-Path (Get-UEMWRoot) 'local\venv\Scripts\python.exe'}
    if($Config.python_base){$Candidates+=$Config.python_base}
    $Launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($Launcher){$Resolved=& $Launcher.Source -3.12 -c 'import sys;print(sys.executable)' 2>$null;if($LASTEXITCODE -eq 0){$Candidates+=($Resolved | Select-Object -Last 1)}}
    $Command=Get-Command python.exe -ErrorAction SilentlyContinue
    if($Command -and $Command.Source -notlike '*\Microsoft\WindowsApps\*'){$Candidates+=$Command.Source}
    $Candidates+=Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    foreach($Candidate in ($Candidates | Select-Object -Unique)){
        if(!$Candidate -or !(Test-Path -LiteralPath $Candidate)){continue}
        $Probe=& $Candidate -c 'import sys,struct;print("ok" if sys.implementation.name=="cpython" and sys.version_info[:2]==(3,12) and struct.calcsize("P")==8 else "unsupported")' 2>$null
        if($LASTEXITCODE -eq 0 -and $Probe -contains 'ok'){return [IO.Path]::GetFullPath($Candidate)}
    }
    throw '64-bit Python 3.12 was not found. Install it from python.org or pass -PythonPath. The Microsoft Store alias is not an interpreter.'
}

function Get-UEMWPrerequisites {
    param([string]$GameRoot,[string]$EngineRoot,[string]$SteamExe,[string]$PythonPath,[string]$ToolchainRoot,[string]$SdkRoot,[string]$SdkVersion)
    $Result=[ordered]@{version=1;passed=$false;checks=[ordered]@{};paths=[ordered]@{};errors=@()}
    $Result.checks.windows_x64=$IsWindows -and [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -eq [System.Runtime.InteropServices.Architecture]::X64
    $Result.checks.powershell7=$PSVersionTable.PSVersion.Major -ge 7
    foreach($Item in @('steam','game','engine','python','compiler','sdk')){
        try {
            switch($Item){
                steam {$Result.paths.steam_exe=Get-UEMWSteamExe -SteamExe $SteamExe;if(!(Test-Path -LiteralPath $Result.paths.steam_exe)){throw 'Steam executable is missing.'}}
                game {
                    $Path=Resolve-UEMWGameRoot -GameRoot $GameRoot -SteamExe $SteamExe;$Result.paths.game_root=$Path
                    $Required=@('Morrowind.exe','Morrowind.ini','binkw32.dll','Data Files\Morrowind.esm','Data Files\Tribunal.esm','Data Files\Bloodmoon.esm','Data Files\Morrowind.bsa','Data Files\Tribunal.bsa','Data Files\Bloodmoon.bsa')
                    foreach($File in $Required){if(!(Test-Path -LiteralPath (Join-Path $Path $File))){throw "Missing installed game file: $File"}}
                    if((Get-FileHash -LiteralPath (Join-Path $Path 'Morrowind.exe') -Algorithm SHA256).Hash -ine 'EAC72E1B3524EE0012D080D3C2E2E00E401464E41EE54F9AFD6AAAADF2C221F5'){throw 'Unsupported Morrowind executable. Only the documented unmodified Steam 1.6.1820 hash is supported.'}
                }
                engine {
                    $Path=Resolve-UEMWEngineRoot -EngineRoot $EngineRoot;$Result.paths.engine_root=$Path
                    $Version=Get-Content -LiteralPath (Join-Path $Path 'Engine\Build\Build.version') -Raw | ConvertFrom-Json
                    if($Version.MajorVersion -ne 5 -or $Version.MinorVersion -ne 2 -or $Version.PatchVersion -ne 1){throw 'This source targets UE 5.2.1. Other UE versions require a port and are not accepted silently.'}
                    foreach($File in @('Engine\Binaries\Win64\UnrealEditor-Cmd.exe','Engine\Build\BatchFiles\RunUAT.bat','Engine\Plugins\2D\Paper2D\Content\OpaqueUnlitSpriteMaterial.uasset')){if(!(Test-Path -LiteralPath (Join-Path $Path $File))){throw "Incomplete Unreal installation: $File"}}
                }
                python {$Result.paths.python_base=Get-UEMWPython -PythonPath $PythonPath -Base}
                compiler {$Result.paths.toolchain_root=Get-UEMWToolchain -ToolchainRoot $ToolchainRoot}
                sdk {$Sdk=Get-UEMWWindowsSDK -SdkRoot $SdkRoot -SdkVersion $SdkVersion;$Result.paths.sdk_root=$Sdk.root;$Result.paths.sdk_version=$Sdk.version}
            }
            $Result.checks[$Item]=$true
        }catch{$Result.checks[$Item]=$false;$Result.errors+=$_.Exception.Message}
    }
    $Result.passed=!($Result.checks.Values -contains $false)
    return $Result
}

function Start-UEMWPythonProcess {
    param([Parameter(Mandatory)][string]$Script,[string[]]$ScriptArguments=@(),[string]$WorkingDirectory=(Get-UEMWRoot),[string]$StandardOutput,[string]$StandardError)
    $Python=Get-UEMWPython
    # Windows venv's python.exe is a redirector. Start-Process returns that
    # waiting parent, while os.getpid()/IPC belongs to the base interpreter.
    # Resolve and verify the direct child instead of recording the wrong PID.
    $Image=(& $Python -c 'import sys;print(sys._base_executable)' | Select-Object -Last 1).Trim()
    if($LASTEXITCODE -or !(Test-Path -LiteralPath $Image)){throw 'Could not identify the project Python runtime.'}
    $SpawnParameters=@{FilePath=$Python;ArgumentList=(@('-u',"`"$Script`"")+$ScriptArguments);WorkingDirectory=$WorkingDirectory;WindowStyle='Hidden';PassThru=$true}
    if($StandardOutput){$SpawnParameters.RedirectStandardOutput=$StandardOutput}
    if($StandardError){$SpawnParameters.RedirectStandardError=$StandardError}
    $Requested=[datetime]::UtcNow;$Launcher=Start-Process @SpawnParameters
    if($Python -ieq $Image){return $Launcher}
    $Until=$Requested.AddSeconds(5)
    do {
        $Children=@(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($Launcher.Id)" | Where-Object {
            $_.ExecutablePath -ieq $Image -and $_.CommandLine.IndexOf($Script,[StringComparison]::OrdinalIgnoreCase) -ge 0 -and $_.CreationDate.ToUniversalTime() -ge $Requested.AddSeconds(-1)
        })
        if($Children.Count -eq 1){return Get-Process -Id $Children[0].ProcessId -ErrorAction Stop}
        if($Children.Count -gt 1){throw 'Ambiguous project Python child; launch refused.'}
        if($Launcher.HasExited){break}
        Start-Sleep -Milliseconds 50
    }while([datetime]::UtcNow -lt $Until)
    throw "Project Python did not initialize for $Script. Check its diagnostic log; the original game was left running."
}
