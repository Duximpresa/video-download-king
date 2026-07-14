from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from .errors import categorize_error
from .models import TaskResult, XiaohongshuDownloadRequest
from .processes import ProcessCancelled
from .xiaohongshu import XiaohongshuService


class XiaohongshuAnalyzeWorker(QObject):
    log = Signal(str)
    completed = Signal(object)
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, request: XiaohongshuDownloadRequest) -> None:
        super().__init__()
        self.request = request
        self.service = XiaohongshuService()

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(self.service.analyze(self.request, self.log.emit))
        except ProcessCancelled:
            self.failed.emit("已取消", "任务已取消")
        except Exception as exc:
            self.failed.emit(categorize_error(str(exc)), str(exc))
        finally:
            self.finished.emit()

    @Slot()
    def cancel(self) -> None:
        self.service.cancel()


class XiaohongshuDownloadWorker(QObject):
    log = Signal(str)
    progress = Signal(object)
    completed = Signal(object)
    finished = Signal()

    def __init__(self, request: XiaohongshuDownloadRequest) -> None:
        super().__init__()
        self.request = request
        self.service = XiaohongshuService()
        self._last_total = 0.0

    @Slot()
    def run(self) -> None:
        try:
            def progress(item) -> None:
                if item.total_percent is not None:
                    self._last_total = max(self._last_total, item.total_percent)
                    item.total_percent = self._last_total
                self.progress.emit(item)

            files = self.service.download(self.request, progress, self.log.emit)
            self.completed.emit(TaskResult(True, "下载完成", files[0] if files else None, files))
        except ProcessCancelled:
            self.completed.emit(TaskResult(False, "任务已取消", error_category="已取消"))
        except Exception as exc:
            self.completed.emit(TaskResult(False, str(exc), error_category=categorize_error(str(exc))))
        finally:
            self.finished.emit()

    @Slot()
    def cancel(self) -> None:
        self.service.cancel()
