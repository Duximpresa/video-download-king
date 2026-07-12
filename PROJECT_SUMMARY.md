# Video Download King 项目总结

## 项目定位

Video Download King 是一个面向 64 位 Windows 11 的简体中文桌面视频下载器。项目当前版本为 `0.5.2`，核心目标是提供可直接解压运行的便携式下载工具，不依赖用户系统 PATH、系统 FFmpeg 或本机 Python 环境。

当前支持范围包括：

- YouTube 单视频分析与下载。
- 抖音单视频、图集、短链接和分享文本解析下载。
- 视频、音频、封面、字幕和兼容 MP4 输出。
- 便携 ZIP 发布，主程序、运行时、配置和默认下载目录位于同一应用目录体系内。

## 技术栈

- Python 3.12
- PySide6 桌面界面
- yt-dlp 视频分析与下载
- FFmpeg / FFprobe 媒体检测、重封装和转码
- Deno 作为 yt-dlp 处理 YouTube JavaScript 挑战的运行时
- PyInstaller 生成 Windows 目录版程序和便携 ZIP
- pytest 覆盖核心逻辑、转码、进程、抖音和 UI 行为

## 核心功能

### 单链接下载

单链接页主要面向 YouTube 单视频：

- 支持视频+音频、仅视频、仅音频、仅封面和高级流组合。
- 支持画质预设、手动选择视频流和音频流。
- 支持 `cookies.txt` 或 Chrome / Edge Cookie。
- 支持代理、网络超时和便携配置保存。
- 支持自定义命名模板。
- 支持封面下载、人工字幕和自动字幕下载。
- 支持 SRT / VTT 字幕格式选择。

### 抖音下载

抖音页是 `0.5.0` 的重点能力：

- 支持抖音单视频、图集、短链接和分享文本。
- 视频可使用自研抖音引擎或 `yt-dlp` 引擎。
- 图集固定使用自研引擎，支持原图和实况片段。
- 自研引擎支持 A-Bogus / X-Bogus、随机 msToken、多接口重试和无水印资源优先。
- 支持独立抖音 Netscape `cookies.txt`。
- 支持按平台分类和按作者分类保存，组合路径为 `Douyin/作者名`。
- 支持抖音实用命名字段：`{author}`、`{type}`、`{index}`、`{asset}`。

### 兼容 MP4

项目提供统一的兼容 MP4 能力：

- 已是 MP4 + H.264 + AAC 时直接保留。
- H.264 + AAC 但容器不是 MP4 时无损重封装。
- 单个流不兼容时只重编码不兼容流。
- 视频和音频都不兼容时转为 H.264 + AAC MP4。
- 支持 CPU 和 GPU 编码器选择。
- GPU 厂商包括 NVIDIA NVENC、Intel QSV 和 AMD AMF。
- GPU 必须通过实际短片试编码后才在 UI 中启用。
- GPU 实际转码失败时询问用户是否回退 CPU。

兼容 MP4 UI 已抽为共享模块，单链接页和抖音页复用同一套配置组件，避免重复造轮子。

## 主要模块

```text
main.py                         程序入口
video_download_king/app.py      QApplication、全局样式和主窗口启动
video_download_king/main_window.py   YouTube/X 单链接页面与主窗口
                                单链接页、主窗口、线程编排和 UI 状态联动
video_download_king/douyin_page.py
                                抖音下载页和抖音 UI 状态
video_download_king/transcode_panel.py
                                可复用兼容 MP4 配置面板
video_download_king/douyin.py   抖音接口、签名、资源选择和原子下载
video_download_king/bilibili.py B站 WBI/DASH、分片下载、附属文件和无转码合并
video_download_king/bilibili_page.py  独立 B站下载页面
video_download_king/bilibili_workers.py  B站后台任务
video_download_king/douyin_workers.py
                                抖音双引擎后台任务和失败回退编排
video_download_king/ytdlp.py    yt-dlp 分析、下载、字幕/封面和进度解析
video_download_king/transcode.py
                                FFprobe、转码决策、硬件探测和 FFmpeg 调用
video_download_king/workers.py  YouTube 分析/下载后台任务和进度映射
video_download_king/processes.py
                                隐藏窗口子进程、实时输出和取消
video_download_king/models.py   稳定数据模型和任务结果类型
video_download_king/config.py   config/settings.json 加载、迁移和恢复
video_download_king/paths.py    开发态和 PyInstaller 冻结态便携路径
video_download_king/utils.py    文件名、日期、后缀和路径工具
tests/                          自动化测试
runtime/                        yt-dlp、FFmpeg、FFprobe、Deno
config/                         便携配置
downloads/                      默认下载目录
```

