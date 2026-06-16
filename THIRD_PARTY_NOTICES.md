# 第三方组件说明

## yt-dlp

- 项目：https://github.com/yt-dlp/yt-dlp
- 当前随附版本：2026.03.17
- 许可证：Unlicense

## FFmpeg

- 项目：https://ffmpeg.org/
- Windows 构建来源：https://www.gyan.dev/ffmpeg/builds/
- FFmpeg 官方下载页将 gyan.dev 列为 Windows 可执行文件构建来源。
- 具体版本可运行 `runtime\ffmpeg\bin\ffmpeg.exe -version` 查看。
- FFmpeg 及其构建所适用的许可证以随附构建和 FFmpeg 项目声明为准。

## Qt for Python / PySide6

- 项目：https://doc.qt.io/qtforpython-6/
- 许可证：LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only

## Deno

- 项目：https://deno.com/
- 下载：https://github.com/denoland/deno/releases
- 用途：yt-dlp 官方推荐的 YouTube JavaScript 挑战运行时
- 许可证：MIT

## douyin-downloader

- 项目：https://github.com/jiji262/douyin-downloader
- 参考提交：`dc7e967b1680cf18beae9857fb99eb43fe0aeee6`
- 用途：抖音单作品接口、资源选择和下载流程的参考实现
- 许可证：MIT

本项目仅移植了抖音单作品下载所需的最小实现。签名辅助代码保留其文件头所声明的
Apache License 2.0 来源信息。

## gmssl

- 项目：https://github.com/py-gmssl/py-gmssl
- 用途：抖音 A-Bogus 签名所需的 SM3 实现
- 许可证：MIT

## aiohttp / aiofiles

- aiohttp：https://github.com/aio-libs/aiohttp
- aiofiles：https://github.com/Tinche/aiofiles
- 用途：抖音接口及媒体资源的异步网络与文件处理
- 许可证：Apache License 2.0

## aiohttp-socks / python-socks

- aiohttp-socks：https://github.com/romis2012/aiohttp-socks
- python-socks：https://github.com/romis2012/python-socks
- 用途：为自研抖音引擎提供 SOCKS4/SOCKS5 代理连接
- 许可证：Apache License 2.0
