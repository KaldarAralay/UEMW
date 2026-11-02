param([string]$GameRoot,[string]$EngineRoot,[string]$SteamExe,[string]$PythonPath,[string]$ToolchainRoot,[string]$SdkRoot,[string]$SdkVersion,[switch]$Json)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
$Report=Get-UEMWPrerequisites -GameRoot $GameRoot -EngineRoot $EngineRoot -SteamExe $SteamExe -PythonPath $PythonPath -ToolchainRoot $ToolchainRoot -SdkRoot $SdkRoot -SdkVersion $SdkVersion
if($Json){$Report|ConvertTo-Json -Depth 5}else{
    foreach($Pair in $Report.checks.GetEnumerator()){Write-Output ('{0}: {1}' -f $Pair.Key,$Pair.Value)}
    foreach($Pair in $Report.paths.GetEnumerator()){Write-Output ('{0}: {1}' -f $Pair.Key,$Pair.Value)}
    $Report.errors|ForEach-Object {Write-Output $_}
}
if(!$Report.passed){throw 'Missing/unsupported prerequisites. Nothing was installed or configured. See docs/SETUP.md.'}
