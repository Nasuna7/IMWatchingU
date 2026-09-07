$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & '.venv/Scripts/python.exe' -m pytest
    if ($LASTEXITCODE -ne 0) { throw '测试失败，停止构建' }
    & '.venv/Scripts/python.exe' -m PyInstaller --noconfirm 'packaging/screen_qq_ocr.spec'
    if ($LASTEXITCODE -ne 0) { throw '构建失败' }
} finally { Pop-Location }
