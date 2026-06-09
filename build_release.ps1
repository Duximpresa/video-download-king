param(
    [string]$Version = "0.3.0"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$PythonPrefix = (python -c "import sys; print(sys.prefix)").Trim()
$PythonLibraryBin = Join-Path $PythonPrefix "Library\bin"
if (Test-Path $PythonLibraryBin) {
    $env:PATH = "$PythonLibraryBin;$env:PATH"
}

$Required = @(
    "runtime\yt-dlp\yt-dlp.exe",
    "runtime\ffmpeg\bin\ffmpeg.exe",
    "runtime\ffmpeg\bin\ffprobe.exe",
    "runtime\deno\deno.exe"
)
foreach ($Item in $Required) {
    if (-not (Test-Path $Item)) {
        throw "Missing runtime file: $Item"
    }
}

python -m pytest
python -m PyInstaller --noconfirm --clean --windowed --name VideoDownloadKing `
    --add-data "video_download_king\assets;video_download_king\assets" main.py

$PackageName = "VideoDownloadKing-v$Version-Windows-x64"
$PackageDir = Join-Path $Root "release\$PackageName"
$Archive = Join-Path $Root "release\$PackageName.zip"
Remove-Item -Recurse -Force $PackageDir -ErrorAction SilentlyContinue
Remove-Item -Force $Archive -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $PackageDir | Out-Null

Copy-Item "dist\VideoDownloadKing\*" $PackageDir -Recurse
Copy-Item "runtime" $PackageDir -Recurse
Copy-Item "README.md","THIRD_PARTY_NOTICES.md" $PackageDir
New-Item -ItemType Directory -Force (Join-Path $PackageDir "config"),(Join-Path $PackageDir "downloads") | Out-Null
Compress-Archive -Path "$PackageDir\*" -DestinationPath $Archive -CompressionLevel Optimal
Write-Host "Release created: $Archive"
