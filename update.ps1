<#
.SYNOPSIS
    Updates AI day tracker: pulls the latest code (git clone only) and runs install.ps1 again.

.DESCRIPTION
    In a git clone: "git pull --ff-only", then install.ps1 with the same arguments plus -NoOpen.
    If the pull fails (for example local changes), git's message is shown and install.ps1 is not run.
    In a ZIP download there is no git history, so it only says how to update by hand.
    Your data, config.json and tickets.json are kept (install.ps1 never overwrites them).

.EXAMPLE
    .\update.ps1
.EXAMPLE
    .\update.ps1 -JiraUrl https://jira.example.com/browse/
#>
$ErrorActionPreference = 'Stop'
$Repo = $PSScriptRoot

if (-not ((Test-Path (Join-Path $Repo '.git')) -and (Get-Command git -ErrorAction SilentlyContinue))) {
    Write-Host "This copy is not a git clone (or git is not installed), so it cannot update itself." -ForegroundColor Yellow
    Write-Host "Download the new ZIP from https://github.com/IvanCuric23/ai-day-tracker/releases/latest ,"
    Write-Host "extract it and run install.cmd. Your data and settings are kept."
    exit 1
}

Write-Host "> git pull --ff-only" -ForegroundColor Cyan
& git -C $Repo pull --ff-only
if ($LASTEXITCODE -ne 0) {
    Write-Host "`ngit pull failed (see above), so nothing was installed. Fix that first, then run update.cmd again." -ForegroundColor Red
    exit $LASTEXITCODE
}

& (Join-Path $Repo 'install.ps1') @args -NoOpen
exit $LASTEXITCODE
