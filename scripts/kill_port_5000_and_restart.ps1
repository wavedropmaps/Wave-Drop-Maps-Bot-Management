# kill_port_5000_and_restart.ps1 — elevated cleanup for stale Flask on :5000
$ErrorActionPreference = 'Continue'
$bot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
$log = Join-Path $bot 'kill_port_5000.log'

"=== $(Get-Date -Format o) ===" | Out-File $log -Encoding utf8

netstat -ano | Select-String 'LISTENING' | Select-String ':5000' | ForEach-Object {
    "before: $_" | Out-File $log -Append -Encoding utf8
}

$portPids = @()
netstat -ano | Select-String 'LISTENING' | Select-String ':5000' | ForEach-Object {
    $parts = ($_ -split '\s+') | Where-Object { $_ -ne '' }
    if ($parts.Count -ge 5) {
        $portPid = [int]$parts[-1]
        if ($portPid -gt 0) { $portPids += $portPid }
    }
}
foreach ($portPid in ($portPids | Select-Object -Unique)) {
    $r = cmd /c "taskkill /F /PID $portPid 2>&1"
    "taskkill $portPid -> $r" | Out-File $log -Append -Encoding utf8
}

Start-Sleep -Seconds 2

netstat -ano | Select-String 'LISTENING' | Select-String ':5000' | ForEach-Object {
    "after-kill: $_" | Out-File $log -Append -Encoding utf8
}

& (Join-Path $bot 'restart_staff_hub.ps1') *>&1 | Out-File $log -Append -Encoding utf8
