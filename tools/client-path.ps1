function Get-UEMWRenderer {
 param([string]$ProjectRoot,[string]$EngineRoot,[switch]$Editor)
 if($Editor){return (Join-Path $EngineRoot 'Engine\Binaries\Win64\UnrealEditor.exe')}
 return (Join-Path $ProjectRoot 'local\client\Windows\UEMorrowind\Binaries\Win64\UEMorrowind.exe')
}
function Test-UEMWClientPackage {
 param([string]$ProjectRoot)
 $Folder=Join-Path $ProjectRoot 'local\client'
 $InfoPath=Join-Path $Folder 'build-info.json'
 if(!(Test-Path -LiteralPath $InfoPath)){throw 'No verified package manifest. Run tools/package-client.ps1. No game was started.'}
 $Info=Get-Content -LiteralPath $InfoPath -Raw|ConvertFrom-Json
 $Exe=Join-Path $Folder 'Windows\UEMorrowind\Binaries\Win64\UEMorrowind.exe'
 $Pak=Join-Path $Folder 'Windows\UEMorrowind\Content\Paks\UEMorrowind-Windows.pak'
 $ReadBatch=Join-Path $ProjectRoot 'local\bin\read-batch.dll'
 if(!(Test-Path -LiteralPath $Exe) -or !(Test-Path -LiteralPath $Pak) -or
    (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash -ine $Info.executable_sha256 -or
    (Get-FileHash -LiteralPath $Pak -Algorithm SHA256).Hash -ine $Info.pak_sha256){
  throw 'Package is incomplete or does not match its successful build manifest. Rebuild before launching. No game was started.'
 }
 if($Info.read_batch_abi -ne 1 -or !(Test-Path -LiteralPath $ReadBatch) -or (Get-FileHash -LiteralPath $ReadBatch -Algorithm SHA256).Hash -ine $Info.read_batch_sha256){
  throw 'External x64 read-batch helper is missing or differs from this package. Run tools/package-client.ps1. No game was started.'
 }
}
