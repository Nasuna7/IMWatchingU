# ============================================================
# QQ 自动发送：剪贴板粘贴 + 激活 QQ 窗口 + 回车发送
# 用法:
#   powershell -NoProfile -ExecutionPolicy Bypass -File qq-send.ps1 -Key enter -Window auto [-OutFile <json 文件路径>]
#   文本：环境变量 QQ_TEXT_FILE 指定（UTF-8 文本文件路径）
#   图片：-ImageFile <png 文件路径>（把图片放进剪贴板后粘贴发送，优先级高于文本）
# 输出: JSON { ok, detail, windowTitle }（指定 -OutFile 时写入该文件，否则输出到 stdout）
# ============================================================
[CmdletBinding()]
param(
    [string]$Key       = 'enter',   # enter | ctrl_enter
    [string]$Window    = 'auto',    # auto | 标题片段
    [string]$OutFile   = '',
    [string]$ImageFile = ''         # 发送图片模式（PNG 文件路径）
)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Write-JsonResult($ok, $detail, $windowTitle) {
    $json = [pscustomobject]@{ ok = $ok; detail = $detail; windowTitle = $windowTitle } | ConvertTo-Json -Compress
    if ($OutFile) {
        $json | Out-File -LiteralPath $OutFile -Encoding utf8
    } else {
        Write-Output $json
    }
}

try {
    . (Join-Path $PSScriptRoot 'qq-common.ps1')

# ---------- 读取发送内容（图片优先，其次文本） ----------
$useImage = -not [string]::IsNullOrWhiteSpace($ImageFile)
$text = ''
if ($useImage) {
    if (-not (Test-Path -LiteralPath $ImageFile)) {
        Write-JsonResult $false '图片文件不存在' ''
        exit 1
    }
} else {
    $textFile = $env:QQ_TEXT_FILE
    if ([string]::IsNullOrWhiteSpace($textFile) -or -not (Test-Path -LiteralPath $textFile)) {
        Write-JsonResult $false '缺少文本文件（QQ_TEXT_FILE 未设置或不存在）' ''
        exit 1
    }
    $text = (Get-Content -LiteralPath $textFile -Raw -Encoding UTF8)
    if ([string]::IsNullOrWhiteSpace($text)) {
        Write-JsonResult $false '发送内容为空' ''
        exit 1
    }
}

# ---------- 查找 QQ 窗口 ----------
$windows = Get-QQWindows
if ($windows.Count -eq 0) {
    Write-JsonResult $false '未找到 QQ 进程或窗口，请先启动 QQ 并登录' ''
    exit 1
}
$cands = @($windows | Where-Object { $_.Visible })
if ($cands.Count -eq 0) { $cands = $windows }

$target = $null
if ($Window -ne 'auto') {
    $target = @($cands | Where-Object { $_.Title -like "*$Window*" }) | Select-Object -First 1
    if (-not $target) {
        $titles = ($cands | ForEach-Object { $_.Title }) -join ' / '
        Write-JsonResult $false "未找到标题包含 [$Window] 的 QQ 窗口。现有窗口: $titles" ''
        exit 1
    }
} else {
    # 自动选窗：优先可见的聊天/主窗口，排除工具类窗口（图片查看等）
    $utility = @('图片查看', '视频通话', '语音通话', '截图', 'QQ空间', '我的收藏', '好友管理器', '群成员', '聊天记录', '收藏管理器', '表情商店')
    function Test-ChatLike($t) {
        if ($t -eq 'QQ') { return $false }
        if ($utility -contains $t) { return $false }
        return ($t -match '[\u4e00-\u9fff]' -and $t.Length -ge 3) -or ($t -match '会话')
    }
    $target = @($cands | Where-Object { $_.Visible -and (Test-ChatLike $_.Title) }) | Select-Object -First 1
    if (-not $target) { $target = @($cands | Where-Object { $_.Visible -and $_.Title -eq 'QQ' }) | Select-Object -First 1 }
    if (-not $target) { $target = @($cands | Where-Object { $_.Visible }) | Select-Object -First 1 }
    if (-not $target) { $target = @($cands) | Select-Object -First 1 }
}

$hwnd     = [IntPtr]$target.Hwnd
$fgBefore = [Win32QQ]::GetForegroundWindow()

# ---------- 恢复并激活窗口（多策略对抗前台锁） ----------
function Activate-Window([IntPtr]$h) {
    # 策略1: Alt 键释放前台锁 + AttachThreadInput + SetForegroundWindow
    for ($i = 0; $i -lt 3; $i++) {
        [Win32QQ]::ShowWindow($h, 9) | Out-Null   # SW_RESTORE
        Start-Sleep -Milliseconds 150
        [Win32QQ]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)      # Alt 按下（解除前台锁）
        [Win32QQ]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)      # Alt 抬起 (KEYEVENTF_KEYUP)
        Start-Sleep -Milliseconds 50
        $fg = [Win32QQ]::GetForegroundWindow()
        $fgPid = 0
        $fgThread = [Win32QQ]::GetWindowThreadProcessId($fg, [ref]$fgPid)
        $myThread = [Win32QQ]::GetCurrentThreadId()
        [Win32QQ]::AttachThreadInput($myThread, $fgThread, $true) | Out-Null
        [Win32QQ]::SetForegroundWindow($h) | Out-Null
        [Win32QQ]::SetActiveWindow($h) | Out-Null
        [Win32QQ]::BringWindowToTop($h) | Out-Null
        [Win32QQ]::AttachThreadInput($myThread, $fgThread, $false) | Out-Null
        Start-Sleep -Milliseconds 300
        if ([Win32QQ]::GetForegroundWindow() -eq $h) { return $true }
    }
    # 策略2: 最小化再还原（窗口管理器会授予前台）
    [Win32QQ]::ShowWindow($h, 6) | Out-Null   # SW_MINIMIZE
    Start-Sleep -Milliseconds 250
    [Win32QQ]::ShowWindow($h, 9) | Out-Null   # SW_RESTORE
    Start-Sleep -Milliseconds 350
    [Win32QQ]::SetForegroundWindow($h) | Out-Null
    Start-Sleep -Milliseconds 300
    if ([Win32QQ]::GetForegroundWindow() -eq $h) { return $true }
    # 策略3: 最后直接尝试一次
    [Win32QQ]::SetForegroundWindow($h) | Out-Null
    Start-Sleep -Milliseconds 300
    return ([Win32QQ]::GetForegroundWindow() -eq $h)
}

