# Open a 390x844 Chromium app window (Chrome or Edge) for the M-02 check.
# Usage: powershell -ExecutionPolicy Bypass -File deploy\m02-mobile.ps1
$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8000"

# Raw TCP check: avoids any system proxy that would reject 127.0.0.1.
$client = New-Object System.Net.Sockets.TcpClient
$online = $false
try {
    $client.Connect("127.0.0.1", 8000)
    $online = $client.Connected
} catch {
    $online = $false
} finally {
    $client.Close()
}

if (-not $online) {
    Write-Host "Backend is not running on port 8000." -ForegroundColor Yellow
    Write-Host "Start it first:"
    Write-Host "  cd E:\dings\Documents\Codex\2026-10-20\web\wolfarena"
    Write-Host "  .\.venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8000"
    exit 1
}

$candidates = @(
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
)
$browser = $candidates |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1
if (-not $browser) {
    Write-Host "No Chrome or Edge found. Open $base/ manually." -ForegroundColor Yellow
    exit 1
}

Start-Process $browser -ArgumentList @(
    "--app=$base/",
    "--new-window",
    "--window-size=390,844",
    "--window-position=120,80"
)

Write-Host ""
Write-Host "Opened a 390x844 Chromium window: $browser" -ForegroundColor Green
Write-Host "1. Type a nickname, click the create-room button."
Write-Host "2. Click the start button; night phases advance one by one."
Write-Host "3. Speak and vote when it is your turn, until the game ends."
Write-Host "4. Press Win+Shift+S to capture each screen into docs\evidence\."
Write-Host ""
Write-Host "If no window appeared, open this URL manually: $base/"
