import json
import os
import signal
import sys

import pytest

from dvc.proc.exceptions import UnsupportedSignalError
from dvc.proc.manager import ProcessManager
from dvc.proc.process import ProcessInfo

PID_FINISHED = 1234
PID_RUNNING = 5678


def create_process(root: str, name: str, pid: int, returncode=None):
    info_path = os.path.join(root, name, f"{name}.json")
    os.makedirs(os.path.join(root, name))
    process_info = ProcessInfo(
        pid=pid, stdin=None, stdout=None, stderr=None, returncode=returncode
    )
    with open(info_path, "w", encoding="utf-8") as fobj:
        json.dump(process_info.asdict(), fobj)


@pytest.fixture
def finished_process(tmp_dir):
    key = "finished"
    create_process(tmp_dir, key, PID_FINISHED, 0)
    return key


@pytest.fixture
def running_process(tmp_dir):
    key = "running"
    create_process(tmp_dir, key, PID_RUNNING)
    return key


def test_send_signal(tmp_dir, mocker, finished_process, running_process):
    m = mocker.patch("os.kill")
    process_manager = ProcessManager(tmp_dir)
    process_manager.send_signal(running_process, signal.SIGTERM)
    m.assert_called_once_with(PID_RUNNING, signal.SIGTERM)

    m = mocker.patch("os.kill")
    process_manager.send_signal(finished_process, signal.SIGTERM)
    m.assert_not_called()

    if sys.platform == "win32":
        with pytest.raises(UnsupportedSignalError):
            process_manager.send_signal(finished_process, signal.SIGABRT)


def test_dead_process(tmp_dir, mocker, running_process):
    process_manager = ProcessManager(tmp_dir)
    with pytest.raises(ProcessLookupError):
        process_manager.send_signal(running_process, signal.SIGTERM)
    assert process_manager[running_process].returncode == -1


def test_kill(tmp_dir, mocker, finished_process, running_process):
    m = mocker.patch("os.kill")
    process_manager = ProcessManager(tmp_dir)
    process_manager.kill(running_process)
    if sys.platform == "win32":
        m.assert_called_once_with(PID_RUNNING, signal.SIGTERM)
    else:
        m.assert_called_once_with(PID_RUNNING, signal.SIGKILL)

    m = mocker.patch("os.kill")
    process_manager.kill(finished_process)
    m.assert_not_called()


def test_terminate(tmp_dir, mocker, running_process, finished_process):
    m = mocker.patch("os.kill")
    process_manager = ProcessManager(tmp_dir)
    process_manager.terminate(running_process)
    m.assert_called_once_with(PID_RUNNING, signal.SIGTERM)

    m.reset_mock()
    process_manager.terminate(finished_process)
    m.assert_not_called()
