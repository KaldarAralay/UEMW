param([string]$LogPrefix='performance')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
if($LogPrefix -notmatch '^[a-z0-9-]{1,40}$'){throw 'Use a short lowercase log prefix'}
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$ZipPath=Join-Path $ProjectRoot 'local\distribution\UEMW-source.zip'
Add-Type -AssemblyName System.IO.Compression
$Archive=[IO.Compression.ZipFile]::OpenRead($ZipPath)
try {
    $Manifest=Get-Content -Raw -LiteralPath (Join-Path $ProjectRoot 'local\distribution\source-manifest.json') | ConvertFrom-Json
    $Failures=@()
    foreach($Item in $Manifest){
        $Entry=$Archive.GetEntry($Item.Path)
        if(!$Entry){$Failures+="Missing entry: $($Item.Path)";continue}
        $Stream=$Entry.Open()
        try {$Hash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Stream))}finally{$Stream.Dispose()}
        $DiskHash=(Get-FileHash -LiteralPath (Join-Path $ProjectRoot $Item.Path) -Algorithm SHA256).Hash
        if($Hash -ne $Item.SHA256 -or $Hash -ne $DiskHash){$Failures+="Hash mismatch: $($Item.Path)"}
    }
    $Forbidden=@($Archive.Entries | Where-Object {$_.FullName -match '(?i)\.(bsa|esm|esp|ess|nif|dds|png|mp4|mkv|exe|dll|obj|lib|exp|ilk|pdb|dmp|ttf|uasset|umap|umesh|uskin|pak|utrace|pth|pt|onnx|safetensors)$'})
    $Result=[pscustomobject]@{passed=($Failures.Count -eq 0 -and $Forbidden.Count -eq 0 -and $Archive.Entries.Count -eq ($Manifest.Count+1));source_files=$Manifest.Count;zip_sha256=(Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash;failures=$Failures;forbidden_entries=@($Forbidden|ForEach-Object {$_.FullName})}
    $Result|ConvertTo-Json -Depth 4|Set-Content -LiteralPath (Join-Path $ProjectRoot "logs\$LogPrefix-source-package-audit.json")
    $Result|ConvertTo-Json -Depth 4
    if(!$Result.passed){throw 'Source package audit failed'}
}finally{$Archive.Dispose()}