if (-not (Activate-Window $hwnd)) {
    Write-JsonResult $false '无法激活 QQ 窗口（系统前台锁定），请先手动点击一下 QQ 窗口后再试' $target.Title
    exit 1
}

# ---------- 剪贴板（图片 or 文本）+ 粘贴 + 发送 ----------
try {
    if ($useImage) {
        # 图片模式：把 PNG 放入剪贴板（图片格式），QQ 输入框 Ctrl+V 会粘贴图片
        Add-Type -AssemblyName System.Drawing -ErrorAction Stop
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        $img = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $ImageFile))
        $clipOk = $false
        for ($i = 0; $i -lt 5 -and -not $clipOk; $i++) {
            try {
                [System.Windows.Forms.Clipboard]::SetImage($img)
                Start-Sleep -Milliseconds 150
                $clipOk = [System.Windows.Forms.Clipboard]::ContainsImage()
            } catch {
                Start-Sleep -Milliseconds 300   # 剪贴板被占用时重试
            }
        }
        if (-not $clipOk) { throw '剪贴板图片写入失败（多次重试后仍未生效）' }
        # 关键：剪贴板图片是延迟渲染，$img 必须保持存活直到 QQ 粘贴完成，否则渲染失败；统一在粘贴后 Dispose
    } else {
        Set-Clipboard -Value $text
    }
} catch {
    Write-JsonResult $false "剪贴板写入失败: $($_.Exception.Message)" $target.Title
    exit 1
}
Start-Sleep -Milliseconds 500

$wshell = New-Object -ComObject WScript.Shell
$wshell.SendKeys('^v') | Out-Null
Start-Sleep -Milliseconds 600
if ($Key -eq 'ctrl_enter') { $wshell.SendKeys('^{ENTER}') | Out-Null } else { $wshell.SendKeys('{ENTER}') | Out-Null }
Start-Sleep -Milliseconds 300

# 粘贴完成后再释放图片对象
if ($useImage -and $img) { $img.Dispose() }

# ---------- 恢复原前台窗口（尽力而为） ----------
if ($fgBefore -ne [IntPtr]::Zero -and $fgBefore -ne $hwnd) {
    [Win32QQ]::SetForegroundWindow($fgBefore) | Out-Null
}

$what = if ($useImage) { '图片' } else { '文本' }
Write-JsonResult $true "已发送${what}到 QQ 窗口「$($target.Title)」（按键: $Key）" $target.Title
    exit 0
} catch {
    Write-JsonResult $false "qq-send 脚本异常: $($_.Exception.Message)" ''
    exit 1
}
