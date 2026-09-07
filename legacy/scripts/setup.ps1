# ============================================================
# 屏幕识别 -> QQ 发送工具  ·  一次性初始化脚本
# 作用：下载/整理 tesseract.js 库、WASM 内核与中文训练数据到 public/vendor
# 用法：powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# 可重复执行（幂等）
# 说明：本机 schannel TLS 异常，下载统一走 Node(OpenSSL) 辅助脚本
# ============================================================
[CmdletBinding()]
param(
    [switch]$SkipDownload   # 仅校验现有文件，不联网
)
$ErrorActionPreference = 'Stop'

$root      = Split-Path -Parent $PSScriptRoot          # screen-qq-ocr\
$vendor    = Join-Path $root 'public\vendor'
$tessdata  = Join-Path $vendor 'tessdata'
$helper    = Join-Path $PSScriptRoot 'download.js'
New-Item -ItemType Directory -Force -Path $vendor, $tessdata | Out-Null

# 需要落在 public\vendor 下的文件（tesseract.js 主库/worker + tesseract.js-core 内核）
$libFiles = @(
    'tesseract.min.js',
    'worker.min.js',
    'tesseract-core.wasm.js',
    'tesseract-core-simd.wasm.js',
    'tesseract-core-lstm.wasm.js',
    'tesseract-core-simd-lstm.wasm.js'
)
$gzTarget = Join-Path $tessdata 'chi_sim.traineddata.gz'

function Test-AllPresent {
    $ok = $true
    foreach ($f in $libFiles) { if (-not (Test-Path (Join-Path $vendor $f))) { Write-Host "缺少: $f" -ForegroundColor Yellow; $ok = $false } }
    if (-not (Test-Path $gzTarget)) { Write-Host "缺少: chi_sim.traineddata.gz" -ForegroundColor Yellow; $ok = $false }
    return $ok
}

if ($SkipDownload) {
    Write-Host '跳过下载，仅校验：'
    if (Test-AllPresent) { Write-Host '全部就绪 ✓' -ForegroundColor Green } else { Write-Host '存在缺失，请不带 -SkipDownload 重新执行' -ForegroundColor Red }
    exit 0
}

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Write-Host '未找到 node，无法下载依赖' -ForegroundColor Red; exit 1 }

# ---------- 下载（Node https 直连，jsdelivr CDN 优先，npm 兜底） ----------
function Get-ViaNode {
    $urls = @(
        'https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js',
        'https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/worker.min.js',
        'https://cdn.jsdelivr.net/npm/tesseract.js-core@5.1.1/tesseract-core.wasm.js',
        'https://cdn.jsdelivr.net/npm/tesseract.js-core@5.1.1/tesseract-core-simd.wasm.js',
        'https://cdn.jsdelivr.net/npm/tesseract.js-core@5.1.1/tesseract-core-lstm.wasm.js',
        'https://cdn.jsdelivr.net/npm/tesseract.js-core@5.1.1/tesseract-core-simd-lstm.wasm.js'
    )
    Write-Host '通过 Node 下载 tesseract.js 库与内核...'
    & $node.Source $helper $vendor @urls
    if ($LASTEXITCODE -ne 0) { return $false }
    if (-not (Test-Path $gzTarget)) {
        Write-Host '通过 Node 下载中文训练数据...'
        & $node.Source $helper $tessdata 'https://cdn.jsdelivr.net/npm/@tesseract.js-data/chi_sim/4.0.0_best_int/chi_sim.traineddata.gz'
        if ($LASTEXITCODE -ne 0) { return $false }
    }
    return $true
}

function Get-FromNpm {
    Write-Host '改用 npm 方式获取依赖...'
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) { Write-Host '未找到 npm.cmd，无法使用 npm 兜底' -ForegroundColor Red; return $false }
    $tmp = Join-Path $env:TEMP ("sqo-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        Push-Location $tmp
        $cache = Join-Path $tmp '.npm-cache'
        & $npm.Source install "tesseract.js@^5" --no-audit --no-fund --loglevel=error --cache $cache
        if ($LASTEXITCODE -ne 0) { throw 'npm install tesseract.js 失败' }
        # 从 node_modules 树中查找各文件（tesseract.js 与 tesseract.js-core 的产物）
        foreach ($k in $libFiles) {
            $hit = Get-ChildItem (Join-Path $tmp 'node_modules') -Recurse -Filter $k -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($hit) { Copy-Item $hit.FullName (Join-Path $vendor $k) -Force; Write-Host "已复制 $k" }
        }
        if (-not (Test-Path $gzTarget)) {
            & $npm.Source install '@tesseract.js-data/chi_sim' --no-audit --no-fund --loglevel=error --cache $cache
            if ($LASTEXITCODE -eq 0) {
                $gz = Get-ChildItem (Join-Path $tmp 'node_modules\@tesseract.js-data\chi_sim') -Recurse -Filter 'chi_sim.traineddata.gz' -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($gz) { Copy-Item $gz.FullName $gzTarget -Force; Write-Host "已复制 chi_sim.traineddata.gz" }
            }
        }
        return $true
    } catch {
        Write-Host "npm 兜底失败: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    } finally {
        Pop-Location
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$ok = Get-ViaNode
if (-not $ok) { $ok = Get-FromNpm }

Write-Host ''
Write-Host '================ 初始化结果 ================' -ForegroundColor Cyan
if (Test-AllPresent) {
    Write-Host '依赖就绪 ✓  可直接运行 start.bat 启动' -ForegroundColor Green
    exit 0
} else {
    Write-Host '依赖不完整，请检查网络后重新执行本脚本' -ForegroundColor Red
    exit 1
}
