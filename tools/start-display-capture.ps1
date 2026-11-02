# Opt-in signed portable ETW observer. No installer, service, driver or input capture.
param([ValidateRange(10,90)][int]$Seconds=55)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Initialize-UEMWEnvironment
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$Tool=Join-Path $ProjectRoot 'local\bin\PresentMon-2.3.1-x64.exe'
$Expected='364e5d98d4d134bd54dd25c22ed2ca2f4883f8bc3ed6502bee0c151e3436d30c'
if(!(Test-Path -LiteralPath $Tool) -or (Get-FileHash -LiteralPath $Tool -Algorithm SHA256).Hash -ine $Expected){throw 'Pinned official portable PresentMon is missing or has a different hash. Nothing was installed.'}
$Signature=Get-AuthenticodeSignature -LiteralPath $Tool
if($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch '^CN=Intel Corporation,'){throw 'PresentMon publisher verification failed.'}
$Token='UEMW-display-'+[guid]::NewGuid().ToString('N')
$Csv=Join-Path $ProjectRoot 'logs\display-delivery.csv'
$Arguments=@('--process_name','Morrowind.exe','--process_name','UEMorrowind.exe','--session_name',$Token,'--timed',$Seconds,'--terminate_after_timed','--no_console_stats','--no_track_input','--qpc_time_ms','--output_file',"`"$Csv`"")
# Windows denied the ordinary ETW probe. UAC approves only this signed observer.
# The tool stops its own unique session after the bounded interval.
$Observer=Start-Process -FilePath $Tool -ArgumentList $Arguments -WorkingDirectory $ProjectRoot -Verb RunAs -WindowStyle Hidden -PassThru
@{pid=$Observer.Id;session=$Token;seconds=$Seconds;output=$Csv;sha256=$Expected;publisher=$Signature.SignerCertificate.Subject;no_input_capture=$true;no_pixels=$true}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $ProjectRoot 'logs\display-observer.json')
Write-Output "Signed display observer PID: $($Observer.Id); automatic stop after $Seconds seconds."
