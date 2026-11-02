$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$ProjectRoot=Get-UEMWRoot;$Python=Get-UEMWPython
$Raw=& $Python (Join-Path $PSScriptRoot 'audit_repository.py') --list-json
if($LASTEXITCODE){$Raw|Write-Output;throw 'Publication audit failed; no source archive was written.'}
$Paths=($Raw -join "`n")|ConvertFrom-Json
$Destination=Join-Path $ProjectRoot 'local\distribution';New-Item -ItemType Directory -Force -Path $Destination|Out-Null
$Manifest=@($Paths|ForEach-Object{$File=Get-Item -LiteralPath (Join-Path $ProjectRoot $_);[pscustomobject]@{Path=$_;SHA256=(Get-FileHash -LiteralPath $File.FullName).Hash;Bytes=$File.Length}})
$Manifest|ConvertTo-Json -Depth 4|Set-Content -LiteralPath (Join-Path $Destination 'source-manifest.json') -Encoding utf8
Add-Type -AssemblyName System.IO.Compression
$ArchivePath=Join-Path $Destination 'UEMW-source.zip';$Stream=[IO.File]::Open($ArchivePath,[IO.FileMode]::Create)
try {
    $Archive=[IO.Compression.ZipArchive]::new($Stream,[IO.Compression.ZipArchiveMode]::Create,$true)
    try {
        foreach($Entry in $Manifest){[IO.Compression.ZipFileExtensions]::CreateEntryFromFile($Archive,(Join-Path $ProjectRoot $Entry.Path),$Entry.Path,[IO.Compression.CompressionLevel]::Optimal)|Out-Null}
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($Archive,(Join-Path $Destination 'source-manifest.json'),'source-manifest.json',[IO.Compression.CompressionLevel]::Optimal)|Out-Null
    }finally{$Archive.Dispose()}
}finally{$Stream.Dispose()}
Write-Output "Audited source only: $ArchivePath ($($Manifest.Count) files). No game/engine assets, saves, binaries, downloads or local diagnostic outputs."
