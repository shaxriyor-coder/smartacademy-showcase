<#
.SYNOPSIS
  Lokal namoyish: HTTPS tunnel, sayt, Telegram xabarlari, smartbot va checker'ni ishga tushiradi.

.DESCRIPTION
  docs/DEMO.md. Har jarayon alohida oynada ochiladi (loglari ko'rinib turadi).
  Tunnel manzili har safar yangi bo'ladi - skript uni .env va smartbot\.env ga o'zi yozadi.
  To'xtatish: pwsh -ExecutionPolicy Bypass -File scripts\demo-stop.ps1

.PARAMETER Build
  Saytni qayta build qiladi (kod o'zgargan yoki NEXT_PUBLIC_* sozlamasi o'zgargan bo'lsa).

.PARAMETER Minimized
  Oynalarni kichraytirilgan holda ochadi.

.EXAMPLE
  pwsh -ExecutionPolicy Bypass -File scripts\demo-start.ps1
#>
param([switch]$Build, [switch]$Minimized)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
$Shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { "pwsh" } else { "powershell" }
$Style = if ($Minimized) { "Minimized" } else { "Normal" }
$LogDir = Join-Path $env:TEMP "smartacademy-demo"
$TunnelLog = Join-Path $LogDir "tunnel.log"
New-Item -ItemType Directory -Force $LogDir | Out-Null

function Step($text) { Write-Host "`n> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "XATO: $text" -ForegroundColor Red; exit 1 }

function Get-EnvValue($path, $key) {
  $m = [regex]::Match((Get-Content -Raw -Encoding UTF8 $path), "(?m)^$key=(.*)$")
  if ($m.Success) { return $m.Groups[1].Value.Trim().Trim('"') }
  return ""
}

function Set-EnvValue($path, $key, $value, [switch]$Quoted) {
  $line = if ($Quoted) { "$key=`"$value`"" } else { "$key=$value" }
  $content = Get-Content -Raw -Encoding UTF8 $path
  if ([regex]::IsMatch($content, "(?m)^$key=.*$")) {
    $content = [regex]::Replace($content, "(?m)^$key=.*$", [System.Text.RegularExpressions.MatchEvaluator] { param($m) $line })
  } else {
    $content = $content.TrimEnd() + "`n$line`n"
  }
  [System.IO.File]::WriteAllText($path, $content, (New-Object System.Text.UTF8Encoding $false))
}

function Start-Window($title, $workdir, $command) {
  $cmd = "`$Host.UI.RawUI.WindowTitle = 'SmartAcademy demo: $title'; Set-Location '$workdir'; $command"
  Start-Process $Shell -ArgumentList @("-NoExit", "-Command", $cmd) -WindowStyle $Style | Out-Null
}

function Wait-Health($url, $seconds) {
  $deadline = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $deadline) {
    try {
      if ((Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10).Content -match '"ok":true') { return $true }
    } catch { }
    Start-Sleep -Seconds 3
  }
  return $false
}

Step "Tekshiruv"
if (-not $Cloudflared) { Fail "cloudflared PATH da topilmadi" }
if (-not (Test-Path "$Root\smartbot\.venv\Scripts\python.exe")) { Fail "smartbot\.venv yo'q - docs/DEMO.md, 'Birinchi marta'" }
if (-not (Get-EnvValue "$Root\smartbot\.env" "BOT_TOKEN")) { Fail "smartbot\.env da BOT_TOKEN bo'sh" }
if (-not (Get-EnvValue "$Root\.env" "TELEGRAM_BOT_TOKEN")) { Fail ".env da TELEGRAM_BOT_TOKEN bo'sh" }
if (-not (Get-NetTCPConnection -LocalPort 5433 -State Listen -ErrorAction SilentlyContinue)) { Fail "PostgreSQL (5433-port) ishlamayapti" }
Write-Host "  hammasi joyida"

Step "Eski jarayonlarni to'xtatish"
& "$PSScriptRoot\demo-stop.ps1" -Quiet

Step "HTTPS tunnel (Cloudflare)"
$url = $null
foreach ($attempt in 1..3) {
  Remove-Item $TunnelLog -ErrorAction SilentlyContinue
  Start-Window "tunnel" $Root "& '$Cloudflared' tunnel --no-autoupdate --url http://localhost:3100 2>&1 | Tee-Object -FilePath '$TunnelLog'"
  $deadline = (Get-Date).AddSeconds(45)
  while (-not $url -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    if (Test-Path $TunnelLog) {
      $log = Get-Content -Raw $TunnelLog
      if ($log) {
        $m = [regex]::Matches($log, "https://[a-z0-9]+(-[a-z0-9]+)+\.trycloudflare\.com") | Where-Object { $_.Value -notlike "https://api.*" } | Select-Object -First 1
        if ($m) { $url = $m.Value }
        elseif ($log -match "failed to request quick Tunnel") { break }
      }
    }
  }
  if ($url) { break }
  Write-Host "  tunnel ochilmadi ($attempt-urinish), qayta..." -ForegroundColor Yellow
  & "$PSScriptRoot\demo-stop.ps1" -Quiet -TunnelOnly
}
if (-not $url) { Fail "tunnel ochilmadi - log: $TunnelLog" }
Write-Host "  $url"

Step "Manzilni sozlamalarga yozish"
Set-EnvValue "$Root\.env" "WEBAPP_URL" $url -Quoted
Set-EnvValue "$Root\.env" "NEXTAUTH_URL" $url -Quoted
Set-EnvValue "$Root\smartbot\.env" "PLATFORM_URL" $url
Write-Host "  .env (WEBAPP_URL, NEXTAUTH_URL), smartbot\.env (PLATFORM_URL)"

if ($Build -or -not (Test-Path "$Root\.next\BUILD_ID")) {
  Step "Sayt build (bir necha daqiqa)"
  Push-Location $Root
  npm run build
  if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "build xato bilan tugadi" }
  Pop-Location
}

Step "Sayt"
Start-Window "sayt" $Root "npx next start -p 3100"
if (-not (Wait-Health "http://localhost:3100/api/health" 90)) { Fail "sayt 90 soniyada ishga tushmadi - 'sayt' oynasini ko'ring" }
Write-Host "  http://localhost:3100 ishlayapti"

Step "Telegram xabarlari, smartbot, checker"
Start-Window "xabarlar" $Root "npm run notify"
Start-Window "smartbot" "$Root\smartbot" "`$env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe bot.py"
Start-Window "checker" "$Root\checker" "python server.py"

Step "Tunnel orqali tekshiruv"
if (-not (Wait-Health "$url/api/health" 90)) { Fail "sayt tunnel orqali ochilmadi: $url" }

$bot = Get-EnvValue "$Root\.env" "NEXT_PUBLIC_TELEGRAM_BOT_USERNAME"
Write-Host ""
Write-Host "TAYYOR" -ForegroundColor Green
Write-Host "  Bot:        https://t.me/$($bot.TrimStart('@'))  (/start, keyin 'Open App')"
Write-Host "  Sayt:       $url"
Write-Host "  O'qituvchi: http://localhost:3100/login (email + parol)"
Write-Host "  To'xtatish: pwsh -ExecutionPolicy Bypass -File scripts\demo-stop.ps1"
