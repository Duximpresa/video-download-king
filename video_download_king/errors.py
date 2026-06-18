from __future__ import annotations


def categorize_error(text: str) -> str:
    lowered = text.lower()
    if "任务已取消" in text or "cancelled" in lowered or "canceled" in lowered:
        return "已取消"
    if "no space left" in lowered or "磁盘空间" in text:
        return "磁盘空间"
    if "proxy" in lowered or "socks" in lowered:
        return "代理"
    if "cookie" in lowered or "sign in" in lowered or "login" in lowered:
        return "Cookie/登录"
    if "requested format is not available" in lowered:
        return "格式失效"
    if "ffmpeg" in lowered or "ffprobe" in lowered:
        return "FFmpeg"
    if "unsupported url" in lowered or "only youtube" in lowered:
        return "平台限制"
    if "timed out" in lowered or "network" in lowered or "http error" in lowered:
        return "网络"
    return "未知错误"
