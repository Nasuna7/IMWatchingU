# 探测 Windows 自带 OCR 可用语言
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction SilentlyContinue
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    $langs = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages
    '可用 OCR 语言:'
    foreach ($l in $langs) { '  - ' + $l.LanguageTag + ' ' + $l.DisplayName }
    $zh = [Windows.Media.Ocr.OcrEngine]::IsLanguageSupported((New-Object Windows.Globalization.Language('zh-CN')))
    'zh-CN 支持: ' + $zh
    $maxD = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension
    'MaxImageDimension: ' + $maxD
} catch {
    '探测失败: ' + $_.Exception.Message
}
