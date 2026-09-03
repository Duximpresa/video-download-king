from __future__ import annotations

import ctypes
import sys
import tempfile
import traceback
from pathlib import Path


def _report_startup_error(details: str) -> None:
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    log_path = root / "启动错误.log"
    try:
        log_path.write_text(details, encoding="utf-8")
    except OSError:
        log_path = Path(tempfile.gettempdir()) / "VideoDownloadKing-启动错误.log"
        try:
            log_path.write_text(details, encoding="utf-8")
        except OSError:
            pass
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(
            None,
            f"程序启动失败。\n\n错误详情已保存到：\n{log_path}",
            "Video Download King 启动失败",
            0x10,
        )


def main() -> int:
    try:
        from video_download_king.app import run

        return run()
    except Exception:
        _report_startup_error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
