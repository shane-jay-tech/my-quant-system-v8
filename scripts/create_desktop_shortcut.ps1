$desktop = [Environment]::GetFolderPath('Desktop')

# Filename via Unicode codepoints (avoid UTF-8/GBK mangling on Chinese Windows)
# Resolves to: 6-char Chinese name "Quant Stock Picker"
$nameChars = 0x91CF, 0x5316, 0x9009, 0x80A1, 0x7CFB, 0x7EDF
$name = -join ($nameChars | ForEach-Object { [char]$_ })
$shortcutPath = Join-Path $desktop ($name + '.lnk')

# Remove old shortcut if present
if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath -Force }

# Locate pythonw.exe — prefer user-level Python install
$pythonw = $null
$candidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe"
)
foreach ($c in $candidates) {
    if (Test-Path -LiteralPath $c) { $pythonw = $c; break }
}
if (-not $pythonw) {
    $cmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
    if ($cmd) { $pythonw = $cmd.Source }
}
if (-not $pythonw) {
    Write-Error "pythonw.exe not found"
    exit 1
}

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($shortcutPath)
$sc.TargetPath = $pythonw
$sc.Arguments = '"D:\code\my-quant-system-v8\launcher.pyw"'
$sc.WorkingDirectory = 'D:\code\my-quant-system-v8'
$sc.IconLocation = 'D:\code\my-quant-system-v8\assets\app.ico,0'
# Description: "Quant Stock Picker - Desktop App" via codepoints
$descChars = 0x91CF, 0x5316, 0x9009, 0x80A1, 0x7CFB, 0x7EDF,
             0x0020, 0x002D, 0x0020, 0x684C, 0x9762, 0x7AEF, 0x5E94, 0x7528
$sc.Description = -join ($descChars | ForEach-Object { [char]$_ })
$sc.WindowStyle = 1
$sc.Save()

[Console]::OutputEncoding = [Text.Encoding]::UTF8
Write-Host ('Created: ' + $shortcutPath)
Write-Host ('Target:  ' + $pythonw)
Write-Host ('Args:    "D:\code\my-quant-system-v8\launcher.pyw"')
Write-Host ('Icon:    D:\code\my-quant-system-v8\assets\app.ico')
Write-Host ('Exists:  ' + (Test-Path -LiteralPath $shortcutPath))
