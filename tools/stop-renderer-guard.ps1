$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$File=Join-Path $ProjectRoot 'local\bridge\renderer-guard.pid'
if(Test-Path -LiteralPath $File){
    $GuardId=[int](Get-Content -LiteralPath $File)
    $Guard=Get-CimInstance Win32_Process -Filter "ProcessId=$GuardId"
    if($Guard){
        if($Guard.CommandLine -notlike "*$(Join-Path $ProjectRoot 'bridge\renderer_guard.py')*"){
            Remove-Item -LiteralPath $File -Force
            Write-Output 'Discarded a stale cutoff PID record; the unrelated process was left untouched.'
            return
        }
        Stop-Process -Id $GuardId -ErrorAction Stop
    }
    Remove-Item -LiteralPath $File -Force -ErrorAction SilentlyContinue
}
