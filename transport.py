"""Vanta listener transport. No device control commands are sent here."""

from __future__ import annotations

import importlib
import ipaddress
import json
import math
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from arduino import ArduinoReport


EventHandler = Callable[[str, Any], None]


@dataclass(frozen=True)
class ReceivedPacket:
    raw: str | bytes
    received_ns: int
    received_at: datetime


def _endpoint(host: str, port: int) -> str:
    """Accept an IPv4 address or DNS name, never a supplied URL/path."""
    if not isinstance(host, str):
        raise ValueError("请输入设备 IP 地址或主机名。")
    host = host.strip()
    if not host or len(host) > 253:
        raise ValueError("请输入有效的设备 IP 地址或主机名。")
    try:
        ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        labels = host.rstrip(".").split(".")
        if (
            re.fullmatch(r"[0-9.]+", host)
            or any(
                not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in labels
            )
        ):
            raise ValueError("IP 地址或主机名无效。请勿输入协议、端口或路径。")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("端口必须是 1 至 65535 的整数。")
    return f"ws://{host}:{port}"


def _shutdown(ws: Any) -> None:
    """End blocking reads without waiting for a WebSocket close reply."""
    try:
        ws.shutdown()
    except Exception:
        # Also support a small compatible test double or another library build.
        try:
            ws.close(timeout=0)
        except Exception:
            pass


class ListenerClient:
    GREETING = "Hi i am a listener"
    ACCEPTED = "Client connected as a listener."

    def __init__(
        self,
        host: str,
        port: int,
        on_event: EventHandler,
        reconnect_seconds: float = 3.0,
    ) -> None:
        self.endpoint = _endpoint(host, port)
        self.on_event = on_event
        if not math.isfinite(reconnect_seconds) or reconnect_seconds < 0.01:
            raise ValueError("重连间隔必须至少为 0.01 秒。")
        self.reconnect_seconds = float(reconnect_seconds)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._ws: Any = None
        self._module: Any = None

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_alive:
            raise RuntimeError("监听线程正在运行。")
        try:
            self._module = importlib.import_module("websocket")
        except ImportError as exc:
            raise RuntimeError(
                "缺少 websocket-client。请在本目录运行 "
                "python -m pip install -r requirements.txt。"
            ) from exc
        if not hasattr(self._module, "WebSocket"):
            raise RuntimeError("websocket 模块无效。请安装 requirements.txt 中的 websocket-client。")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="vanta-listener", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            ws = self._ws
        if ws is not None:
            _shutdown(ws)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            ws = None
            reason = "设备连接已关闭。"
            try:
                self.on_event("status", f"正在连接 {self.endpoint}")
                ws = self._module.WebSocket(enable_multithread=True)
                # Publish before connect/handshake so stop() can close an active read.
                with self._lock:
                    self._ws = ws
                if self._stop.is_set():
                    break
                ws.connect(self.endpoint, timeout=3.0, http_no_proxy=["*"])
                if self._stop.is_set():
                    break
                ws.send(self.GREETING)  # The only application message this client sends.
                reply = ws.recv()
                if isinstance(reply, bytes):
                    reply = reply.decode("utf-8")
                if reply != self.ACCEPTED:
                    raise ConnectionError(f"设备未接受监听者握手：{str(reply)[:180]}")
                if self._stop.is_set():
                    break
                ws.settimeout(0.5)
                self.on_event("connected", self.endpoint)
                while not self._stop.is_set():
                    try:
                        raw = ws.recv()
                        # Record complete-message receipt before parsing or callbacks.
                        received_ns = time.perf_counter_ns()
                        received_at = datetime.now().astimezone()
                    except self._module.WebSocketTimeoutException:
                        continue
                    if self._stop.is_set():
                        break
                    if raw is None or raw == "" or raw == b"":
                        raise ConnectionError("设备已断开连接。")
                    self.on_event("packet", ReceivedPacket(raw, received_ns, received_at))
            except Exception as exc:
                reason = f"设备连接中断：{exc}"
            finally:
                with self._lock:
                    if self._ws is ws:
                        self._ws = None
                if ws is not None:
                    _shutdown(ws)
                if self._stop.is_set():
                    reason = "监听已停止。"
                self.on_event("disconnected", reason)
            if self._stop.is_set():
                break
            self.on_event("status", f"{self.reconnect_seconds:g} 秒后重连。")
            self._stop.wait(self.reconnect_seconds)


