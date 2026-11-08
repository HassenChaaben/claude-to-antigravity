# Save a picture of ONE window (not the whole screen), even if other windows cover it.
#   powershell -ExecutionPolicy Bypass -File tools\capture_window.ps1 -Out shot.png -Process Antigravity
#   powershell -ExecutionPolicy Bypass -File tools\capture_window.ps1 -Out shot.png -Hwnd 123456
# Used for the README proofs, so no private window content ends up in a screenshot by accident.
param([Parameter(Mandatory = $true)][string]$Out, [string]$Process = "", [long]$Hwnd = 0)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Win {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
[void][Win]::SetProcessDPIAware()
if ($Process) {
  $p = Get-Process -Name $Process -ErrorAction Stop | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
  if (-not $p) { Write-Error "no visible window for process $Process"; exit 1 }
  $Hwnd = [long]$p.MainWindowHandle
}
$h = [IntPtr]$Hwnd
$r = New-Object Win+RECT
[void][Win]::GetWindowRect($h, [ref]$r)
$w = $r.R - $r.L; $ht = $r.B - $r.T
if ($w -le 0 -or $ht -le 0) { Write-Error "window has no size (minimized?)"; exit 1 }
$bmp = New-Object System.Drawing.Bitmap $w, $ht
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
[void][Win]::PrintWindow($h, $hdc, 2)   # 2 = PW_RENDERFULLCONTENT (works for GPU-drawn apps)
$g.ReleaseHdc($hdc)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "saved $Out (${w}x${ht})"
