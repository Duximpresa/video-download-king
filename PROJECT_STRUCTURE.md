# Video Download King 项目目录与文件职责说明

本文档说明项目中各目录存放的内容、存在目的，以及各文件负责的功能。内容以当前仓库和本地工作区为准。

## 1. 项目结构总览

```text
video-download-king/
├─ video_download_king/       程序核心 Python 包
├─ tests/                     自动化测试
├─ runtime/                   便携版随附的第三方可执行程序
├─ branding/                  Logo 原稿、母版和各平台导出资源
├─ tools/                     开发和资源生成工具
├─ config/                    用户便携配置
├─ downloads/                 默认下载目录
├─ build/                     PyInstaller 临时构建目录
├─ dist/                      PyInstaller 未压缩输出目录
├─ release/                   最终便携目录和 ZIP 发布包
├─ .vscode/                   本机 VS Code 工作区设置
├─ main.py                    程序入口
├─ VideoDownloadKing.spec     PyInstaller 受控构建配置
└─ 其他文档、脚本和项目配置
```

## 2. 根目录

### 2.1 根目录文件

| 文件 | 作用与职责 |
| --- | --- |
| `.gitignore` | 定义 Git 忽略规则。排除 Python 缓存、测试缓存、虚拟环境、构建目录、发布包、用户配置以及大体积 FFmpeg/Deno 运行时；明确保留受控的 `VideoDownloadKing.spec`。 |
| `AGENTS.md` | 面向开发智能体和维护者的工程指南。记录项目约束、模块职责、数据流、转码与字幕规则、测试命令和发布要求。 |
| `CHANGELOG.md` | 正式版本更新日志。按版本记录新增功能、改进、验证结果、发布包名称、体积和 SHA256。 |
| `LOGO_WORK_HANDOFF.md` | Logo 制作工作的交接记录。说明最终选择稿、已生成资源、构建验证、未来续作方式和注意事项。 |
| `PROJECT_STRUCTURE.md` | 本文档。集中说明每个目录和文件的用途。 |
| `PROJECT_SUMMARY.md` | 项目级概览。介绍产品定位、技术栈、核心功能、数据流、便携约束、构建发布方式和当前版本状态。 |
| `README.md` | 面向用户和普通开发者的主说明文档。包含功能列表、开发运行、运行时目录、构建方法、使用步骤和暂不支持范围。 |
| `THIRD_PARTY_NOTICES.md` | 第三方组件及许可证说明。记录 yt-dlp、FFmpeg、PySide6、Deno、抖音参考实现、gmssl 和异步网络库的来源与用途。 |
| `VideoDownloadKing.spec` | PyInstaller 固定构建配置。指定入口、应用图标、资源目录、隐藏导入项和需要排除的无关大型模块，生成无控制台窗口的目录版程序。 |
| `build_release.ps1` | Windows 正式发布脚本。检查运行时、运行测试、调用固定 spec 构建、裁剪无关 Qt 文件、复制便携运行时，并生成 `release/VideoDownloadKing-v<版本>-Windows-x64.zip`。 |
| `download_runtime.ps1` | 下载或更新便携运行时。获取 yt-dlp、Deno 和 FFmpeg，删除不需要的 `ffplay.exe`，保留 FFmpeg 许可证与说明，并输出各组件版本。 |
| `main.py` | 最薄的程序启动入口。导入并调用 `video_download_king.app.run()`，不承载业务逻辑。 |
| `pyproject.toml` | Python 项目元数据和 pytest 配置。声明项目名、版本、Python 版本、运行依赖、测试目录和模块搜索路径。 |
| `requirements.txt` | 开发及构建依赖的固定/约束版本列表，包括 PySide6、PyInstaller、pytest、aiohttp、aiofiles、aiohttp-socks 和 gmssl。 |
| `run.bat` | Windows 开发态快捷启动脚本，方便双击运行本地 `main.py`。 |

### 2.2 根目录动态目录

| 目录 | 作用与职责 | 是否应提交 |
| --- | --- | --- |
| `.git/` | Git 仓库内部数据库，保存提交、分支、标签、索引和远端信息。 | Git 自身管理，不作为普通文件提交。 |
| `.pytest_cache/` | pytest 自动生成的测试缓存，例如最近失败和节点 ID。删除后会自动重建。 | 否。 |
| `__pycache__/` | 根目录 Python 字节码缓存。 | 否。 |
| `.vscode/` | 本机 VS Code 工作区设置。当前包含 `settings.json`，用于编辑器级配置，不属于程序运行逻辑。 | 当前未跟踪；除非团队明确决定共享，否则不提交。 |
| `build/` | PyInstaller 分析、模块图、警告、归档和中间 EXE 构建文件。 | 否，可重新生成。 |
| `dist/` | PyInstaller 生成的未打包目录版程序，尚未加入完整便携运行时和发布文档。 | 否，可重新生成。 |
| `release/` | `build_release.ps1` 生成的最终便携目录和 ZIP。 | 否，通过 GitHub Release 分发。 |

