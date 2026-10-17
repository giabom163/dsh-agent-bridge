# 舆情总览启动器：确保 dashboard 在跑，然后用默认浏览器打开。
# 桌面快捷方式指向本文件（powershell -File 本文件），点一下就能看情况。
$ErrorActionPreference = 'SilentlyContinue'
$port = 8770
$py   = 'C:\Users\Lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe'
$dash = Join-Path $PSScriptRoot 'dashboard.py'

function Test-Port($p) {
  $c = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
  return [bool]$c
}

if (-not (Test-Port $port)) {
  Start-Process -FilePath $py -ArgumentList @('-B', $dash, '--port', "$port") -WindowStyle Hidden
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 250
    if (Test-Port $port) { break }
  }
}

Start-Process "http://127.0.0.1:$port/"