## 数据流概览

### 分析流程

1. UI 根据当前输入和网络设置创建请求对象。
2. 后台 worker 在 `QThread` 中执行分析，避免阻塞 Qt 主线程。
3. YouTube 路径调用 `YtDlpService.analyze()`。
4. 抖音路径根据引擎选择调用 `DouyinService` 或 `YtDlpService`。
5. 分析结果转为稳定的 `MediaInfo` 或 `DouyinMediaInfo`。
6. UI 填充作品信息、格式选择、字幕选项和文件名预览。

### 下载流程

1. UI 将输出模式、格式、命名、字幕、封面和转码选择固化为请求对象。
2. worker 负责目录分类、阶段映射、失败回退询问和结果汇总。
3. 服务层使用参数数组启动 yt-dlp / FFmpeg，不拼接 Shell 命令。
4. 进度由服务层解析为 `TaskProgress`，UI 不直接解析外部程序文本。
5. 主媒体失败会导致任务失败；封面、字幕等附属文件失败只记录警告。
6. 必要时进入 FFprobe 检测和 FFmpeg 兼容 MP4 流程。

## 便携运行约束

项目最重要的工程约束是便携运行：

- 外部程序必须从 `runtime/` 或冻结态应用目录解析。
- 不依赖系统 PATH。
- 不要求用户安装 FFmpeg、yt-dlp、Deno 或 Python。
- 配置写入程序目录下的 `config/settings.json`。
- 代理密码只保存在当前进程中，不持久化到磁盘。
- 配置损坏时备份为 `settings.json.corrupt-*` 并恢复默认值。
- 子进程必须隐藏窗口启动，不能弹出 CMD。
- 所有外部命令参数必须使用数组传递。

## 构建与发布

开发运行：

```powershell
python -m pip install -r requirements.txt
.\download_runtime.ps1
python main.py
```

测试与编译检查：

```powershell
python -m pytest -q
python -m compileall -q video_download_king tests
git diff --check
```

构建发布包：

```powershell
.\build_release.ps1 -Version 0.5.2
```

发布脚本会运行测试、使用 PyInstaller 构建无控制台窗口的目录版程序，并生成：

```text
release/VideoDownloadKing-v0.5.2-Windows-x64.zip
```

发布包和构建目录不提交到 Git。根目录 `VideoDownloadKing.spec` 是受控的 PyInstaller 构建配置，需要提交。

## 当前版本状态

`0.5.2` 已完成：

- 分析链接时显示忙碌进度并支持取消。
- 分析取消后按正常取消状态收尾，不弹出失败对话框。
- YouTube、Instagram、X 链接在直连模式下提示潜在网络问题。
- 代理设置支持自定义网址的异步连通性测试。
- 720p / 1080p 窗口滚动适配。
- PyInstaller 固定 spec 构建。
- Qt 发布包裁剪和 ZIP 体积优化。
- 抖音独立下载页。
- 抖音双引擎视频下载。
- 抖音图集下载。
- 抖音 cookies.txt 配置。
- 抖音按作者分类保存。
- 抖音命名模板增强。
- 兼容 MP4 面板模块化复用。
- 便携 ZIP 发布。

## 暂不支持

当前明确不支持：

- 播放列表
- 直播
- 抖音主页、合集、音乐页批量下载
- 并发下载
- 字幕嵌入
- 批量任务
- 自动更新

这些方向适合后续版本在复用现有 `DownloadRequest`、worker 和服务层的基础上逐步扩展，不应在批量页复制一套新的下载逻辑。

## 维护建议

- 修改版本时同步更新 `video_download_king/__init__.py`、`pyproject.toml`、`build_release.ps1`、`README.md` 和 `CHANGELOG.md`。
- 修改进度逻辑时必须验证总进度单调不下降。
- 修改字幕逻辑时必须保持人工字幕和自动字幕来源区分，并保证同一语言互斥。
- 修改转码逻辑时必须保证失败保留源文件，不留下伪成功输出。
- 扩展平台时应先扩展 `platforms.py` 的平台识别和能力边界，再复用服务层与 worker。
- Windows 控制台可能错误显示 UTF-8 中文，校验中文文本时应以明确 UTF-8 读取为准。
