param([ValidateSet('copy','flip')][string]$Mode='flip')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$Private=Join-Path $ProjectRoot 'local\Morrowind'
$Exe=Join-Path $Private 'Morrowind.exe'
if((Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash -ine 'EAC72E1B3524EE0012D080D3C2E2E00E401464E41EE54F9AFD6AAAADF2C221F5'){throw 'Unsupported private executable.'}
if(Get-Process -Name Morrowind -ErrorAction SilentlyContinue){throw 'Close the private game before changing its presentation mode.'}
foreach($Name in @('d3d8.dll','dxwrapper.dll')){
    $Expected=Join-Path $ProjectRoot "third_party\dxwrapper-v1.9.8700.25\$Name"
    if(!(Test-Path -LiteralPath $Expected) -or (Get-FileHash -LiteralPath (Join-Path $Private $Name)).Hash -ne (Get-FileHash -LiteralPath $Expected).Hash){throw 'Private wrapper differs from the existing pinned package.'}
}
$Ini=Join-Path $Private 'dxwrapper.ini'
$Backup=Join-Path $Private 'dxwrapper.before-flip.ini'
if(!(Test-Path -LiteralPath $Backup)){Copy-Item -LiteralPath $Ini -Destination $Backup}
$Before=(Get-FileHash -LiteralPath $Ini -Algorithm SHA256).Hash
$Text=[IO.File]::ReadAllText($Ini)
if([regex]::Matches($Text,'(?im)^D3d9to9Ex\s*=').Count -ne 1){throw 'Expected one private D3D9Ex setting.'}
$Value=if($Mode -eq 'flip'){'1'}else{'0'}
$Text=[regex]::Replace($Text,'(?im)^D3d9to9Ex\s*=.*$',"D3d9to9Ex=$Value")
if([regex]::Matches($Text,'(?im)^FlipEx\s*=').Count -gt 1){throw 'Ambiguous private FlipEx setting.'}
if($Text -match '(?im)^FlipEx\s*='){$Text=[regex]::Replace($Text,'(?im)^FlipEx\s*=.*$',"FlipEx=$Value")}
else{$Text=[regex]::Replace($Text,'(?im)^\[d3d9\]\s*$',"[d3d9]`r`nFlipEx=$Value")}
[IO.File]::WriteAllText($Ini,$Text,[Text.Encoding]::ASCII)
@{mode=$Mode;utc=[datetime]::UtcNow.ToString('o');path=$Ini;backup=$Backup;before_sha256=$Before;after_sha256=(Get-FileHash -LiteralPath $Ini -Algorithm SHA256).Hash;wrapper='v1.9.8700.25';gameplay_changes=$false}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $ProjectRoot "logs\private-presentation-$Mode.json")
Write-Output "Private native presentation: $Mode. Original executable, Steam installation and saves unchanged."
