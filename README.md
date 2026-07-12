# Video Download King 0.6.0

面向 Windows 11 的中文桌面视频下载器。支持 YouTube 单视频、X 单条视频帖子、哔哩哔哩单稿件/多分P，以及抖音单视频和图集。YouTube 与 X 使用 `yt-dlp`，B站和抖音提供独立自研下载引擎。

项目维护与智能体交接参见 [AGENTS.md](AGENTS.md)，逐版本变更参见 [CHANGELOG.md](CHANGELOG.md)。

## 第一版功能

- 主界面页面支持垂直滚动，窗口高度不足时仍可访问底部控件，最低适配 1280x720 使用场景
- 发布构建使用固定 PyInstaller spec，并裁剪未使用的 Qt Quick/QML/Pdf/translations 文件以减小 ZIP 体积
- 独立“抖音下载”页面，支持视频、图集、短链接和分享文本
- 抖音视频可选择自研引擎或 `yt-dlp`，失败时询问是否切换
- 自研引擎优先选择无水印高画质资源，并支持图集及实况片段
- 抖音独立 Netscape `cookies.txt` 设置

- 独立“B站下载”页面，不调用 `yt-dlp`
- 支持 BV、AV、`b23.tv`、分享文本及多分P勾选
- WBI 接口解析、DASH 选流、4路 Range 分片、备用 CDN 和断线重试
- 可选择画质、AVC/HEVC/AV1 编码和音质，使用便携 FFmpeg 无转码合并
- 可选封面 JPG、字幕 SRT、弹幕 ASS 和元数据 NFO
- B站独立 Netscape `cookies.txt`，仅使用账号正常拥有的播放权限

- YouTube 单视频与 X 单条帖子分析下载
- 视频+音频、仅视频、仅音频和高级流组合
- 最高、2160p、1440p、1080p、720p、480p、最低和自定义画质
- 视频流与音频流高级组合
- 原始音频、AAC、M4A、MP3 输出
- HTTP、HTTPS、SOCKS4、SOCKS5 代理
- `cookies.txt` 或 Chrome/Edge Cookie
- 按平台子目录自动分类
- 自动检测硬件解码、硬件滤镜和 NVENC/QSV/AMF 编码，失败回退 CPU
- 图像比例、竖构图、旋转、镜像、显示比例和禁止放大
- VBR、CBR、CQ，以及 Shutter Encoder 风格的 `auto`、好的、最好码率档位
- 最大码率、目标文件大小、二次编码和最高质量
- AAC、MP3、AC3、声道及采样率转换
- 视频标题、ID、频道、平台和日期自定义命名
- 独立封面下载模式，以及可选封面、字幕附属文件下载
- 总任务与当前阶段双进度条，显示下载流、速度、大小和 ETA
- 分析链接时显示忙碌进度，可随时取消卡住的分析任务
- YouTube、Instagram、X 链接在未配置代理时提示潜在网络问题
- 代理设置支持自定义网址的异步网络连通性测试
- 分析后按人工/自动来源选择字幕，支持多选及 SRT/VTT
- 自动编码后缀或自定义转码文件后缀
- 满足当前图像、音频和 H.264 MP4 设置的文件直接保留，兼容流按需复制
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
.\build_release.ps1 -Version 0.6.0
```

脚本会先运行测试，再使用 PyInstaller 生成目录版程序，并创建：

```text
release/VideoDownloadKing-v0.6.0-Windows-x64.zip
```

## 使用说明

抖音下载：

1. 打开“抖音下载”页，粘贴视频/图集链接、短链接或分享文本。
2. 视频默认使用自研引擎，也可切换为 `yt-dlp`；图集固定使用自研引擎。
3. 选择画质、命名和封面选项后开始下载；抖音页面不执行额外视频编码。
4. 风控或受限作品可在“设置 > 抖音登录”选择 Netscape `cookies.txt`。

单链接下载：

1. 输入 YouTube 单视频，或 `x.com` / `twitter.com` 单条帖子及其 `/video/序号` 链接并点击“分析链接”。
2. 选择“视频+音频”“仅视频”“仅音频”“仅封面”或“高级流组合”。
3. 可使用 `{title}`、`{id}`、`{channel}`、`{platform}`、`{upload_date}`、`{download_date}` 自定义文件名。
4. 分析完成后点击“选择字幕”，可搜索并多选人工或自动字幕，同时选择 SRT/VTT 输出格式。

B站下载：

1. 打开“B站下载”页，粘贴 BV、AV、`b23.tv` 链接或分享文本并分析。
2. 多分P稿件默认选中链接指定P（没有指定则为P1），可继续勾选多个分P。
3. 选择画质、编码、音质、命名模板和附属文件后开始下载；B站页面只做音视频无转码合并。
4. 1080P+、会员或受限内容需在“设置 > B站登录”选择最新导出的 Netscape `cookies.txt`。
5. “视频编码”区域依次提供图像、比特率调整、音频设置、硬件加速和文件选项。
6. VBR/CBR 可输入码率或选择 `auto`、好的、最好；CQ 使用 1–51 的质量值。转码文件默认追加编码后缀。
7. 点击“开始下载”。若用户选择的 GPU 在实际视频上失败，程序会询问是否使用 CPU 继续。
8. 登录限制视频可在设置中选择 Cookie 文件，或尝试从 Chrome/Edge 读取登录状态。

下载、分析、转码和取消操作均以隐藏窗口方式运行，不会弹出 CMD 窗口。

请遵守网站服务条款、版权规则和所在地法律，只下载你有权保存的内容。

## 暂不支持

播放列表、B站合集/番剧/课程/直播/互动视频、抖音主页/合集/音乐/直播、并发任务、字幕嵌入、批量任务和自动更新将在后续版本评估。
