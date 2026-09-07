# ============================================================
# 输出 QQ 窗口列表（JSON），供 server.js /api/status 使用
# 用法:
#   powershell -NoProfile -ExecutionPolicy Bypass -File qq-list.ps1 [-OutFile <json 文件路径>]
# 指定 -OutFile 时结果写入该文件（UTF-8），否则输出到 stdout
# ============================================================
[CmdletBinding()]
param(
    [string]$OutFile = ''
)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Write-Result($json) {
    if ($OutFile) { $json | Out-File -LiteralPath $OutFile -Encoding utf8 } else { Write-Output $json }
}

try {
    . (Join-Path $PSScriptRoot 'qq-common.ps1')

    $windows = Get-QQWindows
    $result = [pscustomobject]@{
        running = $windows.Count -gt 0
        windows = @($windows | ForEach-Object {
            [pscustomobject]@{ pid = $_.Pid; title = $_.Title; visible = $_.Visible }
        })
    }
    Write-Result ($result | ConvertTo-Json -Compress -Depth 4)
} catch {
    $err = [pscustomobject]@{ ok = $false; detail = "qq-list 脚本错误: $($_.Exception.Message)"; windowTitle = '' } | ConvertTo-Json -Compress
    Write-Result $err
    exit 1
}
