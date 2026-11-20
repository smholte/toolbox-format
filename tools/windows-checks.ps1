# Toolbox format - Windows checks W1, W4, W5 (task 0010 of smholte/ToolBox).
# Works only inside %USERPROFILE%\Toolbox-check (made new, deleted at the end). Touches nothing else.
# Prints one line per check and copies the same text to the clipboard.
# Needs only Windows PowerShell 5.1 or newer (built into Windows). ASCII only: odd characters are built with [char].
$ErrorActionPreference = 'Continue'
$out = New-Object System.Collections.Generic.List[string]
function Say([string]$s) { $out.Add($s); Write-Host $s }

$root = Join-Path $env:USERPROFILE 'Toolbox-check'
if (Test-Path -LiteralPath $root) { Say "STOP: $root already exists. Delete or rename it, then run again."; return }
Say "Toolbox format Windows checks - $(Get-Date -Format s)"
Say ("Windows: " + [Environment]::OSVersion.VersionString + " | PowerShell " + $PSVersionTable.PSVersion + " | " + $PSVersionTable.PSEdition)
New-Item -ItemType Directory -Path $root | Out-Null

function Names([string]$dir) { @([IO.Directory]::GetFileSystemEntries($dir) | ForEach-Object { [IO.Path]::GetFileName($_) }) }

# ---------- W1: device-like names ----------
$sup1 = [string][char]0x00B9; $sup2 = [string][char]0x00B2; $sup3 = [string][char]0x00B3
$w1 = @('con .txt','COM0.txt','LPT0.txt',"COM$sup1.txt","COM$sup2.txt","COM$sup3.txt","LPT$sup1.txt","LPT$sup2.txt","LPT$sup3.txt",
        'CONIN$','CONOUT$','CLOCK$','con.txt.txt','aux')
$d1 = Join-Path $root 'w1'; New-Item -ItemType Directory -Path $d1 | Out-Null
foreach ($n in $w1) {
  $label = ($n.ToCharArray() | ForEach-Object { if ([int]$_ -gt 126) { 'U+{0:X4}' -f [int]$_ } else { [string]$_ } }) -join ''
  $p = Join-Path $d1 $n
  try {
    [IO.File]::WriteAllText($p, 'x')
    $seen = (Names $d1) -contains $n
    $readBack = $null; try { $readBack = [IO.File]::ReadAllText($p) } catch { $readBack = "read failed: $($_.Exception.Message)" }
    if ($seen -and $readBack -eq 'x') { Say "W1 $label : made a file (listed in the folder, read back)" }
    elseif ($seen) { Say "W1 $label : listed, but read back gave: $readBack" }
    else { Say "W1 $label : write said OK but NO file with that name in the folder (a device was probably opened)" }
  } catch { Say "W1 $label : refused: $($_.Exception.Message)" }
}

# ---------- W4: path longer than 260 ----------
$lp = $null; try { $lp = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -ErrorAction Stop).LongPathsEnabled } catch {}
Say "W4 long paths switched on in Windows (LongPathsEnabled): $(if ($null -eq $lp) { 'value not found' } else { $lp })"
$a = 'a' * 80; $b = 'b' * 64; $c = 'c' * 120
$dir = Join-Path $root "tools\$a\inbox\$b"
$file = Join-Path $dir "$c.txt"
Say "W4 path length: $($file.Length) characters"
$steps = @(
  @('make folders', { [void][IO.Directory]::CreateDirectory($dir) }),
  @('write', { [IO.File]::WriteAllText($file, 'long path ok') }),
  @('read', { if ([IO.File]::ReadAllText($file) -ne 'long path ok') { throw 'content differs' } }),
  @('delete', { [IO.File]::Delete($file) }))
foreach ($s in $steps) {
  try { & $s[1]; Say "W4 $($s[0]): ok" } catch { Say "W4 $($s[0]): refused: $($_.Exception.Message)"; break }
}
# the same with the \\?\ prefix, to know whether that works when the plain way did not
$ext = '\\?\' + $file
try {
  [void][IO.Directory]::CreateDirectory('\\?\' + $dir); [IO.File]::WriteAllText($ext, 'long path ok')
  $ok = [IO.File]::ReadAllText($ext) -eq 'long path ok'; [IO.File]::Delete($ext)
  Say "W4 with \\?\ prefix: write, read, delete $(if ($ok) { 'ok' } else { 'content differs' })"
} catch { Say "W4 with \\?\ prefix: refused: $($_.Exception.Message)" }

# ---------- W5: names that may be the same ----------
$pairs = @(
  @('long s / s',  ([string][char]0x017F + '.txt'), 's.txt'),
  @('micro / mu',  ([string][char]0x00B5 + '.txt'), ([string][char]0x03BC + '.txt')),
  @('dotless i / I', ([string][char]0x0131 + '.txt'), 'I.txt'),
  @('e-acute one char / e + accent', ([string][char]0x00E9 + '.txt'), ('e' + [char]0x0301 + '.txt')))
$i = 0
foreach ($pr in $pairs) {
  $i++; $d = Join-Path $root "w5-$i"; New-Item -ItemType Directory -Path $d | Out-Null
  try {
    [IO.File]::WriteAllText((Join-Path $d $pr[1]), 'first')
    [IO.File]::WriteAllText((Join-Path $d $pr[2]), 'second')
    $n = @(Names $d).Count
    $first = [IO.File]::ReadAllText((Join-Path $d $pr[1]))
    Say "W5 $($pr[0]): $(if ($n -eq 1) { "ONE file (the second write replaced the first; first name now reads '$first')" } else { "$n files (different names)" })"
  } catch { Say "W5 $($pr[0]): refused: $($_.Exception.Message)" }
}

# ---------- clean up ----------
try { Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction Stop } catch {
  try { cmd /c "rmdir /s /q `"\\?\$root`"" 2>$null } catch {} }
Say "Clean up: $(if (Test-Path -LiteralPath $root) { "FAILED - please delete $root by hand" } else { 'done, nothing left behind' })"
try { ($out -join "`r`n") | Set-Clipboard; Write-Host '(The text above is now on your clipboard - paste it into the chat.)' } catch {}
