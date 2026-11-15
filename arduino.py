"""Send commands and read lines through one Arduino USB serial port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import importlib
import queue
import re
import threading
import time


BAUD_RATE = 115200
MAX_REPORT_BYTES = 256
MAX_CONSOLE_LINE_BYTES = 2048
MAX_COMMAND_BYTES = 39
REPORT_EVENTS = frozenset(("BOOT", "STATE", "READY", "RAD_ON", "FAULT"))
CONTROL_PROGRESS = re.compile(r"CTRL ([A-Z_]+) sent=([0-9]{1,10}) total=([0-9]{1,10})")
CONTROL_ERROR = re.compile(r"CTRL ERROR ([A-Z_]+)")


@dataclass(frozen=True)
class ArduinoReport:
    uptime_ms: int
    event: str
    sequence: int
    ready: bool
    rad_on: bool
    fault: bool | None
    dropped: int
    matrix: bool
    received_ns: int
    received_at: datetime


@dataclass(frozen=True)
class ArduinoLine:
    direction: str
    text: str
    at: datetime
    report: ArduinoReport | None = None


@dataclass(frozen=True)
class ArduinoControl:
    event: str
    sent: int | None = None
    total: int | None = None
    error: str | None = None


def parse_arduino_control(text: str) -> ArduinoControl | None:
    match = CONTROL_PROGRESS.fullmatch(text)
    if match:
        event, sent_text, total_text = match.groups()
        sent, total = int(sent_text), int(total_text)
        return ArduinoControl(event, sent, total) if sent <= total <= 0xFFFFFFFF else None
    match = CONTROL_ERROR.fullmatch(text)
    if match:
        return ArduinoControl("ERROR", error=match[1])
    if text in ("CTRL FAULT_CLEARED", "CTRL NO_FAULT_LOCK"):
        return ArduinoControl(text[5:])
    return None


def parse_arduino_report(line: bytes) -> ArduinoReport | None:
    if len(line) > MAX_REPORT_BYTES:
        return None
    try:
        parts = line.decode("ascii").split()
        fields = dict(part.split("=", 1) for part in parts)
        event = fields["event"]
        numbers = [fields[key] for key in ("t_ms", "seq", "dropped")]
        bits = [fields[key] for key in ("READY", "RAD_ON", "matrix")]
        fault = fields.get("FAULT")
    except (KeyError, ValueError):
        return None
    if len(fields) != len(parts) or event not in REPORT_EVENTS:
        return None
    if not all(value.isdecimal() and len(value) <= 10 for value in numbers):
        return None
    uptime_ms, sequence, dropped = map(int, numbers)
    if max(uptime_ms, sequence, dropped) > 0xFFFFFFFF:
        return None
    if any(value not in ("0", "1") for value in bits) or fault not in (None, "0", "1"):
        return None
    ready, rad_on, matrix = (value == "1" for value in bits)
    return ArduinoReport(
        uptime_ms, event, sequence, ready, rad_on, None if fault is None else fault == "1",
        dropped, matrix, time.perf_counter_ns(), datetime.now().astimezone(),
    )


class ArduinoClient:
    def __init__(self, port: str, on_event) -> None:
        self.port = port.strip().upper()
        if not re.fullmatch(r"COM[1-9][0-9]{0,4}", self.port):
            raise ValueError("请输入有效的串口号，例如 COM4。")
        self.on_event = on_event
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._command_lock = threading.Lock()
        self._commands: queue.Queue[tuple[str, bytes]] | None = None

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_alive:
            raise RuntimeError("Arduino 串口线程正在运行。")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="arduino-serial", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)

    def send_command(self, command: str) -> None:
        if not command.strip() or any(ch != "\t" and not " " <= ch <= "~" for ch in command):
            raise ValueError("请输入一行 ASCII 命令。")
        command = command.strip()
        payload = command.encode("ascii") + b"\n"
        if len(payload) > MAX_COMMAND_BYTES + 1:
            raise ValueError(f"命令最多 {MAX_COMMAND_BYTES} 字节。")
        with self._command_lock:
            if self._stop.is_set() or self._commands is None:
                raise ConnectionError("Arduino 串口未连接。")
            try:
                self._commands.put_nowait((command, payload))
            except queue.Full as exc:
                raise RuntimeError("命令队列已满。请稍后再发送。") from exc

    def _emit_line(self, direction: str, text: str, report: ArduinoReport | None = None) -> None:
        at = report.received_at if report else datetime.now().astimezone()
        self.on_event("arduino_line", ArduinoLine(direction, text, at, report))

    def _run(self) -> None:
        try:
            serial = importlib.import_module("serial")
        except ImportError:
            self.on_event("arduino_disconnected", "缺少 pyserial。请运行 run_gui.bat 安装依赖。")
            return
        while not self._stop.is_set():
            self.on_event("arduino_status", f"正在打开 {self.port}")
            try:
                with serial.Serial(self.port, BAUD_RATE, timeout=0.1, write_timeout=0.5) as connection:
                    commands = queue.Queue(maxsize=16)
                    with self._command_lock:
                        if self._stop.is_set():
                            break
                        self._commands = commands
                    try:
                        self.on_event("arduino_connected", self.port)
                        self._serve(connection, commands)
                    finally:
                        with self._command_lock:
                            self._commands = None
                        if not commands.empty():
                            self._emit_line("ERR", f"串口已关闭。已取消 {commands.qsize()} 条待发送命令。")
            except (OSError, ValueError) as exc:
                if not self._stop.is_set():
                    self.on_event("arduino_disconnected", f"{self.port} · {exc} · 2 秒后重试")
            self._stop.wait(2.0)
        self.on_event("arduino_disconnected", "未连接")

    def _serve(self, connection, commands: queue.Queue[tuple[str, bytes]]) -> None:
        pending = b""
        discard = False
        while not self._stop.is_set():
            try:
                command, payload = commands.get_nowait()
            except queue.Empty:
                pass
            else:
                if self._stop.is_set():
                    self._emit_line("ERR", f"命令已取消 · {command}")
                    break
                try:
                    if connection.write(payload) != len(payload):
                        raise OSError("串口只写入了部分字节。")
                except (OSError, ValueError) as exc:
                    self._emit_line("ERR", f"写入未确认 · {command} · {exc}")
                    raise
                self._emit_line("TX", command)
            chunk = connection.read(max(1, min(512, connection.in_waiting)))
            if discard:
                _, newline, chunk = chunk.partition(b"\n")
                if not newline:
                    continue
                discard = False
            if not chunk:
                continue
            *lines, pending = (pending + chunk).split(b"\n")
            if len(pending) > MAX_CONSOLE_LINE_BYTES:
                lines.append(pending)
                pending = b""
                discard = True
            for line in lines:
                line = line.rstrip(b"\r")
                if not line:
                    continue
                report = parse_arduino_report(line)
                text = line[:MAX_CONSOLE_LINE_BYTES].decode("utf-8", errors="replace")
                if len(line) > MAX_CONSOLE_LINE_BYTES:
                    text += "…（行已截断）"
                self._emit_line("RX", text, report)