## 3. 核心程序包 `video_download_king/`

该目录是应用的核心 Python 包。UI、请求模型、服务层、后台任务、转码和平台逻辑都位于这里。

### 3.1 核心 Python 模块

| 文件 | 主要职责 |
| --- | --- |
| `__init__.py` | 声明 Python 包，并提供应用版本号 `__version__`。窗口标题、网络测试 User-Agent 和发布版本应与它保持一致。 |
| `app.py` | 创建 `QApplication`，设置应用名称、组织名、全局图标和 Qt 样式表，实例化并显示 `MainWindow`。 |
| `config.py` | 定义 `AppSettings` 和 `SettingsStore`。负责加载、迁移、保存 `config/settings.json`；确保代理密码不落盘；配置损坏时备份并恢复默认值；分别保存 YouTube 与抖音转码配置。 |
| `douyin.py` | 抖音自研服务层。负责提取作品 ID、加载 Netscape Cookie、设置代理、构造签名请求、解析视频/图集/实况资源、按画质选择资源、异步下载、进度报告和原子文件提交。 |
| `bilibili.py` | B站自研服务层。负责 BV/AV/b23 提取、WBI 签名、稿件/分P/DASH 解析、选流、Range 分片、CDN 回退、附属文件和 FFmpeg 无转码合并。 |
| `bilibili_page.py` | 独立 B站下载页面。提供多分P勾选、画质/编码/音质、命名模板、附属文件、双进度条、日志和取消。 |
| `bilibili_workers.py` | B站分析与下载的 Qt 后台 worker，负责结构化信号、错误分类和单调进度转发。 |
| `douyin_page.py` | 抖音下载页面。负责链接、引擎、画质、保存路径、作者分类、命名模板、封面和紧凑转码面板的 UI；创建请求；启动 worker；处理进度、取消、缩略图和结果提示。 |
| `douyin_workers.py` | 抖音后台任务编排。提供分析 worker 和下载 worker；管理自研引擎与 yt-dlp 双引擎、用户确认后的引擎回退、进度区间映射、转码和 GPU 失败回退。 |
| `errors.py` | 将外部错误文本归类为稳定的中文错误类别，例如网络、代理、Cookie/登录、FFmpeg、平台限制和已取消。 |
| `formats.py` | 过滤并排序视频流、音频流，根据输出模式和画质配置生成 yt-dlp `--format` 选择表达式。 |
| `main_window.py` | 应用主窗口和 YouTube/X 单链接页面。负责菜单、标签页、响应式滚动布局、格式表格、字幕入口、文件名预览、设置加载、硬件检测、线程启动、进度显示、取消和关闭流程。批量下载占位页也由此模块创建。 |
| `models.py` | 项目的稳定数据模型层。定义代理、转码、格式、字幕、媒体信息、下载请求、任务进度、任务结果、下载产物和抖音资源等 dataclass。UI 与服务层通过这些对象交换数据。 |
| `naming_widgets.py` | YouTube、抖音和 B站页面共享的命名变量按钮及自动换行布局。 |
| `network_test.py` | 设置页的网络连通性测试。校验测试 URL，支持直连、HTTP/HTTPS 和 SOCKS 代理，通过异步请求返回 HTTP 状态和耗时，并用 Qt worker 避免阻塞界面。 |
| `paths.py` | 统一解析开发态和 PyInstaller 冻结态路径，包括应用根目录、运行时、yt-dlp、FFmpeg、FFprobe、Deno 和配置文件位置。 |
| `platforms.py` | 平台识别和链接校验。识别 YouTube/抖音，提取抖音分享文本中的链接，校验当前支持范围，并对 YouTube、Instagram、X 等平台提供未配置代理提醒判断。 |
| `processes.py` | 安全的外部进程执行器。使用参数数组启动子进程，在 Windows 隐藏控制台窗口，实时读取合并输出，并支持终止整个子进程树。 |
| `settings_dialog.py` | 设置对话框。提供代理、YouTube Cookie、抖音 Cookie 和网络超时配置；代理页包含自定义网址的异步连通性测试。 |
| `subtitle_dialog.py` | 字幕选择对话框。区分人工和自动字幕，支持搜索、显示全部自动字幕、SRT/VTT 输出选择，并保证同一语言人工字幕优先且来源互斥。 |
| `transcode.py` | FFprobe/FFmpeg 服务层。负责媒体探测、编码兼容判断、硬件编码器实际试编码、自动码率决策、重封装/部分转码/完整转码、输出后缀、临时文件验证和原子替换。 |
| `transcode_panel.py` | 可复用的兼容 MP4 设置面板。提供 CPU/GPU、厂商、质量/码率、音频码率和文件后缀设置；支持标准单列布局和抖音页使用的紧凑双列布局。 |
| `utils.py` | 通用工具函数。负责 Windows 文件名清理、重复文件自动编号、媒体主文件名去重、日期显示、命名模板渲染、后缀清理、语言匹配和文件大小格式化。 |
| `workers.py` | YouTube 分析和下载的 Qt worker。在线程中调用 yt-dlp 与 FFmpeg 服务，映射下载/附属文件/转码的总进度，处理取消、GPU 回退和附属文件重命名。 |
| `ytdlp.py` | yt-dlp 服务层。构建安全参数数组，执行分析，解析 JSON，生成下载/封面/字幕命令，聚合双流进度，识别最终输出文件，并将附属文件失败降级为警告。 |

