function Get-UEMWSteamStartup {
    param([string]$ProjectRoot)
    $Bootstrap=Join-Path $ProjectRoot 'local\bin\uemw-game-start.exe'
    $Manifest=Join-Path $ProjectRoot 'local\bin\native-startup-build.json'
    if(!(Test-Path -LiteralPath $Bootstrap) -or !(Test-Path -LiteralPath $Manifest)){throw 'Native startup bootstrap is missing. Run tools/build-native-startup.ps1. Nothing was started.'}
    $Build=Get-Content -LiteralPath $Manifest -Raw|ConvertFrom-Json
    if((Get-FileHash -LiteralPath $Bootstrap).Hash -ine $Build.exe_sha256 -or (Get-FileHash -LiteralPath (Join-Path $ProjectRoot 'native\game_start.cpp')).Hash -ine $Build.source_sha256){throw 'Native startup bootstrap is stale or changed. Run tools/build-native-startup.ps1. Nothing was started.'}
    $Raw=& python (Join-Path $ProjectRoot 'bridge\steam_startup.py') --root $ProjectRoot
    $Code=$LASTEXITCODE;$Context=($Raw -join "`n")|ConvertFrom-Json
    if($Code -or $Context.error){throw "Steam private-startup prerequisite: $($Context.error). Nothing was started."}
    $Steam=@(Get-CimInstance Win32_Process -Filter "Name='steam.exe'"|Where-Object {$_.ExecutablePath -ieq $Context.steam_exe})
    if($Steam.Count -ne 1){throw 'Steam is not running at its registered path. Start Steam normally first. Nothing was started.'}
    $Context.steam_pid=$Steam[0].ProcessId
    return $Context
}

function Start-UEMWSteamPrivateGame {
    param([string]$ProjectRoot)
    $Context=Get-UEMWSteamStartup -ProjectRoot $ProjectRoot
    if(Get-Process -Name Morrowind -ErrorAction SilentlyContinue){throw 'Another Morrowind is already running; it was left untouched.'}
    $PrivateExe=Join-Path $ProjectRoot 'local\Morrowind\Morrowind.exe'
    $Requested=[datetime]::UtcNow;$ReportPath=Join-Path $ProjectRoot 'logs\native-startup.json'
    $Record=[ordered]@{version=4;route='steam-managed-private-bootstrap';game_id=$Context.game_id;requested_utc=$Requested.ToString('o');pid=$null;exited=$null;phase='waiting_for_steam';error=$null}
    $Record|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $ReportPath
    $Launch=[Diagnostics.ProcessStartInfo]::new();$Launch.FileName=$Context.steam_exe;$Launch.WorkingDirectory=Split-Path $Context.steam_exe
    $Launch.UseShellExecute=$false;$Launch.WindowStyle=[Diagnostics.ProcessWindowStyle]::Hidden;$Launch.ArgumentList.Add($Context.uri)
    $Relay=[Diagnostics.Process]::Start($Launch);$Relay.Dispose()
    $Until=$Requested.AddSeconds(20);$BootstrapReport=Join-Path $ProjectRoot 'logs\native-bootstrap.json'
    try {
        while([datetime]::UtcNow -lt $Until){
            $Games=@(Get-CimInstance Win32_Process -Filter "Name='Morrowind.exe'")
            # CIM can expose a newly created process before its image path.
            # Unknown identity waits within the same deadline; only a known
            # different path is an installed/non-private game.
            if($Games|Where-Object {$_.ExecutablePath -and $_.ExecutablePath -ine $PrivateExe}){throw 'An installed/non-private game started; it was not adopted.'}
            $Native=$null
            if((Test-Path -LiteralPath $BootstrapReport) -and (Get-Item -LiteralPath $BootstrapReport).LastWriteTimeUtc -ge $Requested){
                try {$Native=Get-Content -LiteralPath $BootstrapReport -Raw|ConvertFrom-Json}catch{}
            }
            if($Native){
                if($Native.error -or $Native.exited){throw "Private Steam bootstrap failed: $($Native.error) (native exit $($Native.exit_code))."}
                if($Games.Count -eq 1 -and $Games[0].ExecutablePath -ieq $PrivateExe -and $Games[0].ProcessId -eq $Native.pid -and $Games[0].ParentProcessId -eq $Native.bootstrap_pid -and $Games[0].CreationDate.ToUniversalTime() -ge $Requested){
                    $Process=Get-Process -Id $Native.pid -ErrorAction Stop
                    if(!$Process.WaitForExit(300)){
                        $Record.pid=$Native.pid;$Record.exited=$false;$Record.phase='private_game_running';$Record.bootstrap=$Native
                        $Record|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $ReportPath
                        return $Process
                    }
                    throw 'Private game exited immediately after the Steam bootstrap.'
                }
            }
            Start-Sleep -Milliseconds 100
        }
        throw 'Steam did not publish a new private game within 20 seconds. See logs/native-bootstrap.json and Steam.'
    }catch{
        $Record.phase='failed';$Record.error=$_.Exception.Message;$Record|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $ReportPath
        throw
    }
}
