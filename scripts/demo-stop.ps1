<#
.SYNOPSIS
  demo-start.ps1 ishga tushirgan hamma narsani to'xtatadi: tunnel, sayt, xabarlar, smartbot, checker.
.EXAMPLE
  pwsh -ExecutionPolicy Bypass -File scripts\demo-stop.ps1
#>
param([switch]$Quiet, [switch]$TunnelOnly)

$stopped = @()

function Stop-Matching($pattern) {
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern -and $_.ProcessId -ne $PID } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    $script:stopped += "$($_.Name) ($($_.ProcessId))"
  }
}

if ($TunnelOnly) {
  Stop-Matching "cloudflared(\.exe)?.*tunnel"
  Stop-Matching "SmartAcademy demo: tunnel"
} else {
  foreach ($port in 3100, 8090) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
      Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
      $script:stopped += "port $port ($($_.OwningProcess))"
    }
  }
  Stop-Matching "cloudflared(\.exe)?.*tunnel"
  Stop-Matching "telegram-bot\.ts"
  Stop-Matching "smartbot.*bot\.py|\.venv\\Scripts\\python\.exe\s+bot\.py"
  # demo-start.ps1 ochgan oynalar
  Stop-Matching "SmartAcademy demo:"
}

if (-not $Quiet) {
  if ($stopped) { Write-Host ("To'xtatildi: " + ($stopped -join ", ")) } else { Write-Host "Ishlab turgan namoyish jarayoni yo'q." }
}
