$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$PrivateExe=Join-Path $ProjectRoot 'local\Morrowind\Morrowind.exe'
$ClientRoot=Join-Path $ProjectRoot 'local\client\'
$UProject=Join-Path $ProjectRoot 'ue\UEMorrowind\UEMorrowind.uproject'
$Owned=@(Get-CimInstance Win32_Process | Where-Object {
 ($_.Name -ieq 'Morrowind.exe' -and $_.ExecutablePath -ieq $PrivateExe) -or
 ($_.Name -ieq 'UEMorrowind.exe' -and $_.ExecutablePath -like "$ClientRoot*") -or
 ($_.Name -ieq 'UnrealEditor.exe' -and $_.CommandLine -like "*$UProject*" -and $_.CommandLine -match '(?i)(?:^|\s)-game(?:\s|$)') -or
 ($_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -like "*$(Join-Path $ProjectRoot 'bridge\')*")
})
# Close the exact private game first; no other game, editor or Python is touched.
foreach($Item in ($Owned | Sort-Object @{Expression={if($_.Name -ieq 'Morrowind.exe'){0}else{1}}})){
 Stop-Process -Id $Item.ProcessId -ErrorAction SilentlyContinue
 Write-Output "Stopped this project process: $($Item.Name) $($Item.ProcessId)"
}
Write-Output 'Project session stopped. Unsaved private game progress was discarded; saved files were not changed.'
