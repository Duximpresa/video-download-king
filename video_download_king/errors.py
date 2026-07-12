from __future__ import annotations


BILIBILI_412_HINT = (
    "哔哩哔哩拒绝了当前请求（HTTP 412，风控校验失败）。\n\n"
    "请先在 Chrome 或 Edge 中登录哔哩哔哩并打开一次该视频，然后完全退出浏览器；"
    "再到“设置 > 网站登录”选择对应浏览器后重试。也可以导出最新的 Netscape cookies.txt。\n\n"
    "如果已经配置 Cookie，请刷新 Cookie；使用代理时也可尝试更换出口或暂时直连。"
)


def user_facing_error(text: str) -> str:
    lowered = text.lower()
    if "bilibili" in lowered and ("http error 412" in lowered or "precondition failed" in lowered):
        return BILIBILI_412_HINT
    return text


def categorize_error(text: str) -> str:
    lowered = text.lower()
    if "任务已取消" in text or "cancelled" in lowered or "canceled" in lowered:
        return "已取消"
    if "no space left" in lowered or "磁盘空间" in text:
        return "磁盘空间"
    if "proxy" in lowered or "socks" in lowered:
        return "代理"
    if "bilibili" in lowered and ("http error 412" in lowered or "precondition failed" in lowered):
        return "Cookie/风控"
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
