# ============================================================
# Windows 自带 OCR（WinRT）识别脚本：精度高于 tesseract 的备选引擎
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File ocr-win.ps1 -ImagePath <png> [-OutFile <json>]
# 输出: JSON { ok, text, lines:[{text}], ms }
# ============================================================
[CmdletBinding()]
param(
    [string]$ImagePath = '',
    [string]$OutFile   = ''
)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

if (-not $ImagePath -or -not (Test-Path -LiteralPath $ImagePath)) {
    '{"ok":false,"detail":"图片路径无效"}'
    exit 1
}
$sw = [System.Diagnostics.Stopwatch]::StartNew()

Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type -AssemblyName System.Drawing

$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IBuffer, Windows.Foundation, ContentType = WindowsRuntime]

# WinRT 异步操作 → .NET Task 同步等待
function Await($WinRtTask, $ResultType) {
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

# ---------- System.Drawing 读取 PNG → BGRA 字节 ----------
$bmp = [System.Drawing.Bitmap]::FromFile((Resolve-Path -LiteralPath $ImagePath))
$w = $bmp.Width
$h = $bmp.Height
$rect = New-Object System.Drawing.Rectangle(0, 0, $w, $h)
$data = $bmp.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$bytes = $null
try {
    $bytes = New-Object byte[] ($data.Stride * $h)
    [System.Runtime.InteropServices.Marshal]::Copy($data.Scan0, $bytes, 0, $bytes.Length)
} finally {
    $bmp.UnlockBits($data)
    $bmp.Dispose()
}

# ---------- byte[] → IBuffer → SoftwareBitmap (Bgra8) ----------
$buffer = [System.Runtime.InteropServices.WindowsRuntime.WindowsRuntimeBufferExtensions]::AsBuffer($bytes)
$softwareBitmap = [Windows.Graphics.Imaging.SoftwareBitmap]::CreateCopyFromBuffer(
    $buffer,
    [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
    $w,
    $h)

# ---------- 中文 OCR 引擎 ----------
$lang = New-Object Windows.Globalization.Language('zh-Hans-CN')
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) { '{"ok":false,"detail":"无可用 OCR 引擎（系统未安装 OCR 语言包）"}'; exit 1 }
# MaxImageDimension 在 PS 中读取可能为空（uint 投影问题），读不到按 10000 处理
$maxDim = 10000
try { $v = $engine.MaxImageDimension; if ($v) { $maxDim = [int]$v } } catch { }
if ($w -gt $maxDim -or $h -gt $maxDim) {
    '{"ok":false,"detail":"图片超过引擎最大尺寸 ' + $maxDim + '"}'
    exit 1
}

$result = Await ($engine.RecognizeAsync($softwareBitmap)) ([Windows.Media.Ocr.OcrResult])
$lines = @()
foreach ($line in $result.Lines) {
    $lines += [pscustomobject]@{ text = $line.Text }
}
$allText = ($result.Lines | ForEach-Object { $_.Text }) -join "`n"
$sw.Stop()

$out = [pscustomobject]@{
    ok    = $true
    text  = $allText
    lines = @($lines)
    ms    = $sw.ElapsedMilliseconds
}
$json = $out | ConvertTo-Json -Compress -Depth 4
if ($OutFile) { $json | Out-File -LiteralPath $OutFile -Encoding utf8 } else { Write-Output $json }
