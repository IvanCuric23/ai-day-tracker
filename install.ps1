<#
.SYNOPSIS
    Installs AI day tracker for the current Windows user (no admin rights needed).

.DESCRIPTION
    1. Finds Python 3.10+ and checks git.
    2. Copies the scripts to %USERPROFILE%\.claude\clock and %USERPROFILE%\.claude\hooks.
    3. Writes config.json (your git name/e-mail as commit authors, Jira URL, port) unless it exists.
    4. Adds the clock hooks to Claude Code and/or GitHub Copilot CLI.
    5. Registers two scheduled tasks: "My AI day" (17:00 Mon-Fri) and "My AI dashboard server" (every 5 min).
    6. Builds the last days from your existing AI history and opens http://localhost:<port>.
    Safe to run again: it updates the scripts and keeps your data, config.json and tickets.json.

.EXAMPLE
    .\install.ps1
.EXAMPLE
    .\install.ps1 -JiraUrl https://jira.example.com/browse/
#>
[CmdletBinding()]
param(
    [string]   $JiraUrl,                 # Jira keys (ABC-123) link to <JiraUrl>ABC-123
    [string[]] $Authors,                 # whose git commits count as yours; default: git user.name + user.email
    [int]      $Port = 0,                # dashboard port; default 8800
    [int]      $BackfillDays = 7,        # build this many past days now, from your existing history
    [switch]   $NoTasks,                 # skip the scheduled tasks (no 17:00 run, no always-on dashboard)
    [switch]   $NoOpen                   # do not open the browser at the end
)
$ErrorActionPreference = 'Stop'
$Repo = $PSScriptRoot
$UserDir = $env:USERPROFILE
$Clock = Join-Path $UserDir '.claude\clock'
$Hooks = Join-Path $UserDir '.claude\hooks'

function Step($text) { Write-Host "`n> $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "  $text" -ForegroundColor Green }
function Warn($text) { Write-Host "  ! $text" -ForegroundColor Yellow }

function Find-Python {
    # the Microsoft Store "python.exe" in WindowsApps is only an installer stub: skip it
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) { $candidates += , @('py', '-3') }
    foreach ($c in @(Get-Command python -All -CommandType Application -ErrorAction SilentlyContinue)) {
        if ($c.Source -notmatch 'WindowsApps') { $candidates += , @($c.Source) }
    }
    foreach ($c in $candidates) {
        $exe = $c[0]; $rest = @($c | Select-Object -Skip 1)
        try { $out = @(& $exe @rest -c "import sys; print(sys.executable); print(sys.version_info >= (3, 10))" 2>$null) }
        catch { continue }
        if ($LASTEXITCODE -eq 0 -and $out.Count -ge 2 -and $out[1] -eq 'True') { return $out[0].Trim() }
    }
    return $null
}

# ---- 1. prerequisites ----------------------------------------------------------------------------
Step 'Checking prerequisites'
$Python = Find-Python
if (-not $Python) {
    Write-Host "  Python 3.10 or newer was not found." -ForegroundColor Red
    Write-Host "  Install it:  winget install Python.Python.3.12   (then open a new terminal and run install.ps1 again)"
    exit 1
}
$PythonW = Join-Path (Split-Path $Python) 'pythonw.exe'
if (-not (Test-Path $PythonW)) { $PythonW = $Python }
Ok "Python: $Python"

if (Get-Command git -ErrorAction SilentlyContinue) { Ok 'git: found' }
else { Warn 'git not found: hours still work, but tickets from branch names and commits will be missing.' }

$UseClaude = (Test-Path (Join-Path $UserDir '.claude\projects')) -or [bool](Get-Command claude -ErrorAction SilentlyContinue)
$UseCopilot = (Test-Path (Join-Path $UserDir '.copilot')) -or [bool](Get-Command copilot -ErrorAction SilentlyContinue)
if ($UseClaude) { Ok 'Claude Code: found' }
if ($UseCopilot) { Ok 'Copilot CLI: found' }
if (-not ($UseClaude -or $UseCopilot)) {
    Warn 'Neither Claude Code nor Copilot CLI was found. Installing anyway; VS Code Copilot Chat history is still read.'
}

# ---- 2. files ------------------------------------------------------------------------------------
Step "Copying scripts to $Clock"
New-Item -ItemType Directory -Force -Path $Clock, $Hooks | Out-Null
$VersionFile = Join-Path $Clock 'VERSION'
$OldVersion = if (Test-Path $VersionFile) { ([string](Get-Content $VersionFile -Raw)).Trim() } else { '' }
$RepoVersionFile = Join-Path $Repo 'VERSION'
$Version = if (Test-Path $RepoVersionFile) { ([string](Get-Content $RepoVersionFile -Raw)).Trim() } else { '' }
Copy-Item (Join-Path $Repo 'src\clock\*') $Clock -Recurse -Force -Exclude '__pycache__'
Copy-Item (Join-Path $Repo 'src\hooks\clock.py') $Hooks -Force
if ($Version) { [IO.File]::WriteAllText($VersionFile, $Version, [Text.UTF8Encoding]::new($false)) }
$TicketsFile = Join-Path $Hooks 'tickets.json'
if (-not (Test-Path $TicketsFile)) { Copy-Item (Join-Path $Repo 'src\hooks\tickets.example.json') $TicketsFile }
Ok 'done (your days, clock.jsonl and tickets.json are kept)'