### 3.2 `video_download_king/assets/`

该目录保存程序运行和打包时直接使用的视觉资源。它们是从 `branding/logo/v1/` 派生并复制过来的产品资源。

| 文件 | 作用 |
| --- | --- |
| `apple-touch-icon.png` | Apple Touch Icon 派生资源，供网页或未来 Web 入口使用。 |
| `check.svg` | Qt 复选框选中状态使用的白色勾选图标，由 `app.py` 的样式表引用。 |
| `favicon-32.png` | 32×32 PNG 网站图标。 |
| `logo.ico` | Windows 多尺寸应用图标。PyInstaller EXE 构建直接引用此文件。 |
| `logo-1024.png` | 1024×1024 高分辨率应用 Logo，用于较大尺寸展示或后续导出。 |
| `logo-512.png` | 512×512 应用 Logo。`app.py` 使用它设置程序、窗口和任务栏图标。 |

### 3.3 `video_download_king/douyin_vendor/`

该目录保存抖音签名所需的最小第三方辅助实现。它属于底层算法依赖，不应在 UI 或 worker 中复制。

| 文件 | 作用 |
| --- | --- |
| `__init__.py` | 将目录标记为 Python 子包。 |
| `abogus.py` | A-Bogus 签名实现。包含字符串转换、SM3、RC4、自定义 Base64、浏览器指纹和最终签名生成逻辑。 |
| `xbogus.py` | X-Bogus 签名实现。对 URL 参数进行摘要、编码和 RC4 处理，生成抖音接口请求所需签名。 |

### 3.4 核心包生成目录

| 目录 | 作用 |
| --- | --- |
| `video_download_king/__pycache__/` | 核心模块的 Python 字节码缓存，可随时删除并自动重建。 |
| `video_download_king/douyin_vendor/__pycache__/` | 抖音签名子包的字节码缓存。 |

## 4. 自动化测试 `tests/`

| 文件 | 负责验证的内容 |
| --- | --- |
| `test_core.py` | 核心数据与命令测试：代理 URL、密码不持久化、格式选择、平台范围、海外平台代理提醒、测试 URL、文件名与模板、配置迁移、YouTube/抖音转码配置隔离、字幕命令和双流进度。 |
| `test_douyin.py` | 抖音专项测试：链接提取、Cookie 读取、SOCKS 代理、画质选择、视频/图集/实况解析、无水印资源优选、yt-dlp 请求映射和作者目录清理。 |
| `test_bilibili.py` | B站专项测试：链接/标识、WBI 签名、选流回退、Range/顺序下载降级和页面请求。 |
| `test_packaging.py` | 发布打包测试：确认发布脚本使用受控 spec，并只裁剪非必要 Qt 平台插件。 |
| `test_processes.py` | Windows 子进程测试：确认使用隐藏窗口和新进程组标志，避免弹出 CMD。 |
| `test_transcode.py` | 转码测试：兼容性决策、CPU/GPU 参数、源码率优先级、编码感知倍率、未知编码保护和输出后缀。 |
| `test_ui.py` | Qt UI 测试：数字输入框、仅封面联动、双进度条、分析取消、设置页网络测试、窗口滚动与动态回缩、抖音图集状态、共享/紧凑转码面板、抖音独立转码配置、命名按钮和字幕互斥。 |
| `__pycache__/` | 测试模块的字节码缓存，不提交。 |

