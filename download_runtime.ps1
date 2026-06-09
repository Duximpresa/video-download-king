param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$TempRoot = Join-Path $env:TEMP "video-download-king-runtime"
New-Item -ItemType Directory -Force $TempRoot | Out-Null

function Download-File {
    param([string]$Url, [string]$Destination)
    if ((Test-Path $Destination) -and -not $Force) {
        Write-Host "Exists, skipping: $Destination"
        return
    }
    New-Item -ItemType Directory -Force (Split-Path -Parent $Destination) | Out-Null
    curl.exe -L --fail --retry 3 -o $Destination $Url
}

Download-File `
    "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" `
    (Join-Path $Root "runtime\yt-dlp\yt-dlp.exe")

$DenoZip = Join-Path $TempRoot "deno.zip"
Download-File `
    "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" `
    $DenoZip
$DenoExtract = Join-Path $TempRoot "deno"
Remove-Item -Recurse -Force $DenoExtract -ErrorAction SilentlyContinue
Expand-Archive -LiteralPath $DenoZip -DestinationPath $DenoExtract -Force
New-Item -ItemType Directory -Force (Join-Path $Root "runtime\deno") | Out-Null
Copy-Item (Join-Path $DenoExtract "deno.exe") (Join-Path $Root "runtime\deno\deno.exe") -Force

$FFmpegZip = Join-Path $TempRoot "ffmpeg.zip"
Download-File `
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" `
    $FFmpegZip
$FFmpegExtract = Join-Path $TempRoot "ffmpeg"
Remove-Item -Recurse -Force $FFmpegExtract -ErrorAction SilentlyContinue
Expand-Archive -LiteralPath $FFmpegZip -DestinationPath $FFmpegExtract -Force
$FFmpegSource = Get-ChildItem $FFmpegExtract -Directory | Select-Object -First 1
if (-not $FFmpegSource) {
    throw "FFmpeg archive did not contain a build directory"
}
$FFmpegTarget = Join-Path $Root "runtime\ffmpeg"
Remove-Item -Recurse -Force $FFmpegTarget -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $FFmpegTarget | Out-Null
Copy-Item (Join-Path $FFmpegSource.FullName "bin") $FFmpegTarget -Recurse
Remove-Item (Join-Path $FFmpegTarget "bin\ffplay.exe") -Force -ErrorAction SilentlyContinue
Get-ChildItem $FFmpegSource.FullName -File |
    Where-Object { $_.Name -match "LICENSE|README" } |
    Copy-Item -Destination $FFmpegTarget

& (Join-Path $Root "runtime\yt-dlp\yt-dlp.exe") --version
& (Join-Path $Root "runtime\deno\deno.exe") --version
& (Join-Path $Root "runtime\ffmpeg\bin\ffmpeg.exe") -version
Write-Host "Runtime download complete."

