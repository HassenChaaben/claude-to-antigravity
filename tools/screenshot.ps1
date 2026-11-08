# Save a screenshot of the whole primary screen (used for the README proofs).
#   powershell -ExecutionPolicy Bypass -File tools\screenshot.ps1 -Out docs\assets\shot.png [-Region "x,y,w,h"]
param([Parameter(Mandatory = $true)][string]$Out, [string]$Region = "")
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
if ($Region) { $r = $Region.Split(",") | ForEach-Object { [int]$_ }; $b = New-Object System.Drawing.Rectangle $r[0], $r[1], $r[2], $r[3] }
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "saved $Out ($($b.Width)x$($b.Height))"
