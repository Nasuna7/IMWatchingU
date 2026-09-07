# ============================================================
# 共享辅助：Win32 窗口枚举 / 前台激活（C# P/Invoke）
# 被 qq-list.ps1 与 qq-send.ps1 点用（dot-source）
# ============================================================
Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class Win32QQ
{
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder sb, int max);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetActiveWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();

    public class WindowInfo
    {
        public IntPtr Hwnd;
        public int Pid;
        public string Title;
        public bool Visible;
    }

    public static List<WindowInfo> Collect()
    {
        var list = new List<WindowInfo>();
        EnumWindows((h, l) =>
        {
            uint pid;
            GetWindowThreadProcessId(h, out pid);
            var sb = new StringBuilder(512);
            GetWindowText(h, sb, 512);
            if (sb.Length > 0)
            {
                list.Add(new WindowInfo
                {
                    Hwnd = h,
                    Pid = (int)pid,
                    Title = sb.ToString(),
                    Visible = IsWindowVisible(h)
                });
            }
            return true;
        }, IntPtr.Zero);
        return list;
    }
}
"@ -ErrorAction SilentlyContinue

# 过滤掉 QQ 内部/系统隐藏窗口（IME、菜单、随机名等）
function Test-RealWindowTitle($title) {
    if ([string]::IsNullOrWhiteSpace($title)) { return $false }
    if ($title -match '^(Default IME|MSCTFIME UI|Sogou_TSF_UI|MyWing|TXMenuWindow|HintWnd|WndForAero|im event window|SecMyWing|Game<-->QQ Exchange Dlg)$') { return $false }
    if ($title -match '^[0-9A-Fa-f\-]{20,}$') { return $false }          # GUID 样式的窗口名
    if ($title -match '^Wnd_[0-9A-Fa-f\-]+$') { return $false }           # QQ 内部 Wnd_* 窗口
    if ($title -match '^[A-Za-z0-9]{10,}$') { return $false }            # 纯字母数字随机名
    if ($title -match '^(qqexchangewnd|QQ_\d+_)') { return $false }
    return $true
}

# 返回属于 QQ.exe 进程的顶层窗口列表（含句柄/标题/可见性，已过滤噪音）
function Get-QQWindows {
    $procs = @(Get-Process -Name 'QQ' -ErrorAction SilentlyContinue)
    if ($procs.Count -eq 0) { return @() }
    $pids = @($procs | ForEach-Object { $_.Id })
    $all = [Win32QQ]::Collect()
    $out = @()
    foreach ($w in $all) {
        if ($pids -contains $w.Pid -and (Test-RealWindowTitle $w.Title)) {
            $out += [pscustomobject]@{
                Hwnd    = $w.Hwnd.ToInt64()
                Pid     = $w.Pid
                Title   = $w.Title
                Visible = $w.Visible
            }
        }
    }
    return $out
}
