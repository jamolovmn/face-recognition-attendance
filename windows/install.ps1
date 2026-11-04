#Requires -RunAsAdministrator
<#
  Installs the attendance service on Windows 10/11 as a scheduled task that
  starts at boot (no login needed) and restarts itself if it stops.

    powershell -ExecutionPolicy Bypass -File windows\install.ps1             # install / update
    powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Uninstall  # remove

  Put the project in a folder without spaces, e.g. C:\FaceAttendance
#>
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$TaskName = 'FaceAttendance'
Set-Location $Root

function Stop-Attendance {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    # Stopping the task ends run.cmd but not the python it started
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*attendance.main*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}

if ($Uninstall) {
    Stop-Attendance
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host 'FaceAttendance removed.' -ForegroundColor Green
    exit 0
}

function Find-Python {
    foreach ($p in @("$env:ProgramFiles\Python312\python.exe", "$env:ProgramFiles\Python313\python.exe")) {
        if (Test-Path $p) { return $p }
    }
    # Skip the Microsoft Store stub in WindowsApps
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*WindowsApps*' } | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    return $null
}

Write-Host '[1/5] Python' -ForegroundColor Cyan
$python = Find-Python
if (-not $python) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Python.Python.3.12 -e --scope machine --silent --accept-package-agreements --accept-source-agreements
        $python = Find-Python
    }
    if (-not $python) {
        throw 'Python not found. Install Python 3.12 from https://www.python.org/downloads/windows/ ("Install for all users"), then run this script again.'
    }
}
Write-Host "      $python"

Write-Host '[2/5] Libraries (a few minutes the first time)' -ForegroundColor Cyan
if (-not (Test-Path '.venv\Scripts\python.exe')) { & $python -m venv .venv }
$venv = Join-Path $Root '.venv\Scripts\python.exe'
& $venv -m pip install --quiet --upgrade pip
& $venv -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

Write-Host '[3/5] AI models' -ForegroundColor Cyan
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
New-Item -ItemType Directory -Force -Path models, data, faces | Out-Null
$models = @{
    'face_detection_yunet_2023mar.onnx'   = 'https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx'
    'face_recognition_sface_2021dec.onnx' = 'https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx'
}
foreach ($m in $models.GetEnumerator()) {
    $dst = Join-Path 'models' $m.Key
    if (-not (Test-Path $dst)) { Invoke-WebRequest -Uri $m.Value -OutFile $dst -UseBasicParsing }
}

Write-Host '[4/5] Settings (.env)' -ForegroundColor Cyan
# Explorer makes it awkward to name a file ".env", so a downloaded env.txt is accepted too
if (-not (Test-Path '.env') -and (Test-Path 'env.txt')) { Move-Item 'env.txt' '.env' }
if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    Write-Host '      .env created - fill it in, save, and run this script again.' -ForegroundColor Yellow
    Start-Process notepad.exe '.env' -Wait
    exit 1
}
$envText = Get-Content '.env' -Raw
if ($envText -match '(?m)^FAILOVER=(true|1|yes|on)\s*$') {
    $current = if ($envText -match '(?m)^NODE_PRIORITY=(\d+)') { $Matches[1] } else { '1' }
    $answer = Read-Host "      This PC: 1 = main, 2 = backup [$current]"
    if ($answer -match '^\d+$' -and $answer -ne $current) {
        if ($envText -match '(?m)^NODE_PRIORITY=') {
            $envText = $envText -replace '(?m)^NODE_PRIORITY=\d+', "NODE_PRIORITY=$answer"
        } else {
            $envText = $envText.TrimEnd() + "`r`nNODE_PRIORITY=$answer`r`n"
        }
        [IO.File]::WriteAllText((Join-Path $Root '.env'), $envText)
    }
}

Write-Host '[5/5] Service (starts at boot, restarts on failure)' -ForegroundColor Cyan
# An always-on node must not fall asleep when nobody uses the PC
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$Root\windows\run.cmd`"" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Stop-Attendance
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host ''
Write-Host 'Installed. Log: data\attendance.log' -ForegroundColor Green
Write-Host '  Get-Content data\attendance.log -Wait -Tail 30'
