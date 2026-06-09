# Video Download King 0.3.0

面向 Windows 11 的中文桌面视频下载器。第一版围绕 `yt-dlp.exe` 实现 YouTube 单视频分析和下载，并使用 FFmpeg 自动输出兼容的 H.264 + AAC MP4。

## 第一版功能

- YouTube 单链接分析与下载
- 视频+音频、仅视频、仅音频和高级流组合
- 最高、2160p、1440p、1080p、720p、480p、最低和自定义画质
- 视频流与音频流高级组合
- 原始音频、AAC、M4A、MP3 输出
- HTTP、HTTPS、SOCKS4、SOCKS5 代理
- `cookies.txt` 或 Chrome/Edge Cookie
- 按 `YouTube` 子目录自动分类
- 自动检测 NVENC、QSV、AMF，失败回退 CPU
- CPU/GPU 和硬件厂商手动选择，不支持的硬件自动禁用
- 按源视频实际码率自动设置转码码率
- 视频标题、ID、频道、平台和日期自定义命名
- 独立封面下载模式，以及可选封面、字幕附属文件下载
- 编码感知的 H.264 自动码率与未知编码体积保护
- 自动编码后缀或自定义转码文件后缀
- H.264 + AAC 文件直接保留，兼容流重封装，不兼容流按需转码
- 保存路径和设置便携记忆
- 批量下载页面占位

## 开发运行

环境要求：64 位 Windows 11、Python 3.12。

```powershell
python -m pip install -r requirements.txt
.\download_runtime.ps1
python main.py
```

也可双击 `run.bat`。

## 运行时目录

```text
runtime/
  yt-dlp/yt-dlp.exe
  ffmpeg/bin/ffmpeg.exe
  ffmpeg/bin/ffprobe.exe
  deno/deno.exe
```

配置写入 `config/settings.json`。代理密码只保存在当前进程内，不写入该文件。

Deno 是 yt-dlp 官方推荐的 YouTube JavaScript 挑战运行时，程序会自动使用随附版本。

## 构建便携版

```powershell
.\build_release.ps1 -Version 0.3.0
```

脚本会先运行测试，再使用 PyInstaller 生成目录版程序，并创建：

```text
release/VideoDownloadKing-v0.3.0-Windows-x64.zip
```

## 使用说明

1. 输入 YouTube 单视频链接并点击“分析链接”。
2. 选择“视频+音频”“仅视频”“仅音频”“仅封面”或“高级流组合”。
3. 可使用 `{title}`、`{id}`、`{channel}`、`{platform}`、`{upload_date}`、`{download_date}` 自定义文件名。
4. 按需勾选下载封面或下载字幕；也可选择“仅封面”模式。默认字幕语言为 `zh-Hans,zh.*,en.*`。
5. 兼容 MP4 区域可选择 CPU 或 GPU。GPU 厂商必须通过启动时实际编码检测才可选择。
6. 自动码率按源编码与 CPU/GPU 类型补偿；未知编码使用质量模式和码率上限保护。转码文件默认追加 `_H264_AAC`。
7. 点击“开始下载”。若用户选择的 GPU 在实际视频上失败，程序会询问是否使用 CPU 继续。
8. 登录限制视频可在设置中选择 Cookie 文件，或尝试从 Chrome/Edge 读取登录状态。

下载、分析、转码和取消操作均以隐藏窗口方式运行，不会弹出 CMD 窗口。

请遵守网站服务条款、版权规则和所在地法律，只下载你有权保存的内容。

## 暂不支持

播放列表、直播、并发下载、字幕嵌入、批量任务和自动更新将在后续版本评估。