## 5. 便携运行时 `runtime/`

`runtime/` 是便携运行的核心。程序通过 `paths.py` 从这里寻找外部工具，不依赖系统 PATH。

| 路径 | 作用 | Git 状态 |
| --- | --- | --- |
| `runtime/yt-dlp/` | 存放 yt-dlp 可执行程序。 | 目录中的当前 yt-dlp 可受控随项目分发。 |
| `runtime/yt-dlp/yt-dlp.exe` | YouTube/抖音媒体分析、格式查询、下载、封面和字幕处理工具。 | 当前仓库包含。 |
| `runtime/deno/` | 存放 Deno JavaScript 运行时。 | 大体积目录被忽略。 |
| `runtime/deno/deno.exe` | yt-dlp 处理 YouTube JavaScript 挑战时使用的运行时。 | 本地/发布包存在，不提交。 |
| `runtime/ffmpeg/` | 存放 FFmpeg Windows essentials 构建。 | 大体积目录被忽略。 |
| `runtime/ffmpeg/bin/ffmpeg.exe` | 合并媒体流、重封装、音视频转码和硬件编码测试。 | 本地/发布包存在，不提交。 |
| `runtime/ffmpeg/bin/ffprobe.exe` | 探测容器、编码、码率、分辨率和时长，为转码决策提供真实媒体信息。 | 本地/发布包存在，不提交。 |
| `runtime/ffmpeg/LICENSE` | 随附 FFmpeg 构建的许可证文本。 | 跟随本地运行时/发布包。 |
| `runtime/ffmpeg/README.txt` | 随附 FFmpeg Windows 构建说明。 | 跟随本地运行时/发布包。 |

## 6. 用户数据目录

### `config/`

| 文件 | 作用 |
| --- | --- |
| `config/settings.json` | 当前用户的便携设置，包括保存路径、代理（不含密码）、Cookie 路径、网络超时、命名、字幕和 YouTube/抖音独立转码设置。属于本地用户数据，不提交。 |
| `config/settings.json.corrupt-*` | 配置损坏时由 `SettingsStore` 自动创建的备份，便于排查和恢复。 |

### `downloads/`

默认下载输出目录。根据设置可继续创建 `YouTube/`、`Douyin/` 和抖音作者子目录。下载的视频、音频、封面、字幕和图集都属于用户内容，不提交。

## 7. 品牌资源 `branding/`

### 7.1 目录职责

| 目录 | 作用 |
| --- | --- |
| `branding/` | 产品品牌资源总目录。 |
| `branding/logo/` | Logo 各正式版本的归档入口。 |
| `branding/logo/v1/` | 第一代正式 Logo 的不可变归档。修改视觉设计时应创建 `v2/`，不能覆盖这里。 |
| `branding/logo/v1/source/` | 用户最终选择的原始位图，仍包含实际棋盘格背景。 |
| `branding/logo/v1/master/` | 去除棋盘格后的透明高分辨率母版。 |
| `branding/logo/v1/png/` | 常用尺寸彩色 PNG 和黑白单色版。 |
| `branding/logo/v1/windows/` | Windows 多尺寸 ICO。 |
| `branding/logo/v1/web/` | favicon、Apple Touch Icon 和 Web App Icon。 |
| `branding/logo/v1/preview/` | 浅色/深色背景和 EXE 嵌入效果预览。 |

### 7.2 品牌文档

| 文件 | 作用 |
| --- | --- |
| `branding/logo/README.md` | Logo 归档入口和版本管理规则。 |
| `branding/logo/v1/README.md` | V1 设计理念、目录说明、推荐文件和不可变版本规则。 |
| `branding/logo/v1/USAGE_GUIDE.md` | Logo 颜色、留白、最小尺寸、背景、禁止事项和文件选择规范。 |

### 7.3 V1 图像文件

