param([switch]$Renderer,[switch]$Repository)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment -Development
$Python=Get-UEMWPython
& $Python (Join-Path $PSScriptRoot 'run_tests.py')
if($LASTEXITCODE){throw 'Python tests failed.'}
if($Repository){& $Python (Join-Path $PSScriptRoot 'audit_repository.py');if($LASTEXITCODE){throw 'Repository audit failed.'}}
if($Renderer){& (Join-Path $PSScriptRoot 'test-client-headless.ps1')}
