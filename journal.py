"""Write complete JSON records outside the GUI and receive threads."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path, PureWindowsPath
import queue
import sys
import tempfile
import threading
import time
from typing import Callable


class _JournalHandler(RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        # The standard logging handler prints an error and hides it from its
        # caller. The worker must report failed writes to the application.
        error = sys.exc_info()[1]
        if error is not None:
            raise error
        raise OSError("日志写入失败")


@dataclass
class _Barrier:
    done: threading.Event = field(default_factory=threading.Event)
    success: bool = False


class AsyncJournal:
    """An ordered, bounded queue for the JSONL writer.

    ``submit`` does no file I/O or JSON serialization and never waits for queue
    space. Entries must not be changed after submission. ``on_error`` must be a
    short, thread-safe callback; it may be called from either submit or writer.
    Use a queue to notify a GUI. Do not call Tk from this callback.

    ``flush`` is a bounded wait for prior submissions. It reports False after
    any dropped entry or failed write, so a failure cannot look like success.
    ``close(wait=False)`` only requests shutdown. Call close with wait=True in
    a background shutdown task, or poll is_alive before ending the process.
    """

    def __init__(
        self,
        path: Path,
        on_error: Callable[[str], None] | None = None,
        max_pending: int = 4096,
        *,
        result_dir: Path | None = None,
        on_export: Callable[[int, dict], None] | None = None,
        summary_dir: Path | None = None,
        max_bytes: int = 20_000_000,
        backup_count: int = 5,
    ) -> None:
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < 1:
            raise ValueError("max_pending 必须是正整数")
        self.path = Path(path)
        self.on_error = on_error
        self.result_dir = Path(result_dir) if result_dir is not None else None
        self.on_export = on_export
        self.summary_dir = Path(summary_dir) if summary_dir is not None else None
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.failure_count = 0
        self.dropped_count = 0
        self.export_issue_count = 0
        self.last_error: str | None = None
        self._queue: queue.Queue[dict | _Barrier] = queue.Queue(max_pending)
        self._state_lock = threading.Lock()
        self._error_lock = threading.Lock()
        self._accepting = True
        self._stop_requested = threading.Event()
        self._space_available = threading.Event()
        self._space_available.set()
        self._stopped = threading.Event()
        self._handler: _JournalHandler | None = None
        self._thread = threading.Thread(
            target=self._run, name="vanta-journal", daemon=True
        )
        self._thread.start()

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def submit(self, entry: dict, *, report_full: bool = True) -> bool:
        if not isinstance(entry, dict):
            raise TypeError("日志记录必须是字典")
        with self._state_lock:
            if not self._accepting:
                return False
            try:
                self._queue.put_nowait(entry)
            except queue.Full:
                pass
            else:
                return True
        if report_full:
            self._report("日志队列已满；本条原始记录未保存", dropped=True)
        return False

    def flush(self, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        barrier = _Barrier()
        while True:
            with self._state_lock:
                if not self._accepting:
                    closed = True
                else:
                    closed = False
                    # Clear before trying the queue. A worker get() after this
                    # point wakes us, including a get() racing queue.Full.
                    self._space_available.clear()
                    try:
                        self._queue.put_nowait(barrier)
                    except queue.Full:
                        pass
                    else:
                        break
            remaining = max(0.0, deadline - time.monotonic())
            if closed:
                return self._stopped.wait(remaining) and self._successful()
            if remaining <= 0 or not self._space_available.wait(remaining):
                return False
        remaining = max(0.0, deadline - time.monotonic())
        return barrier.done.wait(remaining) and barrier.success

    def close(self, wait: bool = True, timeout: float = 2.0) -> bool:
        with self._state_lock:
            self._accepting = False
            self._stop_requested.set()
            self._space_available.set()
        if wait and threading.current_thread() is not self._thread:
            self._stopped.wait(max(0.0, timeout))
        return self._stopped.is_set() and self._successful()

    def _successful(self) -> bool:
        return self.failure_count == 0 and self.dropped_count == 0

    def _report(self, text: str, *, dropped: bool = False) -> None:
        with self._error_lock:
            if dropped:
                self.dropped_count += 1
            else:
                self.failure_count += 1
            notify = text != self.last_error
            self.last_error = text
        if notify and self.on_error is not None:
            try:
                self.on_error(text)
            except Exception:
                # A faulty notification callback must not stop the writer.
                pass

    def _open(self) -> None:
        if self._handler is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handler = _JournalHandler(
                self.path, maxBytes=self.max_bytes, backupCount=self.backup_count,
                encoding="utf-8", errors="backslashreplace",
            )
            self._handler.setFormatter(logging.Formatter("%(message)s"))

    def _close_handler(self) -> None:
        handler, self._handler = self._handler, None
        if handler is not None:
            try:
                handler.close()
            except Exception as exc:
                self._report(f"关闭日志文件失败：{exc}")

    def _export_final(self, entry: dict, result_dir: Path) -> dict:
        test_id = entry.get("testID")
        if (not isinstance(test_id, str) or not test_id or test_id.endswith((" ", "."))
                or any(ch in '<>:"/\\|?*' or ord(ch) < 32 for ch in test_id)
                or PureWindowsPath(f"{test_id}.json").is_reserved()):
            return {"status": "invalid_id", "error": "testID 缺失或不能作为文件名"}

        directory = result_dir / "demo" if entry.get("source") == "demo" else result_dir
        target = directory / f"{test_id}.json"
        filename = target.relative_to(result_dir.parent).as_posix()
        message = entry["message"]
        temporary = None
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", errors="backslashreplace", dir=directory,
                prefix=".206-", suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump(message, stream, ensure_ascii=False, allow_nan=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Windows rename and POSIX link both publish without replacing a file.
                if os.name == "nt":
                    temporary.rename(target)
                else:
                    os.link(temporary, target)
            except FileExistsError:
                if not target.is_symlink() and target.is_file():
                    try:
                        with target.open(encoding="utf-8") as stream:
                            if json.load(stream) == message:
                                return {"status": "already_saved", "file": filename}
                    except ValueError:
                        pass
                return {"status": "conflict", "file": filename}
            return {"status": "saved", "file": filename}
        except (OSError, ValueError, TypeError) as exc:
            return {"status": "error", "file": filename, "error": str(exc)}
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _write_entry(self, entry: dict) -> None:
        if self.result_dir is not None and entry.get("id") == 206 and entry.get("isFinal") is True:
            exported = self._export_final(entry, self.result_dir)
            entry = {**entry, "export": exported}
            if exported["status"] not in ("saved", "already_saved"):
                self.export_issue_count += 1
            if self.on_export is not None:
                try:
                    self.on_export(entry["packetNo"], exported)
                except Exception:
                    pass
        if entry.get("kind") == "round_summary":
            entry = {
                **entry,
                "journalDropped": self.dropped_count,
                "journalFailures": self.failure_count,
                "exportIssues": self.export_issue_count,
                "evidenceComplete": entry["evidenceComplete"] and self._successful(),
            }
        self._open()
        payload = json.dumps(entry, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        record = logging.LogRecord("vanta-listener", logging.INFO, "", 0, payload, (), None)
        self._handler.handle(record)
        if entry.get("kind") == "round_summary" and self.summary_dir is not None:
            self._write_summary(entry)

    def _write_summary(self, entry: dict) -> None:
        directory = self.summary_dir
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"summary_{self.path.stem}_{entry['summaryNo']}.json"
        temporary = target.with_suffix(".tmp")
        try:
            with temporary.open("w", encoding="utf-8", errors="backslashreplace") as stream:
                json.dump(entry, stream, ensure_ascii=False, allow_nan=False, indent=2)
                stream.write("\n")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def _run(self) -> None:
        try:
            # Directory creation and opening the file take place only here.
            try:
                self._open()
            except Exception as exc:
                self._report(f"打开日志文件失败：{exc}")
            while True:
                if self._stop_requested.is_set() and self._queue.empty():
                    break
                try:
                    entry = self._queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                self._space_available.set()
                try:
                    if isinstance(entry, _Barrier):
                        self._open()
                        self._handler.flush()
                        entry.success = self._successful()
                    else:
                        self._write_entry(entry)
                except Exception as exc:
                    self._report(f"日志记录未保存：{exc}")
                    self._close_handler()
                finally:
                    if isinstance(entry, _Barrier):
                        entry.done.set()
                    self._queue.task_done()
        finally:
            self._close_handler()
            self._stopped.set()
            self._space_available.set()
