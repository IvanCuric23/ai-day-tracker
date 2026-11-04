<#
.SYNOPSIS
    Removes AI day tracker: the scheduled tasks, the dashboard server and the clock hooks.

.DESCRIPTION
    Your data (%USERPROFILE%\.claude\clock: days, clock.jsonl, config.json) is kept unless you add -RemoveData.
    Your other Claude Code hooks and settings stay; settings.json is backed up before the change.

.EXAMPLE
    .\uninstall.ps1
.EXAMPLE
    .\uninstall.ps1 -RemoveData
#>
[CmdletBinding()]
param([switch] $RemoveData)
$ErrorActionPreference = 'Stop'
$Clock = Join-Path $env:USERPROFILE '.claude\clock'
$Hooks = Join-Path $env:USERPROFILE '.claude\hooks'

Write-Host "`n> Removing scheduled tasks" -ForegroundColor Cyan
foreach ($name in 'My AI day', 'My AI dashboard server') {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "  removed: $name" -ForegroundColor Green
    }
}

Write-Host "`n> Stopping the dashboard server" -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match [regex]::Escape("$Clock\server.py") } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "  stopped process $($_.ProcessId)" -ForegroundColor Green }

Write-Host "`n> Removing the clock hooks" -ForegroundColor Cyan
$python = (Get-Command py, python -ErrorAction SilentlyContinue | Where-Object { $_.Source -notmatch 'WindowsApps' } |
    Select-Object -First 1).Source
if ($python) { & $python -X utf8 (Join-Path $PSScriptRoot 'src\setup_hooks.py') uninstall }
# delete clock.py only once no hook calls it any more: a hook pointing at a missing file could block your prompts
if ($python -and $LASTEXITCODE -eq 0) { Remove-Item (Join-Path $Hooks 'clock.py') -ErrorAction SilentlyContinue }
else { Write-Host '  ! Could not remove the hooks: delete the clock.py entries in ~/.claude/settings.json by hand' -ForegroundColor Yellow }

if ($RemoveData) {
    Write-Host "`n> Removing data" -ForegroundColor Cyan
    Remove-Item $Clock -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $Hooks 'tickets.json') -ErrorAction SilentlyContinue
    Write-Host "  removed $Clock" -ForegroundColor Green
}
else { Write-Host "`n  Your data is kept in $Clock (run again with -RemoveData to delete it)." }
Write-Host "`nUninstalled.`n" -ForegroundColor Green