| 文件 | 作用 |
| --- | --- |
| `branding/logo/v1/source/selected-logo-original.png` | 用户选择的原始 Logo 图，是所有 V1 派生文件的唯一视觉源。 |
| `branding/logo/v1/master/video-download-king-logo-v1.png` | 1024×1024 透明 PNG 视觉母版，适合大尺寸宣传和继续导出。 |
| `branding/logo/v1/png/video-download-king-logo-v1-1024.png` | 1024×1024 标准彩色 PNG。 |
| `branding/logo/v1/png/video-download-king-logo-v1-512.png` | 512×512 标准彩色 PNG，适合应用和文档。 |
| `branding/logo/v1/png/video-download-king-logo-v1-256.png` | 256×256 标准彩色 PNG。 |
| `branding/logo/v1/png/video-download-king-logo-v1-128.png` | 128×128 标准彩色 PNG。 |
| `branding/logo/v1/png/video-download-king-logo-v1-64.png` | 64×64 标准彩色 PNG。 |
| `branding/logo/v1/png/video-download-king-logo-v1-mono-black.png` | 保留透明负空间的黑色单色版，供浅色背景或单色印刷使用。 |
| `branding/logo/v1/png/video-download-king-logo-v1-mono-white.png` | 白色单色版，供深色背景使用。 |
| `branding/logo/v1/windows/video-download-king-v1.ico` | 包含 16–256px 多尺寸的 Windows 图标母文件。 |
| `branding/logo/v1/web/favicon.ico` | 浏览器标签使用的多尺寸 ICO favicon。 |
| `branding/logo/v1/web/favicon-32.png` | 32×32 PNG favicon。 |
| `branding/logo/v1/web/apple-touch-icon-180.png` | 180×180 Apple Touch Icon。 |
| `branding/logo/v1/web/web-app-icon-512.png` | 512×512 Web App 图标。 |
| `branding/logo/v1/preview/logo-v1-light-dark-preview.jpg` | 同时展示 Logo 在浅色和深色背景上的效果。 |
| `branding/logo/v1/preview/exe-embedded-icon.png` | 从打包 EXE 中提取的图标预览，用于确认 PyInstaller 嵌入正确。 |

## 8. 开发工具 `tools/`

| 文件/目录 | 作用 |
| --- | --- |
| `tools/build_logo_v1.py` | Logo V1 资源生成脚本。移除原稿中与画布边缘连通的棋盘格，生成透明母版、多尺寸 PNG、ICO、Web 图标、单色版和预览图，并复制程序实际使用的资源到 `video_download_king/assets/`。 |
| `tools/__pycache__/` | 工具脚本字节码缓存，不提交。 |

## 9. 主要依赖关系

```text
main.py
└─ app.py
   └─ main_window.py
      ├─ workers.py ── ytdlp.py ── processes.py
      │             └─ transcode.py ── processes.py
      ├─ douyin_page.py
      │  └─ douyin_workers.py
      │     ├─ douyin.py ── douyin_vendor/
      │     ├─ ytdlp.py
      │     └─ transcode.py
      ├─ settings_dialog.py ── network_test.py
      ├─ subtitle_dialog.py
      ├─ transcode_panel.py
      ├─ config.py
      ├─ models.py
      ├─ platforms.py
      ├─ formats.py
      ├─ paths.py
      └─ utils.py
```

## 10. 修改功能时通常需要关注的文件

| 需求类型 | 优先检查 |
| --- | --- |
| 修改主窗口或 YouTube UI | `main_window.py`、`transcode_panel.py`、`tests/test_ui.py` |
| 修改抖音 UI | `douyin_page.py`、`transcode_panel.py`、`tests/test_ui.py` |
| 修改抖音解析或下载 | `douyin.py`、`douyin_workers.py`、`tests/test_douyin.py` |
| 修改 yt-dlp 参数或进度 | `ytdlp.py`、`formats.py`、`workers.py`、`tests/test_core.py` |
| 修改转码逻辑 | `transcode.py`、`models.py`、`tests/test_transcode.py` |
| 修改配置 | `config.py`、`models.py`、对应 UI 和配置迁移测试 |
| 修改字幕 | `subtitle_dialog.py`、`ytdlp.py`、`models.py`、字幕测试 |
| 修改平台支持 | `platforms.py`、请求模型、服务层和平台测试 |
| 修改打包 | `VideoDownloadKing.spec`、`build_release.ps1`、`tests/test_packaging.py` |
| 修改 Logo | `branding/logo/`、`tools/build_logo_v1.py`、`video_download_king/assets/` |

## 11. 不应手工维护或提交的内容

- `build/`、`dist/`、`release/`：由构建脚本生成。
- `__pycache__/`、`.pytest_cache/`：由 Python 和 pytest 生成。
- `config/settings.json`：用户本地设置，可能包含私人路径和 Cookie 文件位置。
- `downloads/`：用户下载内容。
- `runtime/ffmpeg/`、`runtime/deno/`：大体积第三方运行时，通过脚本获取并放入发布包。
- `.vscode/`：当前属于本机编辑器设置，除非明确决定共享。
