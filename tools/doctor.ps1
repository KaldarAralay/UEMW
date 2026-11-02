param([switch]$DependenciesOnly,[switch]$Json)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$Report=Get-UEMWPrerequisites
if(!$DependenciesOnly -and $Report.passed){
    foreach($Name in @('python_environment','private_game','packaged_client','steam_startup')){
        try {
            switch($Name){
                python_environment {
                    $Python=Join-Path (Get-UEMWRoot) 'local\venv\Scripts\python.exe'
                    if(!(Test-Path -LiteralPath $Python)){throw 'Project Python environment is missing. Run Setup-UEMW.cmd.'}
                    & $Python -c 'import numpy,PIL,struct;assert struct.calcsize("P")==8'
                    if($LASTEXITCODE){throw 'Project Python packages are missing. Run Setup-UEMW.cmd.'}
                }
                private_game {
                    $Path=Join-Path (Get-UEMWRoot) 'local\Morrowind\Morrowind.exe'
                    if(!(Test-Path -LiteralPath $Path) -or (Get-FileHash -LiteralPath $Path).Hash -ine 'EAC72E1B3524EE0012D080D3C2E2E00E401464E41EE54F9AFD6AAAADF2C221F5'){throw 'Supported private game is missing. Run Setup-UEMW.cmd.'}
                }
                packaged_client {. (Join-Path $PSScriptRoot 'client-path.ps1');Test-UEMWClientPackage -ProjectRoot (Get-UEMWRoot)}
                steam_startup {. (Join-Path $PSScriptRoot 'native-startup.ps1');$null=Get-UEMWSteamStartup -ProjectRoot (Get-UEMWRoot)}
            }
            $Report.checks[$Name]=$true
        }catch{$Report.checks[$Name]=$false;$Report.errors+=$_.Exception.Message}
    }
}
$Report.passed=!($Report.checks.Values -contains $false)
if($Json){$Report|ConvertTo-Json -Depth 6}else{
    foreach($Pair in $Report.checks.GetEnumerator()){Write-Output ('{0}: {1}' -f $Pair.Key,$Pair.Value)}
    foreach($Pair in $Report.paths.GetEnumerator()){Write-Output ('{0}: {1}' -f $Pair.Key,$Pair.Value)}
    $Report.errors|ForEach-Object {Write-Output $_}
    Write-Output $(if($Report.passed){'Checks passed.'}else{'Checks failed. See docs/SETUP.md and docs/TROUBLESHOOTING.md.'})
}
if(!$Report.passed){exit 1}
