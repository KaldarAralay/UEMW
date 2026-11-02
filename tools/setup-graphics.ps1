$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
$ProjectRoot=Get-UEMWRoot
$Private=Join-Path $ProjectRoot 'local\Morrowind'
$Tag='v1.9.8700.25'
$Digest='5584B75342C04DC53C1A8E6BF15B1B0BD044398E86959F7D2E1973FCFA2431F4'
$Files=@{'d3d8.dll'='B8B878E29C2931D6A8D064665C4C93EDB28A0105152E7247F8F543C1603985C3';'dxwrapper.dll'='23A2889E0785A02F17F1EE764254BF22B937FC5BDC6ED6374201A9F50CC7B43D'}
$Valid=Test-Path -LiteralPath (Join-Path $Private 'dxwrapper.ini')
foreach($Name in $Files.Keys){$Path=Join-Path $Private $Name;$Valid=$Valid -and (Test-Path -LiteralPath $Path) -and (Get-FileHash -LiteralPath $Path).Hash -ieq $Files[$Name]}
if($Valid){Write-Output 'Verified pinned private graphics DLLs reused; private graphics preferences retained.';return}
$Exe=Join-Path $Private 'Morrowind.exe'
if(!(Test-Path -LiteralPath $Exe)){throw 'Prepare the private game before its graphics wrapper.'}
if(Get-CimInstance Win32_Process -Filter "Name='Morrowind.exe'" | Where-Object {$_.ExecutablePath -ieq $Exe}){throw 'Close this private game before changing its graphics DLLs. Other installations were not touched.'}
$Zip=Join-Path $ProjectRoot "third_party\dx8.games-$Tag.zip";$Package=Join-Path $ProjectRoot "third_party\dxwrapper-$Tag"
New-Item -ItemType Directory -Force -Path (Split-Path $Zip),(Join-Path $ProjectRoot 'logs') | Out-Null
if(!(Test-Path -LiteralPath $Zip)){
    Invoke-WebRequest -Uri "https://github.com/elishacloud/dxwrapper/releases/download/$Tag/dx8.games.zip" -OutFile "$Zip.download"
    if((Get-FileHash -LiteralPath "$Zip.download").Hash -ine $Digest){throw 'Downloaded graphics wrapper failed SHA256 verification; it was not loaded.'}
    Move-Item -LiteralPath "$Zip.download" -Destination $Zip
}
if((Get-FileHash -LiteralPath $Zip).Hash -ine $Digest){throw 'Cached graphics wrapper failed SHA256 verification.'}
Expand-Archive -LiteralPath $Zip -DestinationPath $Package -Force
foreach($Name in @('d3d8.dll','dxwrapper.dll','License.txt')){Copy-Item -LiteralPath (Join-Path $Package $Name) -Destination (Join-Path $Private $Name)}
if(!(Test-Path -LiteralPath (Join-Path $Private 'dxwrapper.ini'))){Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'dxwrapper.ini') -Destination (Join-Path $Private 'dxwrapper.ini')}
@{version=1;tag=$Tag;sha256=$Digest;source="https://github.com/elishacloud/dxwrapper/releases/tag/$Tag"}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $ProjectRoot 'logs\dxwrapper-provenance.json')
Write-Output 'Pinned graphics compatibility DLLs installed only in the private copy.'
