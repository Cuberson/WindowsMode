"""Minimal subprocess wrapper — the Windows port of Subprocess.swift.

Every child gets its own process group (CREATE_NEW_PROCESS_GROUP), so killing
the tree (claude.cmd → node → shells) with ``taskkill /T /F`` takes the whole
hierarchy — the acceptance requirement behind the macOS posix_spawn wrapper.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Callable, Optional

from .paths import AppLog

IS_WINDOWS = sys.platform == "win32"


class Subprocess:
    def __init__(self, executable: str, arguments: list[str], cwd: Optional[str],
                 environment: dict[str, str]):
        self.on_line: Optional[Callable[[str], None]] = None
        self.on_stderr: Optional[Callable[[str], None]] = None
        self.on_exit: Optional[Callable[[int], None]] = None

        self._lock = threading.Lock()
        self._exited = False
        self._exit_code: Optional[int] = None

        exe, args = _wrap_shim(executable, arguments)
        kwargs: dict = dict(
            exe=exe,
            args=args,
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        if IS_WINDOWS:
            # Own process group + no console window.
            kwargs["creationflags"] = (
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            )
        self._proc = subprocess.Popen(**kwargs)
        self.pid = self._proc.pid

    def start(self) -> None:
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        threading.Thread(target=self._wait, daemon=True).start()

    def _read_stdout(self) -> None:
        self._read_stream(self._proc.stdout, is_err=False)

    def _read_stderr(self) -> None:
        self._read_stream(self._proc.stderr, is_err=True)

    def _read_stream(self, stream, is_err: bool) -> None:
        try:
            for raw in iter(stream.readline, b""):
                try:
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                except Exception:
                    continue
                if not line:
                    continue
                cb = self.on_stderr if is_err else self.on_line
                if cb:
                    try:
                        cb(line)
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _wait(self) -> None:
        code = self._proc.wait()
        self._finish(code)

    def _finish(self, code: int) -> None:
        with self._lock:
            if self._exited:
                return
            self._exited = True
            self._exit_code = code
        # Give the read threads a moment to drain before reporting exit.
        def fire():
            if self.on_exit:
                try:
                    self.on_exit(code)
                except Exception:
                    pass
        threading.Timer(0.05, fire).start()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return not self._exited

    def interrupt(self, grace: float = 3.0) -> None:
        """CTRL_BREAK the whole group, then kill the tree after `grace` seconds if still alive."""
        try:
            if IS_WINDOWS:
                self._proc.send_signal(subprocess.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                self._proc.send_signal(2)  # SIGINT
        except Exception:
            pass

        def escalate():
            if self.is_running:
                self.kill()
        threading.Timer(grace, escalate).start()

    def kill(self) -> None:
        _kill_tree(self.pid)

    @staticmethod
    def kill_group(pid: int) -> None:
        _kill_tree(pid)

    @staticmethod
    def is_alive(pid: int) -> bool:
        return _is_alive(pid)


# ---------------------------------------------------------------------------
# Process-tree helpers
# ---------------------------------------------------------------------------

def _wrap_shim(executable: str, arguments: list[str]):
    """Batch shims (claude.cmd, npm.cmd…) must run through cmd.exe on Windows."""
    if IS_WINDOWS and executable.lower().endswith((".cmd", ".bat")):
        cmdline = subprocess.list2cmdline([executable] + list(arguments))
        return "cmd.exe", ["/d", "/s", "/c", cmdline]
    return executable, list(arguments)


def _kill_tree(pid: int) -> None:
    if IS_WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
            )
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(pid), 9)
        except Exception:
            try:
                os.kill(pid, 9)
            except Exception:
                pass


def _is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if IS_WINDOWS:
        # os.kill(pid, 0) would TerminateProcess on Windows — use OpenProcess.
        import ctypes
        import ctypes.wintypes as wt

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = wt.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Run a CLI to completion and capture output (used for --version,
# `auth status`, and every orchestrator call).
# ---------------------------------------------------------------------------

def run_capture(executable: str, arguments: list[str], cwd: Optional[str] = None,
                timeout: float = 60, environment: Optional[dict[str, str]] = None,
                extra_env: Optional[dict[str, str]] = None) -> tuple[int, str, str]:
    from .cli_locator import CLILocator

    env = dict(environment if environment is not None else CLILocator.child_environment())
    if extra_env:
        env.update(extra_env)

    out_lines: list[str] = []
    err_lines: list[str] = []
    done = threading.Event()
    result: dict = {}

    def on_exit(code: int) -> None:
        result["code"] = code
        done.set()

    try:
        p = Subprocess(executable=executable, arguments=arguments, cwd=cwd, environment=env)
    except Exception as e:
        return (-1, "", f"spawn failed: {e}")

    p.on_line = out_lines.append
    p.on_stderr = err_lines.append
    p.on_exit = on_exit
    p.start()

    def on_timeout():
        if p.is_running:
            AppLog.write(f"run_capture timeout after {timeout}s: {executable}")
            p.kill()

    timer = threading.Timer(timeout, on_timeout)
    timer.start()
    try:
        done.wait(timeout + 15)
    finally:
        timer.cancel()

    code = result.get("code", -1)
    return (code, "\n".join(out_lines), "\n".join(err_lines))
