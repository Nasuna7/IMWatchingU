param([string]$DataDir = "")
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先创建 .venv 并安装项目依赖，参见 README.md' }
if ($DataDir) { & $pythonPath -m screen_qq_ocr --data-dir $DataDir }
else { & $pythonPath -m screen_qq_ocr }
