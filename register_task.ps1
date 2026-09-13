# Registers "GoWildMatcher" to run DAILY (8:00 AM), SILENTLY, via Task Scheduler,
# so each morning you get the GoWild flights that just entered the booking window.
# Silent = launched with pythonw.exe (no console window).
# (Optional — the GitHub Actions workflow already runs this in the cloud whether
#  or not your PC is on. Use this only if you also want a local copy.)
# Run this ONCE:  .\register_task.ps1   (elevate if it reports an access error)
# Re-running updates the existing task.

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$matcher   = Join-Path $scriptDir "gowild_matcher.py"

# Prefer pythonw.exe (windowless). Fall back to python.exe if not found.
$python = (Get-Command python).Source
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
$exe = if (Test-Path $pythonw) { $pythonw } else { $python }

$action = New-ScheduledTaskAction -Execute $exe -Argument "`"$matcher`"" -WorkingDirectory $scriptDir

# Every day at 8:00 AM.
$trigger = New-ScheduledTaskTrigger -Daily -At 8:00AM

# Start when available (catch up if the PC was asleep), run on battery (critical
# for laptops: default power conditions leave the task stuck "Queued"), hidden.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -RunOnlyIfNetworkAvailable -Hidden `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew

# Run as the current user, only when logged on (no stored password needed).
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "GoWildMatcher" `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Daily Frontier GoWild Pass matcher: one-tap Frontier search deep links for every city inside the GoWild booking window, from your home hubs. Runs silently." `
    -Force | Out-Null

Write-Host "Registered 'GoWildMatcher' (daily 8:00 AM, silent via $([System.IO.Path]::GetFileName($exe)))."
Write-Host "Manage it in Task Scheduler, or run:  Get-ScheduledTask GoWildMatcher | Get-ScheduledTaskInfo"
Write-Host "Run once now to test:  python `"$matcher`" --preview   (console, no Telegram)"
