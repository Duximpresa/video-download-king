# Video Download King 智能体指南

## 项目概况

Video Download King 是面向 64 位 Windows 11 的简体中文桌面视频下载器，当前版本为 `0.5.2`。

- 技术栈：Python 3.12、PySide6、yt-dlp、FFmpeg、FFprobe、Deno、PyInstaller。
- 当前平台范围：YouTube 单视频，以及抖音单视频/图集；批量页仅占位。
- 发布形式：便携 ZIP，主程序和全部运行时放在同一目录。
- 当前分支：`main`。
- 版本历史：参见 `CHANGELOG.md`。

不要把它改造成依赖系统 PATH、系统 FFmpeg 或 Python 环境的程序。便携运行是项目的核心约束。

## 常用命令

```powershell
# 安装开发依赖
python -m pip install -r requirements.txt

# 下载或补齐运行时
.\download_runtime.ps1

# 开发运行
python main.py

# 测试
python -m pytest -q

# 编译检查
python -m compileall -q video_download_king tests

# 构建发布包，版本号必须与代码版本一致
.\build_release.ps1 -Version 0.5.2
```

发布脚本会运行测试、使用 PyInstaller 构建无控制台窗口的目录版程序，并生成：

```text
release/VideoDownloadKing-v<版本>-Windows-x64.zip
```

## 目录与模块职责

```text
main.py                         程序入口
video_download_king/
  app.py                        QApplication、全局样式和主窗口启动
  main_window.py                主界面、UI 状态联动和 Qt 线程编排
  subtitle_dialog.py            人工/自动字幕搜索、多选和格式选择
  settings_dialog.py            代理、Cookie、网络超时设置
  douyin_page.py                抖音专用页面和 UI 状态
  douyin.py                     抖音接口、签名、资源选择和原子下载
  douyin_workers.py             抖音双引擎后台任务与回退编排
  models.py                     稳定的数据模型和任务结果类型
  config.py                     config/settings.json 的加载、迁移和恢复
  ytdlp.py                      分析、下载、字幕/封面和进度解析
  transcode.py                  FFprobe、转码决策、硬件探测和 FFmpeg 调用
  workers.py                    后台分析/下载任务及总任务进度映射
  processes.py                  隐藏窗口子进程、实时输出和取消
  formats.py                    yt-dlp 格式选择表达式
  paths.py                      开发态和冻结态的便携路径
  platforms.py                  平台识别及第一版范围校验
  utils.py                      文件名、日期、后缀和路径工具
tests/                          核心、进程、转码和 UI 测试
runtime/                        yt-dlp、FFmpeg、FFprobe、Deno
config/                         便携配置
downloads/                      默认下载目录
```

## 核心数据流

### 分析

1. `MainWindow` 根据当前网络设置创建 `DownloadRequest`。
2. `AnalyzeWorker` 在 `QThread` 中调用 `YtDlpService.analyze()`。
3. yt-dlp 使用 `--dump-single-json --skip-download` 返回媒体信息。
4. `MediaInfo` 保存格式、频道、日期、缩略图、人工字幕和自动字幕。
5. UI 填充视频流、音频流和字幕选择数据。

### 下载

1. UI 将输出模式、格式、命名、字幕和转码选择固化为 `DownloadRequest`。
2. `DownloadWorker` 负责平台目录、阶段映射、GPU 失败询问和最终结果。
3. `YtDlpService` 使用参数数组调用 yt-dlp，不使用 Shell 命令拼接。
4. 视频和音频流的进度由 `DownloadProgressTracker` 聚合，不能在第二条流开始时倒退。
5. 封面、人工字幕和自动字幕分别下载；附属文件失败只记录警告。
6. 必要时进入 FFprobe 检测和 FFmpeg 兼容 MP4 流程。

### 转码

`FFmpegService.decide_action()` 根据实际文件决定：

- 已是 MP4 + H.264 + AAC：不处理。
- H.264 + AAC 但不是 MP4：无损重封装。
- 只有一个流不兼容：复制兼容流，只重编码不兼容流。
- 视频和音频均不兼容：转为 H.264 + AAC MP4。

转码先写临时文件，通过 FFprobe 验证后再原子替换。失败时必须保留源文件，不得留下伪成功文件。

## 不可破坏的约束

- 所有外部程序必须通过 `ProcessRunner` 或同等隐藏窗口参数启动，不能弹出 CMD。
- 子进程参数必须使用数组传递，禁止拼接 Shell 命令。
- `runtime/` 路径由 `paths.py` 解析，开发态和 PyInstaller 冻结态都必须可用。
- 配置必须写入程序目录的 `config/settings.json`；代理密码不得持久化。
- 配置损坏时备份为 `settings.json.corrupt-*` 并恢复默认值。
- 文件名必须清理 Windows 非法字符；重复文件必须追加序号，不能静默覆盖。
- “仅封面”不能携带媒体格式参数，也不能触发转码。
- 字幕必须由分析结果选择，人工和自动字幕来源要明确区分。
- 同一语言的人工和自动字幕互斥，人工字幕优先。
- 字幕或封面失败不能把主视频任务判为失败。
- UI 不直接解析 yt-dlp/FFmpeg 文本；服务层负责转换为 `TaskProgress`。
- Qt 主线程不得执行下载、分析、探测或转码等长任务。
- GPU 厂商必须通过实际短片试编码后才能在 UI 中启用。
- GPU 实际转码失败时询问用户是否回退 CPU，不能静默改变选择。