class DemoClient:
    """Simulate the API and the Arduino reports with local sample data."""

    endpoint = "演示数据"

    def __init__(self, on_event: EventHandler) -> None:
        self.on_event = on_event
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_alive:
            raise RuntimeError("演示线程正在运行。")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="vanta-demo", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)

    def _send(self, notification_id: int, params: dict[str, Any]) -> None:
        raw = json.dumps(
            {"commandId": 403, "id": notification_id, "params": params},
            ensure_ascii=False,
        )
        stamp_ns = time.perf_counter_ns()
        stamp_at = datetime.now().astimezone()
        self.on_event("packet", ReceivedPacket(raw, stamp_ns, stamp_at))

    def _send_gpio(self, event: str, *, ready: bool, rad_on: bool) -> None:
        stamp_ns = time.perf_counter_ns()
        if event != "BOOT":
            self._gpio_sequence += 1
        self.on_event("arduino_report", ArduinoReport(
            (stamp_ns - self._gpio_started_ns) // 1_000_000, event, self._gpio_sequence,
            ready, rad_on, False, 0, True, stamp_ns, datetime.now().astimezone(),
        ))

    def _run(self) -> None:
        self.on_event("connected", self.endpoint)
        self.on_event("arduino_connected", "演示串口")
        self._gpio_started_ns = time.perf_counter_ns()
        self._gpio_sequence = 0
        self._send_gpio("BOOT", ready=True, rad_on=False)
        self._send(100, {"systemStatus": "Ready"})
        test_id = 1
        try:
            while not self._stop.is_set():
                self._send_gpio("READY", ready=False, rad_on=False)
                self._send_gpio("RAD_ON", ready=False, rad_on=True)
                self._send(200, {})
                self._send(202, {"exposureNum": 1, "maxExposures": 1})
                if self._stop.wait(0.5):
                    break
                analysis = {
                    "testId": test_id,
                    "tidName": str(test_id),
                    "testDateTime": datetime.now().isoformat(),
                    "elapsedTime": 0.5,
                    "methodId": "alloyPlus-demo",
                    "methodDispName": "Alloy Plus（演示）",
                    "final": False,
                }
                chemistry = [
                    {"elementName": "Fe", "concentration": 68.82, "error": 0.12},
                    {"elementName": "Cr", "concentration": 18.10, "error": 0.06},
                    {"elementName": "Ni", "concentration": 10.55, "error": 0.04},
                    {"elementName": "Mo", "concentration": 2.53, "error": 0.02},
                ]
                self._send(206, {"result": {"analysis": dict(analysis), "chemistry": chemistry}})
                if self._stop.wait(0.5):
                    break
                self._send_gpio("RAD_ON", ready=False, rad_on=False)
                self._send(203, {"exposureNum": 1, "maxExposures": 1})
                self._send(201, {"stopReason": "Test Complete", "stopReasonInt": 0})
                if self._stop.wait(0.25):
                    break
                analysis["final"] = True
                analysis["elapsedTime"] = 1
                final_chemistry = [{**chemistry[0], "concentration": 68.62}, *chemistry[1:]]
                self._send(206, {"result": {"analysis": analysis, "processedChemistry": final_chemistry}})
                self._send_gpio("READY", ready=True, rad_on=False)
                test_id += 1
                if self._stop.wait(2.0):
                    break
        finally:
            self.on_event("arduino_disconnected", "演示已停止")
            self.on_event("disconnected", "演示已停止。")
