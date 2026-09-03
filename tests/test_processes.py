import os
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from video_download_king.processes import ProcessRunner, ProcessTimeout


class FakeProcess:
    def __init__(self) -> None:
        self.stdout = []

    def wait(self) -> int:
        return 0


def test_windows_processes_are_hidden() -> None:
    with patch("video_download_king.processes.os.name", "nt"), patch(
        "video_download_king.processes.subprocess.Popen", return_value=FakeProcess()
    ) as popen:
        ProcessRunner().run(["tool.exe"])
    kwargs = popen.call_args.kwargs
    assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert kwargs["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    assert kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW


def test_process_timeout_stops_hung_process() -> None:
    started = time.monotonic()
    with pytest.raises(ProcessTimeout, match="运行超过"):
        ProcessRunner().run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.2,
        )
    assert time.monotonic() - started < 5
