# 打开一个 390x844 的手机尺寸 Chrome 窗口，用于 M-02 手机端验收。
# 用法：powershell -ExecutionPolicy Bypass -File deploy\m02-mobile.ps1
$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8000"

try {
    Invoke-WebRequest "$base/health" -TimeoutSec 3 | Out-Null
} catch {
    Write-Host "后端没有启动。请先运行：" -ForegroundColor Yellow
    Write-Host "  cd E:\dings\Documents\Codex\2026-10-20\web\wolfarena"
    Write-Host "  .\.venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8000"
    exit 1
}

$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) {
    $chrome = "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
}
if (-not (Test-Path $chrome)) {
    Write-Host "没有找到 Chrome，请手动打开 $base/" -ForegroundColor Yellow
    exit 1
}

Start-Process $chrome -ArgumentList @(
    "--app=$base/",
    "--window-size=390,844",
    "--window-position=120,80"
)

Write-Host ""
Write-Host "已打开 390x844 窗口。" -ForegroundColor Green
Write-Host "1. 填入昵称，点“创建房间”"
Write-Host "2. 点开局的提交按钮，夜晚会自动逐阶段推进"
Write-Host "3. 轮到你时发言/投票，直到“对局结束”"
Write-Host "4. 每一步按 Win+Shift+S 截图，保存到 docs\evidence\"
Write-Host ""
