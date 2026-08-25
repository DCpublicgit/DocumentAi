Add-Type -AssemblyName System.Drawing

$srcPath = "C:\Document bot\Digital concept logo.jpg"
$outPath = "C:\Document bot\ui\public\logo-mark.png"

$src = [System.Drawing.Bitmap]::FromFile($srcPath)
Write-Output "Source size: $($src.Width) x $($src.Height)"

# Find bounding box of the cyan icon mark (distinct from black text / white bg)
$minX = $src.Width
$maxX = 0
$minY = $src.Height
$maxY = 0

for ($y = 0; $y -lt $src.Height; $y += 2) {
    for ($x = 0; $x -lt $src.Width; $x += 2) {
        $p = $src.GetPixel($x, $y)
        # cyan-ish: high G and B, lower R, and clearly not white/gray
        if ($p.G -gt 140 -and $p.B -gt 140 -and $p.R -lt 140 -and ($p.G - $p.R) -gt 40) {
            if ($x -lt $minX) { $minX = $x }
            if ($x -gt $maxX) { $maxX = $x }
            if ($y -lt $minY) { $minY = $y }
            if ($y -gt $maxY) { $maxY = $y }
        }
    }
}

Write-Output "Cyan bbox: X[$minX-$maxX] Y[$minY-$maxY]"

$pad = 14
$cropX = [Math]::Max(0, $minX - $pad)
$cropY = [Math]::Max(0, $minY - $pad)
$cropW = [Math]::Min($src.Width - $cropX, ($maxX - $minX) + 2 * $pad)
$cropH = [Math]::Min($src.Height - $cropY, ($maxY - $minY) + 2 * $pad)

Write-Output "Crop rect: $cropX,$cropY $cropW x $cropH"

$cropped = New-Object System.Drawing.Bitmap $cropW, $cropH
$g = [System.Drawing.Graphics]::FromImage($cropped)
$g.DrawImage($src, (New-Object System.Drawing.Rectangle 0, 0, $cropW, $cropH), (New-Object System.Drawing.Rectangle $cropX, $cropY, $cropW, $cropH), [System.Drawing.GraphicsUnit]::Pixel)
$g.Dispose()

# Chroma-key: make near-white pixels transparent
$result = New-Object System.Drawing.Bitmap $cropW, $cropH, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
for ($y = 0; $y -lt $cropH; $y++) {
    for ($x = 0; $x -lt $cropW; $x++) {
        $p = $cropped.GetPixel($x, $y)
        if ($p.R -gt 235 -and $p.G -gt 235 -and $p.B -gt 235) {
            $result.SetPixel($x, $y, [System.Drawing.Color]::FromArgb(0, 255, 255, 255))
        } else {
            $result.SetPixel($x, $y, $p)
        }
    }
}

$result.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output "Saved: $outPath"

$src.Dispose()
$cropped.Dispose()
$result.Dispose()