# ---- 3. config.json ------------------------------------------------------------------------------
Step 'Writing config.json'
$ConfigFile = Join-Path $Clock 'config.json'
$config = [ordered]@{}
if (Test-Path $ConfigFile) {
    (Get-Content $ConfigFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $config[$_.Name] = $_.Value }
}
if (-not $config.Contains('authors') -or $Authors) {
    if (-not $Authors) {
        $Authors = @(foreach ($k in 'user.name', 'user.email') {
            $v = ''; if (Get-Command git -ErrorAction SilentlyContinue) { $v = (git config --global $k) 2>$null }
            if ($v) { $v.Trim() } })
    }
    $config['authors'] = @($Authors | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}
if ($JiraUrl) { $config['jira_url'] = $(if ($JiraUrl.EndsWith('/')) { $JiraUrl } else { "$JiraUrl/" }) }
elseif (-not $config.Contains('jira_url')) { $config['jira_url'] = '' }
if ($Port) { $config['port'] = $Port } elseif (-not $config.Contains('port')) { $config['port'] = 8800 }
foreach ($k in @{ day_from = 7; day_to = 19; gap_minutes = 10 }.GetEnumerator()) {
    if (-not $config.Contains($k.Key)) { $config[$k.Key] = $k.Value }
}
if (-not $config.Contains('reports_dir')) { $config['reports_dir'] = '~/Documents/DailyWorkReport/reports' }
[IO.File]::WriteAllText($ConfigFile, ($config | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
Ok "$ConfigFile"
if (-not $config['authors']) { Warn 'No git user.name/user.email: commits will not be matched. Set "authors" in config.json.' }
if (-not $config['jira_url']) { Warn 'No Jira URL: Jira tickets show as text. Run again with -JiraUrl https://<your-jira>/browse/' }
$Port = [int]$config['port']

# ---- 4. hooks ------------------------------------------------------------------------------------
Step 'Adding the clock hooks'
$hookArgs = @('install', '--python', $Python)
if ($UseClaude) { $hookArgs += '--claude' }
if ($UseCopilot) { $hookArgs += '--copilot' }
if ($UseClaude -or $UseCopilot) {
    & $Python -X utf8 (Join-Path $Repo 'src\setup_hooks.py') @hookArgs
    if ($LASTEXITCODE -ne 0) { throw 'Adding the hooks failed (see above).' }
    Ok 'Restart open Claude Code / Copilot sessions so they pick up the hooks.'
}
else { Warn 'skipped: no Claude Code or Copilot CLI' }

# ---- 5. scheduled tasks --------------------------------------------------------------------------
if (-not $NoTasks) {
    Step 'Registering scheduled tasks'
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
    $daily = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    Register-ScheduledTask -TaskName 'My AI day' -Force -Principal $principal -Settings $daily `
        -Description 'AI day tracker: calculates yesterday and today at 17:00' `
        -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At 17:00) `
        -Action (New-ScheduledTaskAction -Execute $PythonW -Argument "`"$Clock\daily.py`"" -WorkingDirectory $Clock) | Out-Null
    Ok 'My AI day: Mon-Fri 17:00'

    $server = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
    Register-ScheduledTask -TaskName 'My AI dashboard server' -Force -Principal $principal -Settings $server `
        -Description "AI day tracker: keeps http://localhost:$Port running (a second copy exits at once)" `
        -Trigger $trigger `
        -Action (New-ScheduledTaskAction -Execute $PythonW -Argument "`"$Clock\server.py`"" -WorkingDirectory $Clock) | Out-Null
    Ok 'My AI dashboard server: every 5 minutes, also on battery'
}

# ---- 6. first build + start ----------------------------------------------------------------------
Step "Building the last $BackfillDays days from your AI history"
for ($i = $BackfillDays; $i -ge 0; $i--) {
    $day = (Get-Date).AddDays(-$i).ToString('yyyy-MM-dd')
    & $Python -X utf8 (Join-Path $Clock 'my_day.py') $day --no-open | Out-Null
    if ($LASTEXITCODE -ne 0) { Warn "$day failed" }
}
Ok 'done'

Step 'Starting the dashboard'
if ($NoTasks) { Start-Process $PythonW -ArgumentList "`"$Clock\server.py`"" -WorkingDirectory $Clock -WindowStyle Hidden }
else { Start-ScheduledTask -TaskName 'My AI dashboard server' }
$url = "http://localhost:$Port/"
$up = $false
foreach ($n in 1..20) {
    # 127.0.0.1, not localhost: Windows PowerShell tries IPv6 first and the server listens on IPv4 only
    try { Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2 | Out-Null; $up = $true; break }
    catch { Start-Sleep -Milliseconds 500 }
}
if ($up) { Ok "running: $url  (bookmark it)" } else { Warn "the dashboard did not answer on $url yet; try again in a minute" }
if ($up -and -not $NoOpen) { Start-Process $url }
$done = if (-not $Version) { 'Installed ai-day-tracker (version unknown)' }
        elseif ($OldVersion -and $OldVersion -ne $Version) { "Updated v$OldVersion -> v$Version" }
        else { "Installed ai-day-tracker v$Version" }
Write-Host "`n$done. It calculates your day at 17:00; the 'Refresh today' button does it any time.`n" -ForegroundColor Green
