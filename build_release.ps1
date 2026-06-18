param(
    [string]$Version = "0.5.2"
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

function Remove-PackageItem {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Path
    )

    if (Test-Path $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Optimize-QtPackage {
    param(
        [Parameter(Mandatory=$true)]
        [string]$PackageDir
    )

    $PySideDir = Join-Path $PackageDir "_internal\PySide6"
    if (-not (Test-Path $PySideDir)) {
        return
    }

    Remove-PackageItem (Join-Path $PySideDir "translations")
    Remove-PackageItem (Join-Path $PySideDir "opengl32sw.dll")
    Remove-PackageItem (Join-Path $PySideDir "Qt6Quick.dll")
    Remove-PackageItem (Join-Path $PySideDir "Qt6Qml.dll")
    Remove-PackageItem (Join-Path $PySideDir "Qt6QmlMeta.dll")
    Remove-PackageItem (Join-Path $PySideDir "Qt6QmlModels.dll")
    Remove-PackageItem (Join-Path $PySideDir "Qt6QmlWorkerScript.dll")
    Remove-PackageItem (Join-Path $PySideDir "Qt6Pdf.dll")

    $PlatformsDir = Join-Path $PySideDir "plugins\platforms"
    if (Test-Path $PlatformsDir) {
        Get-ChildItem -LiteralPath $PlatformsDir -File |
            Where-Object { $_.Name -ne "qwindows.dll" } |
            Remove-Item -Force
    }
}

python -m pytest
python -m PyInstaller --noconfirm --clean VideoDownloadKing.spec

$PackageName = "VideoDownloadKing-v$Version-Windows-x64"
$PackageDir = Join-Path $Root "release\$PackageName"
$Archive = Join-Path $Root "release\$PackageName.zip"
Remove-Item -Recurse -Force $PackageDir -ErrorAction SilentlyContinue
Remove-Item -Force $Archive -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $PackageDir | Out-Null

Copy-Item "dist\VideoDownloadKing\*" $PackageDir -Recurse
Optimize-QtPackage $PackageDir
Copy-Item "runtime" $PackageDir -Recurse
Copy-Item "README.md","THIRD_PARTY_NOTICES.md" $PackageDir
New-Item -ItemType Directory -Force (Join-Path $PackageDir "config"),(Join-Path $PackageDir "downloads") | Out-Null
Compress-Archive -Path "$PackageDir\*" -DestinationPath $Archive -CompressionLevel Optimal
Write-Host "Release created: $Archive"
