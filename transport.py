"""Vanta listener transport. No device control commands are sent here."""

from __future__ import annotations

import importlib
import ipaddress
import json
import math
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from arduino import ArduinoLine, ArduinoReport


EventHandler = Callable[[str, Any], None]


@dataclass(frozen=True)
class ReceivedPacket:
    raw: str | bytes
    received_ns: int
    received_at: datetime
    rx_no: int = 0


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


def _tune_keepalive(sock: socket.socket) -> None:
    if sys.platform == "win32":
        sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 5000, 1000))
    else:
        for name, value in (("TCP_KEEPIDLE", 5), ("TCP_KEEPINTVL", 1), ("TCP_KEEPCNT", 5)):
            option = getattr(socket, name, None)
            if option is not None:
                sock.setsockopt(socket.IPPROTO_TCP, option, value)


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
                # The application validates and logs invalid text payloads.
                ws = self._module.WebSocket(enable_multithread=True, skip_utf8_validation=True)
                # Publish before connect/handshake so stop() can close an active read.
                with self._lock:
                    self._ws = ws
                if self._stop.is_set():
                    break
                ws.connect(self.endpoint, timeout=3.0, http_no_proxy=["*"],
                           sockopt=((socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),))
                try:
                    _tune_keepalive(ws.sock)
                except (AttributeError, OSError) as exc:
                    self.on_event("status", f"TCP 保活参数无法设置：{exc}")
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
                rx_no = 0
                while not self._stop.is_set():
                    try:
                        opcode, raw = ws.recv_data()
                        # Record complete-message receipt before parsing or callbacks.
                        received_ns = time.perf_counter_ns()
                        received_at = datetime.now().astimezone()
                    except self._module.WebSocketTimeoutException:
                        continue
                    if opcode == self._module.ABNF.OPCODE_CLOSE:
                        raise ConnectionError("设备已断开连接。")
                    rx_no += 1
                    self.on_event("packet", ReceivedPacket(raw, received_ns, received_at, rx_no))
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
        self._rx_no += 1
        self.on_event("packet", ReceivedPacket(raw, time.perf_counter_ns(),
                                                datetime.now().astimezone(), self._rx_no))

    def _send_control(self, event: str, sent: int, total: int, extra: str = "") -> None:
        text = f"CTRL {event} sent={sent} total={total}{extra}"
        self.on_event("arduino_line", ArduinoLine("RX", text, datetime.now().astimezone(),
                                                   received_ns=time.perf_counter_ns()))

    def _send_gpio(self, event: str, *, ready: bool, rad_on: bool) -> None:
        stamp_ns = time.perf_counter_ns()
        self._gpio_ready = ready
        self._gpio_rad_on = rad_on
        if event not in ("BOOT", "STATE"):
            self._gpio_sequence += 1
        self.on_event("arduino_report", ArduinoReport(
            (stamp_ns - self._gpio_started_ns) // 1_000_000, event, self._gpio_sequence,
            ready, rad_on, False, 0, True, stamp_ns, datetime.now().astimezone(),
        ))

    def _pause(self, seconds: float) -> bool:
        """Keep the simulated serial state current while waiting for a deadline."""
        while seconds > 1.0:
            if self._stop.wait(1.0):
                return True
            self._send_gpio("STATE", ready=self._gpio_ready, rad_on=self._gpio_rad_on)
            seconds -= 1.0
        return self._stop.wait(seconds)

    def _run(self) -> None:
        self._rx_no = 0
        self.on_event("connected", self.endpoint)
        self.on_event("arduino_connected", "演示串口")
        self._gpio_started_ns = time.perf_counter_ns()
        self._gpio_sequence = 0
        self._send_gpio("BOOT", ready=True, rad_on=False)
        self._send(100, {"systemStatus": "Ready"})
        test_id = 1
        daily_id = 1
        scenario = 0
        try:
            while not self._stop.is_set():
                if not self._demo_cycle(scenario, test_id, daily_id):
                    break
                if scenario in (0, 2, 5):
                    test_id += 1
                if scenario != 3:
                    daily_id += 1
                scenario = (scenario + 1) % 6
        finally:
            self.on_event("arduino_disconnected", "演示已停止")
            self.on_event("disconnected", "演示已停止。")

    def _demo_cycle(self, scenario: int, test_id: int, daily_id: int) -> bool:
        double = scenario == 4
        self._send_control("DOUBLE_FIRST" if double else "TRIGGER", 1, 2 if double else 1)
        if scenario == 3:
            if self._pause(3.1):
                return False
            self._send_control("NO_RESPONSE", 1, 1, " rad_on=0 ms=3100")
            self._send_control("SUMMARY", 1, 1, " no_response=1 rad_on_cycles=0")
            self._send_control("DONE", 1, 1)
            return not self._pause(0.5)

        analysis = {
            "testId": test_id, "dailyId": daily_id, "tidName": str(daily_id),
            "testDateTime": datetime.now().isoformat(), "elapsedTime": 0.5,
            "methodId": "alloyPlus-demo", "methodDispName": "Alloy Plus（演示）", "final": False,
        }
        chemistry = [
            {"elementName": "Fe", "concentration": 68.82, "error": 0.12},
            {"elementName": "Cr", "concentration": 18.10, "error": 0.06},
            {"elementName": "Ni", "concentration": 10.55, "error": 0.04},
            {"elementName": "Mo", "concentration": 2.53, "error": 0.02},
        ]
        self._send(702, {})
        self._send_gpio("READY", ready=False, rad_on=False)
        self._send(200, {})
        self._send_gpio("RAD_ON", ready=False, rad_on=True)
        exposure = {"exposureNum": 1, "maxExposures": 1}
        self._send(202, exposure)
        if self._pause(0.5):
            return False
        self._send(206, {"result": {"analysis": dict(analysis), "chemistry": chemistry}})
        if double:
            self._send_control("DOUBLE_SECOND", 2, 2)

        reason, code = {1: ("Proximity Failure", 6), 4: ("User Abort", 2)}.get(scenario, ("Test Complete", 0))
        self._send_gpio("RAD_ON", ready=False, rad_on=False)
        self._send(203, {**exposure, "finalExposureStatus": reason if code else "Time Elapsed"})
        self._send(201, {"stopReason": reason, "stopReasonInt": code})
        if scenario in (0, 5):
            if self._pause(0.25):
                return False
            analysis.update(final=True, elapsedTime=1)
            if scenario == 5:
                chemistry[0]["concentration"] = math.nan
            self._send(206, {"result": {"analysis": analysis, "processedChemistry": chemistry}})
        self._send_gpio("READY", ready=True, rad_on=False)
        self._send(100, {"systemStatus": "Ready"})
        if double:
            self._send_control("DOUBLE_DONE", 2, 2)
        else:
            self._send_control("CYCLE_END", 1, 1, " rad_on=1 ms=500")
            self._send_control("SUMMARY", 1, 1, " no_response=0 rad_on_cycles=1")
            self._send_control("DONE", 1, 1)
        # Let the real tracker reach its deadlines in demo mode.
        delay = {1: 3.2, 2: 5.2, 4: 3.2}.get(scenario, 1.5)
        return not self._pause(delay)