## 进度规则

主界面有两条进度条：

- 总任务：下载、合并、附属文件和转码的统一进度。
- 当前阶段：当前媒体流或转码阶段的真实进度。

有转码时，总任务区间为：

- 媒体下载：`0–70%`
- 合并和附属文件：`70–80%`
- 转码：`80–100%`

无转码时：

- 媒体下载：`0–85%`
- 合并和附属文件：`85–100%`

合并、检测等无法计算百分比的阶段使用忙碌状态。修改进度逻辑时必须验证总进度单调不下降。

## 字幕规则

- `MediaInfo.subtitle_options` 将 yt-dlp 的 `subtitles` 和 `automatic_captions` 转为 `SubtitleInfo`。
- `SubtitleDialog` 默认显示全部人工字幕，以及中文、英文自动字幕。
- 其他自动字幕通过搜索或“显示全部自动字幕”展示。
- 默认不自动勾选任何字幕。
- 具体语言选择不持久化；只保存输出格式和“显示全部”偏好。
- SRT：`--sub-format srt/best --convert-subs srt`。
- VTT：`--sub-format vtt/best`，不执行格式转换。
- 人工字幕使用 `--write-subs`，自动字幕使用 `--write-auto-subs`，两类必须分开调用。

## 自动转码规则

自动转换为 H.264 时，按源编码和处理器补偿源码率：

| 源编码 | CPU | GPU |
| --- | ---: | ---: |
| H.264/AVC | 1.0x | 1.0x |
| VP8 | 1.3x | 1.3x |
| VP9 | 1.8x | 2.0x |
| HEVC/H.265 | 2.0x | 2.2x |
| AV1 | 2.0x | 2.2x |
| MPEG-4 Part 2 / MPEG-2 | 1.0x | 1.0x |

未知编码使用受约束质量模式，质量值 23，并设置 `maxrate`/`bufsize` 防止体积失控。用户手动选择恒定质量时不要套用自动体积保护。

## 测试与验收

提交前至少运行：

```powershell
python -m pytest -q
python -m compileall -q video_download_king tests
git diff --check
```

当前测试覆盖：

- 代理 URL、配置迁移和损坏恢复。
- 格式预设、输出模式和命名。
- 隐藏窗口子进程。
- 转码决策、编码感知码率和未知编码保护。
- 字幕分组、SRT/VTT 命令和人工/自动互斥。
- 双流下载进度聚合和未知文件大小。
- 数字框样式、仅封面联动和双进度条。

正式发布还应验证：

- 真实 YouTube 分析和视频+音频下载。
- 人工字幕下载；自动字幕可能因 YouTube HTTP 429 失败，应只产生警告。
- CPU 与本机可用硬件编码器转码。
- 打包 EXE 启动、中文路径、配置记忆和便携 ZIP。

## 版本与发布

修改版本时同步更新：

- `video_download_king/__init__.py`
- `pyproject.toml`
- `build_release.ps1`
- `README.md`
- `CHANGELOG.md`

发布包不提交到 Git；`release/`、`dist/`、`build/` 已被忽略。根目录 `VideoDownloadKing.spec` 是受控的 PyInstaller 构建配置，需要提交；其他临时生成的 `.spec` 仍按忽略处理。发布后记录 ZIP 大小和 SHA256，并创建独立版本提交。

## 当前范围与后续方向

当前明确不支持：播放列表、直播、并发下载、字幕嵌入、批量任务和自动更新。

批量功能应复用现有 `DownloadRequest`、worker 和服务层，不要在批量页复制下载逻辑。扩展其他平台时，应先扩展 `platforms.py` 和平台能力边界，再复用 yt-dlp 服务。

## 已知注意事项

- PowerShell 控制台可能错误显示 UTF-8 中文；内容校验应使用明确的 UTF-8 读取。
- 默认文件名包含方括号，回查文件时不要用未转义的 `glob()` 模式，应使用安全的前缀比较。
- yt-dlp 的 `--print` 会影响进度输出，下载命令必须显式带 `--progress`。
- YouTube 自动字幕数量可能超过百种，不能在主界面直接全部展开。
- 自动字幕下载可能遇到 HTTP 429；不要因此删除已下载主视频。
- 不要提交 `config/settings.json`、下载文件、构建目录或第三方大体积运行时更新，除非用户明确要求。
