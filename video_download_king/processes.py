from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections.abc import Callable, Iterable
from pathlib import Path


LogCallback = Callable[[str], None]


class ProcessCancelled(RuntimeError):
    pass


class ProcessTimeout(RuntimeError):
    pass


class ProcessRunner:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self.cancelled = False

    def run(
        self,
        args: Iterable[str | Path],
        *,
        on_line: LogCallback | None = None,
        cwd: Path | None = None,
        capture: bool = False,
        timeout: float | None = None,
    ) -> tuple[int, str]:
        command = [str(item) for item in args]
        flags = 0
        startupinfo = None
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        self.cancelled = False
        with self._lock:
            self._process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=flags,
                startupinfo=startupinfo,
            )
        timed_out = threading.Event()

        def stop_on_timeout() -> None:
            with self._lock:
                process = self._process
            if process is not None and process.poll() is None:
                timed_out.set()
                process.kill()

        timer = threading.Timer(timeout, stop_on_timeout) if timeout is not None else None
        if timer:
            timer.start()
        output: list[str] = []
        try:
            assert self._process.stdout is not None
            for raw_line in self._process.stdout:
                line = raw_line.rstrip("\r\n")
                if capture:
                    output.append(line)
                if on_line:
                    on_line(line)
            return_code = self._process.wait()
        finally:
            if timer:
                timer.cancel()
        with self._lock:
            self._process = None
        if timed_out.is_set():
            raise ProcessTimeout(f"子进程运行超过 {timeout:g} 秒，已停止")
        if self.cancelled:
            raise ProcessCancelled("任务已取消")
        return return_code, "\n".join(output)

    def cancel(self) -> None:
        self.cancelled = True
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
