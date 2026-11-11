#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vanta iX Listener Mode Monitor & 206 Result Exporter (PySide6)
==============================================================
基于 Olympus Vanta WebSocket API (Listener 模式) 开发的 Vanta iX 检测监控工具。
核心功能：
1. Listener 模式连接 Vanta iX ("Hi i am a listener")，不影响主控端或 PLC 控制。
2. 实时监控设备状态 (Notification 100 系统状态、139 GPIO 状态、200/201 启停、202/203/207 曝光进度、209 错误、702/704 触发)。
3. 捕获并解析 206 (ResultReceived) 结果：
   - 实时大屏显示当前 testID 与 dailyID (兼容 dailyId 与 tidName 字段)。
   - 严格监控 testID 是否连续递增，一旦发生跳号 (跳过某一个或多个递增 ID) 立即高亮告警并记录缺失的 testID。
   - 监控 dailyID 递增与跨日重置情况，作为双重监控手段。
   - 监控“有触发/启动 (200) 但停止 (201) 时未收到 206 结果”的漏检情况。
4. 自动与手动导出 206 结果 (原始 JSON 文件 + 汇总 CSV 表格 + 漏检异常日志)。
"""

from __future__ import annotations

import csv
import datetime
import json
import os
import socket
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
    from PySide6.QtGui import QAction, QColor, QFont, QBrush, QIcon
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QSpinBox,
        QSplitter,
        QStatusBar,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
    from PySide2.QtGui import QColor, QFont, QBrush, QIcon
    from PySide2.QtWidgets import (
        QAction,
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QSpinBox,
        QSplitter,
        QStatusBar,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    PYSIDE_VERSION = 2

try:
    import websocket  # websocket-client
    HAS_WEBSOCKET_CLIENT = True
except ImportError:
    HAS_WEBSOCKET_CLIENT = False

try:
    if PYSIDE_VERSION == 6:
        from PySide6.QtWebSockets import QWebSocket
    else:
        from PySide2.QtWebSockets import QWebSocket
    HAS_QT_WEBSOCKET = True
except ImportError:
    HAS_QT_WEBSOCKET = False


# ============================================================================
# 数据结构定义
# ============================================================================

@dataclass
class Result206Record:
    """存储单条 206 (ResultReceived) 检测结果的标准化数据"""
    seq_no: int
    recv_time: str
    test_date_time: str
    is_final: bool
    test_id: Optional[int]
    raw_test_id: Any
    daily_id: Optional[int]
    daily_id_str: str
    tid_name: str
    expected_test_id: Optional[int]
    id_status: str  # "OK", "FIRST", "SKIPPED", "DUPLICATE", "RESET/BACKWARD", "INTERMEDIATE(-1)"
    skipped_ids: List[int] = field(default_factory=list)
    daily_id_status: str = ""
    method_name: str = ""
    method_id: str = ""
    test_type: str = ""
    test_error_info: str = ""
    grade_summary: str = ""
    chemistry_summary: str = ""
    chemistry_list: List[Dict[str, Any]] = field(default_factory=list)
    grade_list: List[Dict[str, Any]] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)
    saved_json_path: str = ""


# ============================================================================
# WebSocket Listener 线程 (严格遵循 Vanta-API-master 规范)
# ============================================================================

class VantaListenerWorker(QThread):
    """
    后台 WebSocket 监听线程：
    连接 ws://<host>:<port>，发送文本消息 "Hi i am a listener"，
    验证响应 "Client connected as a listener."，随后持续接收 JSON 通知。
    """
    sig_connection_state = Signal(bool, str)       # (connected, status_text)
    sig_notification = Signal(dict, int)           # (parsed_json_dict, byte_len)
    sig_raw_log = Signal(str, str)                 # (level, message)

    LISTENER_HANDSHAKE = "Hi i am a listener"
    LISTENER_EXPECTED_REPLY = "Client connected as a listener."

    def __init__(
        self,
        host: str,
        port: int = 7860,
        auto_reconnect: bool = True,
        request_device_info: bool = False,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.host = host.strip()
        self.port = int(port)
        self.auto_reconnect = auto_reconnect
        self.request_device_info = request_device_info
        self._stop_event = threading.Event()
        self._ws: Optional[ Any ] = None

    def stop(self):
        self._stop_event.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass

    def _connect_and_handshake(self, url: str) -> Optional[Any]:
        """建立连接并执行 Vanta Listener 握手"""
        if not HAS_WEBSOCKET_CLIENT:
            raise RuntimeError("未找到 websocket-client 库，无法使用线程模式。")

        # 可选：按照 WebSocketTest.py 示例先用 discovery socket 查询设备状态
        if self.request_device_info:
            try:
                disc_ws = websocket.WebSocket()
                disc_ws.settimeout(4.0)
                disc_ws.connect(url)
                disc_ws.send("Request device info")  # 必须以 TEXT 发送
                info_reply = disc_ws.recv()
                if isinstance(info_reply, bytes):
                    info_reply = info_reply.decode("utf-8", errors="replace")
                self.sig_raw_log.emit("INFO", f"设备信息响应 (Request device info): {info_reply}")
                disc_ws.close()
            except Exception as exc:
                self.sig_raw_log.emit("WARN", f"查询设备信息失败 (继续尝试连接): {exc}")

        ws = websocket.WebSocket()
        ws.settimeout(5.0)
        self.sig_raw_log.emit("INFO", f"正在连接 {url} ...")
        ws.connect(url)

        # 发送 Listener 握手指令（API 文档要求：区分大小写，小写的 'i'，且必须作为 TEXT 发送）
        ws.send(self.LISTENER_HANDSHAKE)
        self.sig_raw_log.emit("INFO", f"已发送握手指令: '{self.LISTENER_HANDSHAKE}'")

        reply = ws.recv()
        if isinstance(reply, bytes):
            reply = reply.decode("utf-8", errors="replace")
        reply_str = str(reply).strip()
        self.sig_raw_log.emit("INFO", f"收到握手响应: '{reply_str}'")

        if self.LISTENER_EXPECTED_REPLY in reply_str:
            # 握手成功，将 recv 超时设为较短时间以便响应停止信号
            ws.settimeout(1.0)
            return ws
        else:
            # 即使响应文本不完全一致，若不是 Rejecting 也可提示用户
            if "Rejecting" in reply_str:
                ws.close()
                raise ConnectionRefusedError(f"设备拒绝连接: {reply_str}")
            ws.settimeout(1.0)
            self.sig_raw_log.emit(
                "WARN",
                f"握手返回非标准文本 '{reply_str}' (期望 '{self.LISTENER_EXPECTED_REPLY}')，继续监听...",
            )
            return ws

    def run(self):
        url = f"ws://{self.host}:{self.port}"
        while not self._stop_event.is_set():
            try:
                self._ws = self._connect_and_handshake(url)
                self.sig_connection_state.emit(True, f"已连接 Listener ({url})")
                self.sig_raw_log.emit("SUCCESS", f"成功以 Listener 模式连接到 Vanta iX ({url})")

                # 持续接收消息循环
                while not self._stop_event.is_set():
                    try:
                        raw_msg = self._ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    except socket.timeout:
                        continue

                    if raw_msg is None or raw_msg == "":
                        raise ConnectionError("WebSocket 连接已由远端关闭 (收到空帧)")

                    byte_len = len(raw_msg) if isinstance(raw_msg, (bytes, str)) else 0
                    if isinstance(raw_msg, bytes):
                        text_msg = raw_msg.decode("utf-8", errors="replace")
                    else:
                        text_msg = str(raw_msg)

                    text_stripped = text_msg.strip()
                    if not text_stripped:
                        continue

                    # 忽略登录时可能出现的 checksum 字符串 ("checksum:5d2f4290...")
                    if text_stripped.startswith("checksum:"):
                        self.sig_raw_log.emit("DEBUG", f"收到 checksum 消息: {text_stripped}")
                        continue

                    try:
                        data = json.loads(text_stripped)
                        if isinstance(data, dict):
                            self.sig_notification.emit(data, byte_len)
                        else:
                            self.sig_raw_log.emit("DEBUG", f"收到非字典 JSON: {text_stripped[:200]}")
                    except json.JSONDecodeError:
                        self.sig_raw_log.emit("INFO", f"收到纯文本消息: {text_stripped[:300]}")

            except Exception as exc:
                if self._stop_event.is_set():
                    break
                err_msg = f"连接断开或异常: {exc}"
                self.sig_connection_state.emit(False, err_msg)
                self.sig_raw_log.emit("ERROR", err_msg)
            finally:
                if self._ws is not None:
                    try:
                        self._ws.close()
                    except Exception:
                        pass
                    self._ws = None

            if self._stop_event.is_set() or not self.auto_reconnect:
                break

            # 自动重连等待 2 秒
            self.sig_raw_log.emit("INFO", "将在 2 秒后尝试自动重连...")
            for _ in range(20):
                if self._stop_event.is_set():
                    break
                time.sleep(0.1)

        self.sig_connection_state.emit(False, "未连接")
        self.sig_raw_log.emit("INFO", "监听线程已停止。")


# ============================================================================
# Qt 原生 QWebSocket 监听器备用实现 (当 websocket-client 未安装时自动启用)
# ============================================================================

class QtWebSocketListener(QObject):
    """使用 PySide 自带的 QWebSocket 实现同样的 Vanta Listener 协议"""
    sig_connection_state = Signal(bool, str)
    sig_notification = Signal(dict, int)
    sig_raw_log = Signal(str, str)

    LISTENER_HANDSHAKE = "Hi i am a listener"
    LISTENER_EXPECTED_REPLY = "Client connected as a listener."

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.ws = QWebSocket() if HAS_QT_WEBSOCKET else None
        self.host = ""
        self.port = 7860
        self.auto_reconnect = True
        self._active = False
        self._handshake_done = False

        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.setSingleShot(True)
        self.reconnect_timer.timeout.connect(self._do_connect)

        if self.ws is not None:
            self.ws.connected.connect(self._on_connected)
            self.ws.disconnected.connect(self._on_disconnected)
            self.ws.textMessageReceived.connect(self._on_text_message)
            self.ws.binaryMessageReceived.connect(self._on_binary_message)

    def start_listen(self, host: str, port: int, auto_reconnect: bool = True):
        self.host = host.strip()
        self.port = int(port)
        self.auto_reconnect = auto_reconnect
        self._active = True
        self._do_connect()

    def stop(self):
        self._active = False
        self.reconnect_timer.stop()
        if self.ws is not None:
            self.ws.close()
        self.sig_connection_state.emit(False, "未连接")

    def _do_connect(self):
        if not self._active or self.ws is None:
            return
        self._handshake_done = False
        url = f"ws://{self.host}:{self.port}"
        self.sig_raw_log.emit("INFO", f"[QWebSocket] 正在连接 {url} ...")
        self.ws.open(QUrl(url))

    def _on_connected(self):
        self.sig_raw_log.emit("INFO", f"已连接，发送握手: '{self.LISTENER_HANDSHAKE}'")
        self.ws.sendTextMessage(self.LISTENER_HANDSHAKE)

    def _on_disconnected(self):
        self.sig_connection_state.emit(False, "连接已断开")
        if self._active and self.auto_reconnect:
            self.sig_raw_log.emit("WARN", "连接断开，2 秒后自动重连...")
            self.reconnect_timer.start(2000)

    def _on_text_message(self, msg: str):
        if not self._handshake_done:
            self._handshake_done = True
            self.sig_raw_log.emit("INFO", f"收到握手响应: '{msg}'")
            if "Rejecting" in msg:
                self.sig_raw_log.emit("ERROR", f"设备拒绝连接: {msg}")
                self.stop()
                return
            self.sig_connection_state.emit(True, f"已连接 Listener (ws://{self.host}:{self.port})")
            return
        self._parse_payload(msg, len(msg.encode("utf-8", errors="ignore")))

    def _on_binary_message(self, data):
        raw_bytes = bytes(data)
        text = raw_bytes.decode("utf-8", errors="replace")
        self._parse_payload(text, len(raw_bytes))

    def _parse_payload(self, text: str, byte_len: int):
        text_stripped = text.strip()
        if not text_stripped or text_stripped.startswith("checksum:"):
            return
        try:
            obj = json.loads(text_stripped)
            if isinstance(obj, dict):
                self.sig_notification.emit(obj, byte_len)
        except Exception:
            self.sig_raw_log.emit("INFO", f"收到非 JSON 文本: {text_stripped[:200]}")


# ============================================================================
# 主界面窗口
# ============================================================================

class VantaIXListenerGUI(QMainWindow):
    """Vanta iX 漏检监控与 206 结果导出 GUI"""

    NOTIFICATION_NAMES = {
        100: "SystemStatus (系统状态)",
        103: "BatteryStatus (电池状态)",
        110: "DevicePluggedIntoAC (外接电源连接)",
        111: "DeviceDisconnectedFromAC (外接电源断开)",
        123: "USBStorageStatusChanged (U盘状态)",
        124: "SDCardStatusChanged (SD卡状态)",
        131: "HardwareConfigurationChanged (硬件配置)",
        132: "HardwareStatus (硬件实时参数)",
        139: "DigitalIOStateChanged (GPIO状态改变)",
        200: "TestStarted (检测开始)",
        201: "TestStopped (检测停止)",
        202: "ExposureStarted (射线曝光开始)",
        203: "ExposureStopped (射线曝光结束)",
        204: "SpectrumUpdate (谱图更新)",
        206: "ResultReceived (206检测结果)",
        207: "ExposureStatus (曝光进度状态)",
        208: "CalCheckRequired (需要校准检查)",
        209: "ErrorDuringTest (检测过程出错)",
        300: "SettingsChanged (设置改变)",
        301: "MethodLoaded (方法已加载)",
        302: "MethodLoading (方法加载中)",
        701: "NewLogMessages (设备日志)",
        702: "TriggerPulled (触发信号/开始按键)",
        704: "KeyPressed (按键状态 6按下/7释放)",
        771: "BeamSettingsChanged (束流设置改变)",
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vanta iX 漏检监控系统 (Listener 模式 - 206结果导出 & testID/dailyID 跳号监控)")
        self.resize(1380, 880)

        # 运行状态与统计计数器
        self.listener_worker: Optional[VantaListenerWorker] = None
        self.qt_listener: Optional[QtWebSocketListener] = None
        self.is_connected = False
        self.session_start_time: Optional[datetime.datetime] = None

        self.total_messages = 0
        self.total_bytes = 0
        self.trigger_count = 0          # 702 / 704(key=6) 触发计数
        self.test_started_count = 0     # 200 TestStarted 计数
        self.test_stopped_count = 0     # 201 TestStopped 计数
        self.result_206_total_count = 0 # 收到 206 的总次数（含中间结果）
        self.result_206_final_count = 0 # 收到有效/最终 206 的次数
        self.test_error_count = 0       # 209 ErrorDuringTest 计数

        # testID 与 dailyID 核心监控状态
        self.last_valid_test_id: Optional[int] = None
        self.current_test_id: Optional[int] = None
        self.last_valid_daily_id: Optional[int] = None
        self.current_daily_id_str: str = "--"

        self.skipped_event_count = 0        # 发生跳号的次数
        self.skipped_ids_total_count = 0    # 累计缺失的 testID 总数
        self.all_skipped_ids: List[int] = []

        # 监控“有启动 (200) 但无 206 结果即停止 (201)”的漏检情况
        self.in_active_test = False
        self.active_test_start_time: Optional[datetime.datetime] = None
        self.active_test_got_206_final = False
        self.active_test_got_any_206 = False
        self.no_result_stop_count = 0       # 启动后未出最终结果就停止的次数

        # 存储所有捕获的 206 记录
        self.records_206: List[Result206Record] = []

        # 模拟测试内部计数器
        self._sim_test_id = 1000
        self._sim_daily_id = 1

        # 默认导出目录
        default_export = Path(__file__).resolve().parent / "exports_206"
        self.export_dir = default_export
        self.session_csv_path = self._build_session_csv_path()

        # 初始化 UI
        self._init_ui()
        self._load_config_if_exists()

        # 界面定时刷新器 (更新运行时长等)
        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._on_ui_timer)
        self.ui_timer.start(1000)

    def _build_session_csv_path(self) -> Path:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.export_dir / f"vanta_206_summary_{ts}.csv"

    def _load_config_if_exists(self):
        """尝试读取工作区或示例目录中的配置文件以填充默认 IP"""
        candidates = [
            Path(__file__).resolve().parent / "configuration.json",
            Path(__file__).resolve().parent
            / "Vanta-API-master"
            / "Vanta_API_Sample_Code"
            / "Python-WebSocketApp"
            / "configuration_example.json",
        ]
        for cfg_path in candidates:
            if cfg_path.exists():
                try:
                    raw = cfg_path.read_text(encoding="utf-8", errors="ignore")
                    # 处理 configuration_example.json 中可能存在的尾随逗号
                    cleaned = raw.replace(",\n}", "\n}").replace(",\r\n}", "\r\n}")
                    cfg = json.loads(cleaned)
                    if cfg.get("connection") == "USB":
                        self.host_input.setText("192.168.7.2")
                    elif cfg.get("host"):
                        self.host_input.setText(str(cfg["host"]))
                    if cfg.get("port"):
                        self.port_input.setValue(int(cfg["port"]))
                    self._append_event_log("INFO", f"已从 {cfg_path.name} 读取默认连接地址: {self.host_input.text()}")
                    break
                except Exception:
                    pass

    # ========================================================================
    # UI 构建
    # ========================================================================

    def _init_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # 1. 顶部连接与导出配置栏
        main_layout.addWidget(self._create_connection_bar())

        # 2. 核心监控看板 (testID / dailyID / 跳号监控 / Vanta iX 实时状态)
        main_layout.addWidget(self._create_dashboard_panel())

        # 3. 中部主体分割区域：左侧 206 结果表格，右侧详情与日志标签页
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._create_206_table_panel())
        splitter.addWidget(self._create_right_tabs_panel())
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 4)
        main_layout.addWidget(splitter, stretch=1)

        # 4. 底部模拟测试工具栏 (用于离线验证与现场调试)
        main_layout.addWidget(self._create_simulator_bar())

        # 5. 状态栏
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.lbl_uptime = QLabel("运行时长: 00:00:00 | 消息数: 0 | 流量: 0 B")
        self.status_bar.addPermanentWidget(self.lbl_uptime)
        self.status_bar.showMessage("就绪 - 请确认 Vanta iX IP 地址后点击【连接监听 (Listener)】")

    def _create_connection_bar(self) -> QGroupBox:
        group = QGroupBox("连接与 206 导出设置 (Listener 监听模式)")
        layout = QHBoxLayout(group)
        layout.setSpacing(10)

        # 连接预设与 IP
        layout.addWidget(QLabel("连接方式:"))
        self.conn_preset_combo = QComboBox()
        self.conn_preset_combo.addItems(["局域网 IP (LAN)", "USB OTG (192.168.7.2)"])
        self.conn_preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        layout.addWidget(self.conn_preset_combo)

        layout.addWidget(QLabel("Vanta iX 地址:"))
        self.host_input = QLineEdit("10.163.210.80")
        self.host_input.setPlaceholderText("例如 10.163.210.80 或 192.168.7.2")
        self.host_input.setMinimumWidth(145)
        layout.addWidget(self.host_input)

        layout.addWidget(QLabel("端口:"))
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(7860)
        layout.addWidget(self.port_input)

        self.chk_auto_reconnect = QCheckBox("断线自动重连")
        self.chk_auto_reconnect.setChecked(True)
        layout.addWidget(self.chk_auto_reconnect)

        self.btn_connect = QPushButton("连接监听 (Listener)")
        self.btn_connect.setMinimumHeight(32)
        self.btn_connect.setStyleSheet(
            "QPushButton { background-color: #1976D2; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1565C0; }"
        )
        self.btn_connect.clicked.connect(self._on_toggle_connect)
        layout.addWidget(self.btn_connect)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # 过滤与导出选项
        self.chk_final_only = QCheckBox("仅对 Final(最终) 206 校验跳号")
        self.chk_final_only.setChecked(True)
        self.chk_final_only.setToolTip(
            "Vanta 在检测过程中可能会发送 final=false (testId=-1) 的中间结果，勾选此项可只针对有效最终结果校验 testID 递增。"
        )
        layout.addWidget(self.chk_final_only)

        self.chk_auto_export = QCheckBox("实时自动导出 206 (JSON+CSV)")
        self.chk_auto_export.setChecked(True)
        layout.addWidget(self.chk_auto_export)

        layout.addWidget(QLabel("导出目录:"))
        self.export_dir_edit = QLineEdit(str(self.export_dir))
        self.export_dir_edit.setMinimumWidth(180)
        layout.addWidget(self.export_dir_edit, stretch=1)

        btn_browse = QPushButton("选择目录...")
        btn_browse.clicked.connect(self._on_choose_export_dir)
        layout.addWidget(btn_browse)

        btn_export_now = QPushButton("导出汇总 CSV")
        btn_export_now.clicked.connect(self._on_manual_export_csv)
        layout.addWidget(btn_export_now)

        return group

    def _create_dashboard_panel(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # --- 卡片 1: testID 与 dailyID 核心监控卡片 ---
        id_group = QGroupBox("核心 ID 监控 (206 ResultReceived)")
        id_grid = QGridLayout(id_group)

        big_font = QFont("Arial", 22, QFont.Bold)
        mid_font = QFont("Arial", 14, QFont.Bold)

        id_grid.addWidget(QLabel("当前 testID:"), 0, 0)
        self.lbl_current_test_id = QLabel("--")
        self.lbl_current_test_id.setFont(big_font)
        self.lbl_current_test_id.setStyleSheet("color: #1565C0;")
        id_grid.addWidget(self.lbl_current_test_id, 0, 1)

        id_grid.addWidget(QLabel("上一个 testID:"), 1, 0)
        self.lbl_prev_test_id = QLabel("--")
        self.lbl_prev_test_id.setFont(mid_font)
        id_grid.addWidget(self.lbl_prev_test_id, 1, 1)

        id_grid.addWidget(QLabel("当前 dailyID:"), 0, 2)
        self.lbl_current_daily_id = QLabel("--")
        self.lbl_current_daily_id.setFont(big_font)
        self.lbl_current_daily_id.setStyleSheet("color: #00897B;")
        self.lbl_current_daily_id.setToolTip("显示 206 analysis 中的 dailyId / tidName (每日递增编号，午夜重置)")
        id_grid.addWidget(self.lbl_current_daily_id, 0, 3)

        id_grid.addWidget(QLabel("上一个 dailyID:"), 1, 2)
        self.lbl_prev_daily_id = QLabel("--")
        self.lbl_prev_daily_id.setFont(mid_font)
        id_grid.addWidget(self.lbl_prev_daily_id, 1, 3)

        layout.addWidget(id_group, stretch=3)

        # --- 卡片 2: 漏检与跳号诊断看板 ---
        diag_group = QGroupBox("漏检 / testID 跳号监控诊断")
        diag_grid = QGridLayout(diag_group)

        self.lbl_sequence_banner = QLabel("状态正常 (等待 206 数据)")
        self.lbl_sequence_banner.setAlignment(Qt.AlignCenter)
        self.lbl_sequence_banner.setFont(QFont("Arial", 13, QFont.Bold))
        self.lbl_sequence_banner.setMinimumHeight(38)
        self.lbl_sequence_banner.setStyleSheet(
            "background-color: #E8F5E9; color: #2E7D32; border: 1px solid #A5D6A7; border-radius: 4px; padding: 4px;"
        )
        diag_grid.addWidget(self.lbl_sequence_banner, 0, 0, 1, 4)

        diag_grid.addWidget(QLabel("跳号发生次数:"), 1, 0)
        self.lbl_skip_events = QLabel("0")
        self.lbl_skip_events.setFont(mid_font)
        diag_grid.addWidget(self.lbl_skip_events, 1, 1)

        diag_grid.addWidget(QLabel("累计缺失 testID 数:"), 1, 2)
        self.lbl_skipped_total = QLabel("0")
        self.lbl_skipped_total.setFont(mid_font)
        diag_grid.addWidget(self.lbl_skipped_total, 1, 3)

        diag_grid.addWidget(QLabel("有启动无206结果:"), 2, 0)
        self.lbl_no_result_stops = QLabel("0")
        self.lbl_no_result_stops.setFont(mid_font)
        self.lbl_no_result_stops.setToolTip("收到 200(TestStarted) 后收到 201(TestStopped)，但未收到最终 206 结果的次数")
        diag_grid.addWidget(self.lbl_no_result_stops, 2, 1)

        btn_reset_alarm = QPushButton("重置基线/清除告警")
        btn_reset_alarm.clicked.connect(self._on_reset_baseline)
        diag_grid.addWidget(btn_reset_alarm, 2, 2, 1, 2)

        layout.addWidget(diag_group, stretch=3)

        # --- 卡片 3: Vanta iX 设备实时状态看板 ---
        dev_group = QGroupBox("Vanta iX 实时状态监控")
        dev_grid = QGridLayout(dev_group)

        dev_grid.addWidget(QLabel("连接状态:"), 0, 0)
        self.lbl_conn_badge = QLabel("● 未连接")
        self.lbl_conn_badge.setStyleSheet("color: #757575; font-weight: bold;")
        dev_grid.addWidget(self.lbl_conn_badge, 0, 1)

        dev_grid.addWidget(QLabel("X-Ray 状态:"), 0, 2)
        self.lbl_xray_badge = QLabel("● 射线关闭 (OFF)")
        self.lbl_xray_badge.setStyleSheet("color: #388E3C; font-weight: bold;")
        dev_grid.addWidget(self.lbl_xray_badge, 0, 3)

        dev_grid.addWidget(QLabel("系统状态 (100):"), 1, 0)
        self.lbl_sys_status = QLabel("--")
        self.lbl_sys_status.setStyleSheet("font-weight: bold;")
        dev_grid.addWidget(self.lbl_sys_status, 1, 1, 1, 3)

        dev_grid.addWidget(QLabel("曝光进度 (207):"), 2, 0)
        self.exposure_bar = QProgressBar()
        self.exposure_bar.setRange(0, 100)
        self.exposure_bar.setValue(0)
        self.exposure_bar.setFormat("空闲")
        dev_grid.addWidget(self.exposure_bar, 2, 1, 1, 3)

        dev_grid.addWidget(QLabel("GPIO (139):"), 3, 0)
        self.lbl_gpio_status = QLabel("B1:-- B2:-- B3:-- B4:--")
        self.lbl_gpio_status.setFont(QFont("Courier", 10))
        dev_grid.addWidget(self.lbl_gpio_status, 3, 1, 1, 3)

        stats_text = "触发(702): 0 | 开始(200): 0 | 停止(201): 0 | 206最终/总数: 0/0 | 错误(209): 0"
        self.lbl_lifecycle_counts = QLabel(stats_text)
        self.lbl_lifecycle_counts.setStyleSheet("color: #455A64; font-size: 11px;")
        dev_grid.addWidget(self.lbl_lifecycle_counts, 4, 0, 1, 4)

        layout.addWidget(dev_group, stretch=4)

        return container

    def _create_206_table_panel(self) -> QGroupBox:
        group = QGroupBox("206 (ResultReceived) 检测结果实时监控表 (点击行查看完整 JSON 与元素详情)")
        layout = QVBoxLayout(group)

        self.table_206 = QTableWidget(0, 12)
        headers = [
            "序号",
            "接收时间",
            "设备测试时间",
            "Final",
            "testID",
            "期望testID",
            "testID状态",
            "跳过/缺失ID",
            "dailyID (tidName)",
            "方法 (Method)",
            "牌号匹配 (Grade)",
            "主要化学成分 / 错误信息",
        ]
        self.table_206.setHorizontalHeaderLabels(headers)
        self.table_206.setAlternatingRowColors(True)
        self.table_206.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_206.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_206.itemSelectionChanged.connect(self._on_table_206_selection_changed)

        header_view = self.table_206.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.Interactive)
        header_view.setStretchLastSection(True)
        self.table_206.setColumnWidth(0, 50)
        self.table_206.setColumnWidth(1, 90)
        self.table_206.setColumnWidth(2, 145)
        self.table_206.setColumnWidth(3, 55)
        self.table_206.setColumnWidth(4, 75)
        self.table_206.setColumnWidth(5, 80)
        self.table_206.setColumnWidth(6, 110)
        self.table_206.setColumnWidth(7, 110)
        self.table_206.setColumnWidth(8, 115)
        self.table_206.setColumnWidth(9, 100)
        self.table_206.setColumnWidth(10, 120)

        layout.addWidget(self.table_206)
        return group

    def _create_right_tabs_panel(self) -> QTabWidget:
        self.right_tabs = QTabWidget()

        # Tab 1: 漏检与异常告警日志
        tab_alarms = QWidget()
        alarm_layout = QVBoxLayout(tab_alarms)
        self.txt_alarms = QTextEdit()
        self.txt_alarms.setReadOnly(True)
        self.txt_alarms.setFont(QFont("Menlo", 10))
        self.txt_alarms.setPlaceholderText("此处实时记录所有 testID 跳号、dailyID 异常、启动后未出 206 结果、209 报错等疑似漏检事件...")
        alarm_layout.addWidget(self.txt_alarms)
        btn_export_alarms = QPushButton("导出漏检告警日志")
        btn_export_alarms.clicked.connect(self._on_export_alarms)
        alarm_layout.addWidget(btn_export_alarms)
        self.right_tabs.addTab(tab_alarms, "⚠️ 漏检与跳号告警")

        # Tab 2: 选中 206 结果的化学成分与完整 JSON
        tab_detail = QWidget()
        detail_layout = QVBoxLayout(tab_detail)

        detail_splitter = QSplitter(Qt.Vertical)
        self.chem_table = QTableWidget(0, 3)
        self.chem_table.setHorizontalHeaderLabels(["元素 (Element)", "浓度 (Conc %)", "误差 (1σ Error)"])
        self.chem_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.chem_table.setEditTriggers(QTableWidget.NoEditTriggers)
        detail_splitter.addWidget(self.chem_table)

        self.txt_json_detail = QTextEdit()
        self.txt_json_detail.setReadOnly(True)
        self.txt_json_detail.setFont(QFont("Menlo", 10))
        detail_splitter.addWidget(self.txt_json_detail)

        detail_layout.addWidget(detail_splitter)
        btn_save_single_json = QPushButton("另存当前选中 206 为 JSON 文件...")
        btn_save_single_json.clicked.connect(self._on_save_selected_json)
        detail_layout.addWidget(btn_save_single_json)
        self.right_tabs.addTab(tab_detail, "🔍 206 结果详情 & JSON")

        # Tab 3: Vanta 实时消息事件流日志
        tab_events = QWidget()
        events_layout = QVBoxLayout(tab_events)
        self.txt_events = QTextEdit()
        self.txt_events.setReadOnly(True)
        self.txt_events.setFont(QFont("Menlo", 9))
        self.txt_events.document().setMaximumBlockCount(1000)
        events_layout.addWidget(self.txt_events)

        btn_clear_events = QPushButton("清空事件流日志")
        btn_clear_events.clicked.connect(self.txt_events.clear)
        events_layout.addWidget(btn_clear_events)
        self.right_tabs.addTab(tab_events, "📡 实时 API 事件流")

        return self.right_tabs

    def _create_simulator_bar(self) -> QGroupBox:
        group = QGroupBox("离线仿真调试工具 (无需连接真实 Vanta iX 即可验证监控与导出逻辑)")
        layout = QHBoxLayout(group)

        btn_sim_normal = QPushButton("模拟正常检测 (testID +1, dailyID +1)")
        btn_sim_normal.clicked.connect(self._sim_normal_test)
        layout.addWidget(btn_sim_normal)

        btn_sim_skip = QPushButton("模拟 testID 跳号漏检 (跳过 2 个 testID)")
        btn_sim_skip.setStyleSheet("color: #C62828; font-weight: bold;")
        btn_sim_skip.clicked.connect(self._sim_skipped_test_id)
        layout.addWidget(btn_sim_skip)

        btn_sim_no_206 = QPushButton("模拟有触发/启动(200)但无206结果即停止(201)")
        btn_sim_no_206.setStyleSheet("color: #E65100; font-weight: bold;")
        btn_sim_no_206.clicked.connect(self._sim_test_without_206)
        layout.addWidget(btn_sim_no_206)

        btn_clear_all = QPushButton("清空所有监控记录")
        btn_clear_all.clicked.connect(self._on_clear_all_records)
        layout.addWidget(btn_clear_all)

        layout.addStretch(1)
        return group

    # ========================================================================
    # 交互槽函数
    # ========================================================================

    @Slot(int)
    def _on_preset_changed(self, idx: int):
        if idx == 1:
            self.host_input.setText("192.168.7.2")
        elif self.host_input.text().strip() == "192.168.7.2":
            self.host_input.setText("10.163.210.80")

    @Slot()
    def _on_choose_export_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择 206 结果导出目录", str(self.export_dir))
        if folder:
            self.export_dir = Path(folder)
            self.export_dir_edit.setText(str(self.export_dir))
            self.session_csv_path = self._build_session_csv_path()

    @Slot()
    def _on_toggle_connect(self):
        if self.is_connected or (self.listener_worker is not None and self.listener_worker.isRunning()):
            self._stop_listening()
        else:
            self._start_listening()

    def _start_listening(self):
        host = self.host_input.text().strip()
        port = self.port_input.value()
        if not host:
            QMessageBox.warning(self, "参数错误", "请输入 Vanta iX 的 IP 地址或主机名！")
            return

        self.export_dir = Path(self.export_dir_edit.text().strip() or str(self.export_dir))
        self.session_start_time = datetime.datetime.now()
        self.btn_connect.setText("停止监听")
        self.btn_connect.setStyleSheet(
            "QPushButton { background-color: #D32F2F; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #B71C1C; }"
        )
        self.host_input.setEnabled(False)
        self.port_input.setEnabled(False)
        self.conn_preset_combo.setEnabled(False)

        if HAS_WEBSOCKET_CLIENT:
            self.listener_worker = VantaListenerWorker(
                host=host,
                port=port,
                auto_reconnect=self.chk_auto_reconnect.isChecked(),
                parent=self,
            )
            self.listener_worker.sig_connection_state.connect(self._on_connection_state_changed)
            self.listener_worker.sig_notification.connect(self._on_message_received)
            self.listener_worker.sig_raw_log.connect(self._append_event_log)
            self.listener_worker.start()
        elif HAS_QT_WEBSOCKET:
            if self.qt_listener is None:
                self.qt_listener = QtWebSocketListener(self)
                self.qt_listener.sig_connection_state.connect(self._on_connection_state_changed)
                self.qt_listener.sig_notification.connect(self._on_message_received)
                self.qt_listener.sig_raw_log.connect(self._append_event_log)
            self.qt_listener.start_listen(host, port, self.chk_auto_reconnect.isChecked())
        else:
            QMessageBox.critical(
                self,
                "缺少依赖",
                "未检测到 websocket-client 或 PySide QtWebSockets，请安装 websocket-client。",
            )
            self._stop_listening()

    def _stop_listening(self):
        if self.listener_worker is not None:
            self.listener_worker.stop()
            self.listener_worker.wait(2500)
            self.listener_worker = None
        if self.qt_listener is not None:
            self.qt_listener.stop()

        self.is_connected = False
        self.btn_connect.setText("连接监听 (Listener)")
        self.btn_connect.setStyleSheet(
            "QPushButton { background-color: #1976D2; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1565C0; }"
        )
        self.host_input.setEnabled(True)
        self.port_input.setEnabled(True)
        self.conn_preset_combo.setEnabled(True)
        self._on_connection_state_changed(False, "未连接")

    @Slot(bool, str)
    def _on_connection_state_changed(self, connected: bool, status_text: str):
        self.is_connected = connected
        if connected:
            self.lbl_conn_badge.setText(f"● {status_text}")
            self.lbl_conn_badge.setStyleSheet("color: #2E7D32; font-weight: bold;")
        else:
            self.lbl_conn_badge.setText(f"● {status_text}")
            self.lbl_conn_badge.setStyleSheet("color: #C62828; font-weight: bold;")
        self.status_bar.showMessage(status_text)

    # ========================================================================
    # Vanta API 消息分发与处理核心
    # ========================================================================

    @Slot(dict, int)
    def _on_message_received(self, data: Dict[str, Any], byte_len: int):
        """处理从 Vanta iX WebSocket 收到的每一条 JSON 消息"""
        self.total_messages += 1
        self.total_bytes += byte_len

        cmd_id = data.get("commandId")
        msg_id = data.get("id")
        params = data.get("params") or {}

        # Notification 消息的 commandId 固定为 403
        if cmd_id == 403:
            self._handle_notification(msg_id, params, data)
        else:
            self._append_event_log("INFO", f"收到响应消息 commandId={cmd_id}, id={msg_id}")

    def _handle_notification(self, notif_id: Any, params: Dict[str, Any], full_data: Dict[str, Any]):
        notif_name = self.NOTIFICATION_NAMES.get(notif_id, f"未知通知({notif_id})")

        # 204 SpectrumUpdate 高频消息不在事件流刷屏，其余通知记录日志
        if notif_id != 204:
            self._append_event_log("EVENT", f"[{notif_id}] {notif_name}")

        # 100: SystemStatus
        if notif_id == 100:
            sys_status = str(params.get("systemStatus", ""))
            info = str(params.get("info", ""))
            combined = f"{sys_status} ({info})" if info else sys_status
            self.lbl_sys_status.setText(combined or "--")
            if "X-rays on" in info or "X-rays on" in sys_status:
                self._set_xray_indicator(True)
            elif "X-rays off" in info or "Ready" in sys_status:
                self._set_xray_indicator(False)

        # 139: DigitalIOStateChanged (Vanta iX 专有 GPIO 状态)
        elif notif_id == 139:
            b1 = params.get("bank1", 0)
            b2 = params.get("bank2", 0)
            b3 = params.get("bank3", 0)
            b4 = params.get("bank4", 0)
            # bank4 高 4 位是 4 路用户数字输入
            in_bits = f"{(b4 >> 4) & 0x0F:04b}"
            out_bits = f"{b4 & 0x0F:04b}"
            self.lbl_gpio_status.setText(
                f"B1:{b1} B2:{b2} B3:{b3} B4:{b4}(0x{b4:02X} In:{in_bits} Out:{out_bits})"
            )

        # 702: TriggerPulled / 704: KeyPressed
        elif notif_id == 702:
            self.trigger_count += 1
            self._update_lifecycle_label()
            self._append_event_log("INFO", ">>> 收到硬件触发信号 (702 TriggerPulled / Start Pressed)")

        elif notif_id == 704:
            key_act = params.get("keyActivated")
            if key_act == 6:
                self.trigger_count += 1
                self._update_lifecycle_label()
                self._append_event_log("INFO", ">>> 收到按键/GPIO触发按下 (704 KeyPressed = 6)")

        # 200: TestStarted
        elif notif_id == 200:
            self.test_started_count += 1
            self.in_active_test = True
            self.active_test_start_time = datetime.datetime.now()
            self.active_test_got_206_final = False
            self.active_test_got_any_206 = False
            self.exposure_bar.setValue(0)
            self.exposure_bar.setFormat("检测已启动 (200)...")
            self._update_lifecycle_label()

        # 202: ExposureStarted
        elif notif_id == 202:
            exp_num = params.get("exposureNum", 1)
            max_exp = params.get("maxExposures", 1)
            self._set_xray_indicator(True)
            self.exposure_bar.setFormat(f"Beam {exp_num}/{max_exp} 曝光中...")

        # 207: ExposureStatus
        elif notif_id == 207:
            elapsed = float(params.get("elapsedTime", 0))
            total = float(params.get("totalTime", 1)) or 1.0
            exp_num = params.get("exposureNum", 1)
            max_exp = params.get("maxExposures", 1)
            pct = int(min(100, max(0, (elapsed / total) * 100)))
            self.exposure_bar.setValue(pct)
            self.exposure_bar.setFormat(f"Beam {exp_num}/{max_exp}: {elapsed:.0f}s / {total:.0f}s ({pct}%)")

        # 203: ExposureStopped
        elif notif_id == 203:
            status_str = params.get("finalExposureStatus", "")
            self.exposure_bar.setFormat(f"曝光结束 ({status_str})")

        # 206: ResultReceived (核心监控与导出对象！)
        elif notif_id == 206:
            self._process_result_206(full_data)

        # 201: TestStopped
        elif notif_id == 201:
            self.test_stopped_count += 1
            self._set_xray_indicator(False)
            stop_reason = str(params.get("stopReason", "Unknown"))
            stop_reason_int = params.get("stopReasonInt", 0)
            self.exposure_bar.setValue(100 if stop_reason == "Test Complete" else 0)
            self.exposure_bar.setFormat(f"已停止: {stop_reason}")

            # 检查是否存在“有 TestStarted(200) 但直到 TestStopped(201) 都未收到有效 206 结果”的漏检情形
            if self.in_active_test and not self.active_test_got_206_final:
                self.no_result_stop_count += 1
                self.lbl_no_result_stops.setText(str(self.no_result_stop_count))
                self.lbl_no_result_stops.setStyleSheet("color: #D32F2F; font-weight: bold;")
                alarm_msg = (
                    f"[漏检告警 - 有启动无206结果] 检测已停止 (201, 原因='{stop_reason}', code={stop_reason_int})，"
                    f"但本次检测期间未收到任何有效的最终 206 结果！(是否收到中间206: {self.active_test_got_any_206})"
                )
                self._record_alarm(alarm_msg)

            self.in_active_test = False
            self._update_lifecycle_label()

        # 209: ErrorDuringTest
        elif notif_id == 209:
            self.test_error_count += 1
            self._update_lifecycle_label()
            self._record_alarm(f"[检测错误 209 ErrorDuringTest] 参数: {json.dumps(params, ensure_ascii=False)}")

    # ========================================================================
    # 206 结果解析、testID 递增跳号监控、dailyID 提取与自动导出
    # ========================================================================

    @staticmethod
    def _parse_int_or_none(val: Any) -> Optional[int]:
        if val is None or val == "":
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    def _process_result_206(self, full_data: Dict[str, Any]):
        """解析 206 消息，监控 testID 跳号与 dailyID，更新表格并导出"""
        self.result_206_total_count += 1
        self.active_test_got_any_206 = True

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        params = full_data.get("params") or {}
        result_obj = params.get("result") or {}
        analysis = result_obj.get("analysis") or {}

        # 1. 提取 final 标志
        is_final = bool(analysis.get("final", False))

        # 2. 提取 testID (兼容 analysis.testId 和 result.testId)
        raw_test_id = analysis.get("testId")
        if raw_test_id is None or raw_test_id == -1:
            alt_test_id = result_obj.get("testId")
            if alt_test_id is not None and alt_test_id != -1:
                raw_test_id = alt_test_id
        test_id_int = self._parse_int_or_none(raw_test_id)

        # 3. 提取 dailyID (兼容 analysis.dailyId 与 analysis.tidName)
        # 根据 API 文档 results_file_structure.md: "tidName": "485" 是 daily test ID；
        # 而在 API-Command-List.md 示例中同时存在 "dailyId" 与 "tidName"
        raw_daily_id = analysis.get("dailyId")
        tid_name = str(analysis.get("tidName", "") or "").strip()

        daily_id_int: Optional[int] = None
        if raw_daily_id is not None and raw_daily_id != -1 and str(raw_daily_id).strip() != "":
            daily_id_int = self._parse_int_or_none(raw_daily_id)

        if daily_id_int is None and tid_name:
            daily_id_int = self._parse_int_or_none(tid_name)

        if daily_id_int is not None and tid_name and str(daily_id_int) != tid_name:
            daily_display = f"{daily_id_int} (tid:{tid_name})"
        elif daily_id_int is not None:
            daily_display = str(daily_id_int)
        elif tid_name:
            daily_display = tid_name
        else:
            daily_display = "-1" if raw_daily_id == -1 else "--"

        # 4. 判断该条 206 是否参与 testID 连续递增校验
        # 中间结果 (final=False 且 testId=-1) 尚未写入设备数据库，不具有有效 testId
        should_check_seq = True
        if self.chk_final_only.isChecked() and not is_final:
            should_check_seq = False
        if test_id_int is None or test_id_int < 0:
            should_check_seq = False

        expected_test_id: Optional[int] = None
        skipped_ids: List[int] = []
        id_status = "INTERMEDIATE(-1)"
        daily_id_status = ""

        if should_check_seq and test_id_int is not None:
            self.result_206_final_count += 1
            self.active_test_got_206_final = True

            # 更新看板上的上一个与当前 testID
            if self.current_test_id is not None:
                self.lbl_prev_test_id.setText(str(self.current_test_id))
            self.current_test_id = test_id_int
            self.lbl_current_test_id.setText(str(test_id_int))

            # 校验 testID 是否跳过某一个递增
            if self.last_valid_test_id is None:
                expected_test_id = test_id_int
                id_status = "FIRST (首条基线)"
                self.last_valid_test_id = test_id_int
                self._update_banner_status("OK", f"已建立基线 testID = {test_id_int}，监控递增中...")
            else:
                expected_test_id = self.last_valid_test_id + 1
                if test_id_int == expected_test_id:
                    id_status = "OK (正常递增)"
                    self.last_valid_test_id = test_id_int
                    if self.skipped_event_count == 0:
                        self._update_banner_status("OK", f"testID 连续正常 ({test_id_int - 1} → {test_id_int})")
                elif test_id_int > expected_test_id:
                    # 发生跳号！
                    skipped_ids = list(range(expected_test_id, test_id_int))
                    skip_cnt = len(skipped_ids)
                    id_status = f"SKIPPED (跳过 {skip_cnt} 个!)"
                    self.skipped_event_count += 1
                    self.skipped_ids_total_count += skip_cnt
                    self.all_skipped_ids.extend(skipped_ids)

                    self.lbl_skip_events.setText(str(self.skipped_event_count))
                    self.lbl_skip_events.setStyleSheet("color: #D32F2F; font-weight: bold;")
                    self.lbl_skipped_total.setText(str(self.skipped_ids_total_count))
                    self.lbl_skipped_total.setStyleSheet("color: #D32F2F; font-weight: bold;")

                    preview_ids = (
                        str(skipped_ids)
                        if len(skipped_ids) <= 10
                        else f"[{skipped_ids[0]}..{skipped_ids[-1]}] (共{skip_cnt}个)"
                    )
                    banner_msg = (
                        f"⚠️ 检测到 testID 跳号！上次:{self.last_valid_test_id} → 本次:{test_id_int} "
                        f"(缺失: {preview_ids})"
                    )
                    self._update_banner_status("SKIPPED", banner_msg)
                    self._record_alarm(
                        f"[testID 跳号告警] 期望 testID={expected_test_id}，实际收到 testID={test_id_int}，"
                        f"跳过了 {skip_cnt} 个 ID: {preview_ids} | 当前 dailyID={daily_display}"
                    )
                    self.last_valid_test_id = test_id_int
                elif test_id_int == self.last_valid_test_id:
                    id_status = "DUPLICATE (重复ID)"
                else:
                    id_status = f"RESET/BACKWARD (回退 {self.last_valid_test_id}->{test_id_int})"
                    self._record_alarm(
                        f"[testID 回退/重置提示] 上次 testID={self.last_valid_test_id}，本次收到 testID={test_id_int}"
                    )
                    self.last_valid_test_id = test_id_int

            # 同时更新并校验 dailyID
            if daily_id_int is not None and daily_id_int >= 0:
                if self.last_valid_daily_id is not None:
                    self.lbl_prev_daily_id.setText(str(self.last_valid_daily_id))
                    if daily_id_int == self.last_valid_daily_id + 1:
                        daily_id_status = "OK"
                    elif daily_id_int == 1 and self.last_valid_daily_id > 1:
                        daily_id_status = "MIDNIGHT_RESET (跨日重置为1)"
                        self._append_event_log("INFO", f"dailyID 已跨日重置为 1 (昨日最后 dailyID={self.last_valid_daily_id})")
                    elif daily_id_int > self.last_valid_daily_id + 1:
                        daily_skipped = list(range(self.last_valid_daily_id + 1, daily_id_int))
                        daily_id_status = f"DAILY_SKIPPED ({daily_skipped})"
                        self._record_alarm(
                            f"[dailyID 跳号告警] 上次 dailyID={self.last_valid_daily_id} → 本次 dailyID={daily_id_int}，"
                            f"缺失 dailyID: {daily_skipped}"
                        )
                self.last_valid_daily_id = daily_id_int
                self.current_daily_id_str = daily_display
                self.lbl_current_daily_id.setText(daily_display)
            elif daily_display not in ("--", "-1"):
                self.lbl_current_daily_id.setText(daily_display)

        # 5. 提取方法、时间、牌号、化学成分摘要
        test_dt = str(analysis.get("testDateTime", "") or "")
        method_disp = str(analysis.get("methodDispName", "") or "")
        method_id = str(analysis.get("methodId", "") or "")
        test_type = str(analysis.get("testType", "") or "")
        test_err = str(analysis.get("testErrorInfo", "") or "").strip()

        # 处理 CalCheck 结果或普通化学结果
        cal_check = result_obj.get("calCheckResult")
        grades = result_obj.get("gradeMatch") or []
        chemistry = result_obj.get("processedChemistry") or result_obj.get("chemistry") or []

        grade_parts = []
        for g in grades:
            g_name = g.get("gradeName", "")
            m_num = g.get("matchNumber", "")
            cutoff = g.get("passFailCutOff", -1)
            pf_str = ""
            try:
                if float(cutoff) >= 0:
                    pf_str = " [PASS]" if float(m_num) <= float(cutoff) else " [FAIL]"
            except Exception:
                pass
            if g_name:
                grade_parts.append(f"{g_name}({m_num:.2f}){pf_str}" if isinstance(m_num, float) else f"{g_name}{pf_str}")
        grade_summary = ", ".join(grade_parts) if grade_parts else ("CalCheck" if cal_check else "--")

        # 提取浓度 > 0 的前 5 个主要元素作为摘要
        non_zero_chem = [
            c for c in chemistry if isinstance(c, dict) and float(c.get("concentration", 0) or 0) > 0
        ]
        non_zero_chem.sort(key=lambda x: float(x.get("concentration", 0) or 0), reverse=True)
        chem_parts = [
            f"{c.get('elementName')}:{float(c.get('concentration', 0)):.2f}%"
            for c in non_zero_chem[:5]
        ]
        chem_summary = " ".join(chem_parts)
        if test_err and test_err.lower() != "no error":
            chem_summary = f"[Err: {test_err}] {chem_summary}"

        record = Result206Record(
            seq_no=len(self.records_206) + 1,
            recv_time=now_str,
            test_date_time=test_dt,
            is_final=is_final,
            test_id=test_id_int,
            raw_test_id=raw_test_id,
            daily_id=daily_id_int,
            daily_id_str=daily_display,
            tid_name=tid_name,
            expected_test_id=expected_test_id,
            id_status=id_status,
            skipped_ids=skipped_ids,
            daily_id_status=daily_id_status,
            method_name=method_disp or method_id,
            method_id=method_id,
            test_type=test_type,
            test_error_info=test_err,
            grade_summary=grade_summary,
            chemistry_summary=chem_summary,
            chemistry_list=chemistry,
            grade_list=grades,
            raw_data=full_data,
        )

        # 6. 自动导出 206 结果到磁盘 (JSON + CSV)
        if self.chk_auto_export.isChecked():
            # 如果勾选了“仅对 Final 校验”，中间结果是否也导出？这里仅当 is_final 或未勾选 final_only 时自动导出，避免中间帧过多
            if is_final or not self.chk_final_only.isChecked():
                self._auto_export_record(record)

        self.records_206.append(record)
        self._insert_record_to_table(record)
        self._update_lifecycle_label()

    def _auto_export_record(self, rec: Result206Record):
        """将单条 206 记录实时保存为独立 JSON 并追加到汇总 CSV"""
        try:
            self.export_dir = Path(self.export_dir_edit.text().strip() or str(self.export_dir))
            json_dir = self.export_dir / "json_206"
            json_dir.mkdir(parents=True, exist_ok=True)

            safe_ts = rec.recv_time.replace(":", "").replace(" ", "_").replace(".", "_")
            tid_tag = rec.test_id if rec.test_id is not None else "neg1"
            did_tag = rec.daily_id if rec.daily_id is not None else (rec.tid_name or "na")
            json_filename = f"206_seq{rec.seq_no:04d}_testID_{tid_tag}_dailyID_{did_tag}_{safe_ts}.json"
            json_path = json_dir / json_filename

            with open(json_path, "w", encoding="utf-8") as jf:
                json.dump(rec.raw_data, jf, indent=2, ensure_ascii=False)
            rec.saved_json_path = str(json_path)

            # 追加到 CSV
            self._append_record_to_csv(rec, self.session_csv_path)
        except Exception as exc:
            self._append_event_log("ERROR", f"自动导出 206 结果失败: {exc}")

    def _append_record_to_csv(self, rec: Result206Record, csv_path: Path):
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = csv_path.exists()
        with open(csv_path, "a", newline="", encoding="utf-8-sig") as cf:
            writer = csv.writer(cf)
            if not file_exists:
                writer.writerow([
                    "序号",
                    "接收时间",
                    "设备测试时间(UTC)",
                    "是否Final",
                    "testID",
                    "期望testID",
                    "testID递增状态",
                    "跳过缺失的testID",
                    "dailyID",
                    "tidName",
                    "dailyID状态",
                    "检测方法(Method)",
                    "方法ID(methodId)",
                    "测试类型(testType)",
                    "牌号匹配(gradeMatch)",
                    "错误信息(testErrorInfo)",
                    "主要元素成分(Chemistry)",
                    "原始JSON文件路径",
                ])
            writer.writerow([
                rec.seq_no,
                rec.recv_time,
                rec.test_date_time,
                rec.is_final,
                rec.test_id if rec.test_id is not None else rec.raw_test_id,
                rec.expected_test_id if rec.expected_test_id is not None else "",
                rec.id_status,
                ";".join(map(str, rec.skipped_ids)),
                rec.daily_id if rec.daily_id is not None else "",
                rec.tid_name,
                rec.daily_id_status,
                rec.method_name,
                rec.method_id,
                rec.test_type,
                rec.grade_summary,
                rec.test_error_info,
                rec.chemistry_summary,
                rec.saved_json_path,
            ])

    # ========================================================================
    # 表格与辅助 UI 更新
    # ========================================================================

    def _insert_record_to_table(self, rec: Result206Record):
        row = self.table_206.rowCount()
        self.table_206.insertRow(row)

        time_short = rec.recv_time.split(" ")[-1] if " " in rec.recv_time else rec.recv_time
        skipped_str = ", ".join(map(str, rec.skipped_ids)) if rec.skipped_ids else "--"

        values = [
            str(rec.seq_no),
            time_short,
            rec.test_date_time,
            "Yes" if rec.is_final else "No",
            str(rec.test_id if rec.test_id is not None else rec.raw_test_id),
            str(rec.expected_test_id) if rec.expected_test_id is not None else "--",
            rec.id_status,
            skipped_str,
            rec.daily_id_str,
            rec.method_name,
            rec.grade_summary,
            rec.chemistry_summary,
        ]

        # 根据状态着色
        bg_color: Optional[QColor] = None
        fg_color: Optional[QColor] = None
        if rec.id_status.startswith("SKIPPED"):
            bg_color = QColor("#FFEBEE")
            fg_color = QColor("#B71C1C")
        elif rec.id_status.startswith("RESET") or rec.id_status.startswith("DUPLICATE"):
            bg_color = QColor("#FFF8E1")
            fg_color = QColor("#E65100")
        elif not rec.is_final:
            fg_color = QColor("#78909C")

        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            if col in (0, 3, 4, 5, 8):
                item.setTextAlignment(Qt.AlignCenter)
            if bg_color is not None:
                item.setBackground(QBrush(bg_color))
            if fg_color is not None:
                item.setForeground(QBrush(fg_color))
            if col == 6 and rec.id_status.startswith("OK"):
                item.setForeground(QBrush(QColor("#2E7D32")))
            self.table_206.setItem(row, col, item)

        self.table_206.scrollToBottom()
        # 如果当前未选中任何行，或者只有第一行，自动展示最新行详情
        if self.table_206.rowCount() == 1 or rec.id_status.startswith("SKIPPED"):
            self.table_206.selectRow(row)

    @Slot()
    def _on_table_206_selection_changed(self):
        selected_rows = self.table_206.selectionModel().selectedRows()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        if 0 <= row < len(self.records_206):
            rec = self.records_206[row]
            self._display_record_detail(rec)

    def _display_record_detail(self, rec: Result206Record):
        # 更新化学成分表
        self.chem_table.setRowCount(0)
        sorted_chem = sorted(
            [c for c in rec.chemistry_list if isinstance(c, dict)],
            key=lambda x: float(x.get("concentration", 0) or 0),
            reverse=True,
        )
        for item_dict in sorted_chem:
            conc = float(item_dict.get("concentration", 0) or 0)
            err = float(item_dict.get("error", 0) or 0)
            el_name = str(item_dict.get("elementName", ""))
            r = self.chem_table.rowCount()
            self.chem_table.insertRow(r)
            self.chem_table.setItem(r, 0, QTableWidgetItem(el_name))
            self.chem_table.setItem(r, 1, QTableWidgetItem(f"{conc:.4f}"))
            self.chem_table.setItem(r, 2, QTableWidgetItem(f"{err:.4f}"))

        # 更新完整 JSON
        pretty_json = json.dumps(rec.raw_data, indent=2, ensure_ascii=False)
        self.txt_json_detail.setPlainText(pretty_json)

    def _set_xray_indicator(self, xray_on: bool):
        if xray_on:
            self.lbl_xray_badge.setText("☢️ 射线开启 (X-RAYS ON)")
            self.lbl_xray_badge.setStyleSheet(
                "background-color: #FFEBEE; color: #D32F2F; font-weight: bold; padding: 2px 6px; border-radius: 3px;"
            )
        else:
            self.lbl_xray_badge.setText("● 射线关闭 (OFF)")
            self.lbl_xray_badge.setStyleSheet("color: #388E3C; font-weight: bold;")

    def _update_banner_status(self, status_type: str, text: str):
        self.lbl_sequence_banner.setText(text)
        if status_type == "SKIPPED":
            self.lbl_sequence_banner.setStyleSheet(
                "background-color: #FFCDD2; color: #B71C1C; border: 2px solid #D32F2F; border-radius: 4px; padding: 4px;"
            )
        else:
            self.lbl_sequence_banner.setStyleSheet(
                "background-color: #E8F5E9; color: #2E7D32; border: 1px solid #A5D6A7; border-radius: 4px; padding: 4px;"
            )

    def _update_lifecycle_label(self):
        self.lbl_lifecycle_counts.setText(
            f"触发(702/704): {self.trigger_count} | 开始(200): {self.test_started_count} | "
            f"停止(201): {self.test_stopped_count} | 206最终/总数: {self.result_206_final_count}/{self.result_206_total_count} | "
            f"错误(209): {self.test_error_count}"
        )

    def _record_alarm(self, message: str):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{ts}] {message}"
        self.txt_alarms.append(line)
        self._append_event_log("ALARM", message)

        # 同时写入告警日志文件
        try:
            self.export_dir.mkdir(parents=True, exist_ok=True)
            alarm_file = self.export_dir / "vanta_missed_detection_alarms.log"
            with open(alarm_file, "a", encoding="utf-8") as af:
                af.write(line + "\n")
        except Exception:
            pass

    @Slot(str, str)
    def _append_event_log(self, level: str, message: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.txt_events.append(f"[{ts}] [{level}] {message}")

    @Slot()
    def _on_ui_timer(self):
        if self.session_start_time is not None and self.is_connected:
            delta = datetime.datetime.now() - self.session_start_time
            uptime_str = str(delta).split(".")[0]
        else:
            uptime_str = "00:00:00"

        if self.total_bytes >= 1024 * 1024:
            bytes_str = f"{self.total_bytes / (1024 * 1024):.2f} MB"
        elif self.total_bytes >= 1024:
            bytes_str = f"{self.total_bytes / 1024:.2f} KB"
        else:
            bytes_str = f"{self.total_bytes} B"

        self.lbl_uptime.setText(
            f"运行时长: {uptime_str} | 消息总数: {self.total_messages} | 累计流量: {bytes_str}"
        )

    # ========================================================================
    # 导出与重置操作
    # ========================================================================

    @Slot()
    def _on_manual_export_csv(self):
        if not self.records_206:
            QMessageBox.information(self, "提示", "当前尚无已捕获的 206 结果记录。")
            return

        default_file = str(self.export_dir / f"vanta_206_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        file_path, _ = QFileDialog.getSaveFileName(self, "导出 206 汇总结果 CSV", default_file, "CSV Files (*.csv)")
        if not file_path:
            return

        target = Path(file_path)
        if target.exists():
            target.unlink()
        for rec in self.records_206:
            self._append_record_to_csv(rec, target)

        QMessageBox.information(self, "导出成功", f"已成功导出 {len(self.records_206)} 条 206 记录至:\n{target}")

    @Slot()
    def _on_save_selected_json(self):
        selected_rows = self.table_206.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "提示", "请先在左侧表格中选择一条 206 记录。")
            return
        row = selected_rows[0].row()
        rec = self.records_206[row]
        default_name = str(self.export_dir / f"206_testID_{rec.test_id}_dailyID_{rec.daily_id_str}.json")
        file_path, _ = QFileDialog.getSaveFileName(self, "保存 206 原始 JSON", default_name, "JSON Files (*.json)")
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(rec.raw_data, f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "保存成功", f"已保存至:\n{file_path}")

    @Slot()
    def _on_export_alarms(self):
        content = self.txt_alarms.toPlainText().strip()
        if not content:
            QMessageBox.information(self, "提示", "当前没有漏检或跳号告警记录。")
            return
        default_name = str(self.export_dir / f"alarms_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        file_path, _ = QFileDialog.getSaveFileName(self, "导出告警日志", default_name, "Text Files (*.txt *.log)")
        if file_path:
            Path(file_path).write_text(content, encoding="utf-8")
            QMessageBox.information(self, "导出成功", f"告警日志已保存至:\n{file_path}")

    @Slot()
    def _on_reset_baseline(self):
        self.last_valid_test_id = self.current_test_id
        self.skipped_event_count = 0
        self.skipped_ids_total_count = 0
        self.no_result_stop_count = 0
        self.lbl_skip_events.setText("0")
        self.lbl_skip_events.setStyleSheet("")
        self.lbl_skipped_total.setText("0")
        self.lbl_skipped_total.setStyleSheet("")
        self.lbl_no_result_stops.setText("0")
        self.lbl_no_result_stops.setStyleSheet("")
        self._update_banner_status("OK", f"已重置监控基线 (当前基线 testID = {self.last_valid_test_id})")

    @Slot()
    def _on_clear_all_records(self):
        self.records_206.clear()
        self.table_206.setRowCount(0)
        self.chem_table.setRowCount(0)
        self.txt_json_detail.clear()
        self.txt_alarms.clear()
        self.last_valid_test_id = None
        self.current_test_id = None
        self.last_valid_daily_id = None
        self.lbl_current_test_id.setText("--")
        self.lbl_prev_test_id.setText("--")
        self.lbl_current_daily_id.setText("--")
        self.lbl_prev_daily_id.setText("--")
        self.trigger_count = 0
        self.test_started_count = 0
        self.test_stopped_count = 0
        self.result_206_total_count = 0
        self.result_206_final_count = 0
        self.test_error_count = 0
        self._on_reset_baseline()
        self._update_lifecycle_label()
        self.lbl_sequence_banner.setText("状态正常 (等待 206 数据)")

    # ========================================================================
    # 离线仿真器 (严格按照 API-Command-List.md 的消息结构生成仿真数据包)
    # ========================================================================

    def _build_mock_206_packet(self, test_id: int, daily_id: int, is_final: bool = True) -> Dict[str, Any]:
        now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        return {
            "commandId": 403,
            "id": 206,
            "params": {
                "result": {
                    "analysis": {
                        "auPlating": "APNotApplicable",
                        "collimated": False,
                        "compoundSuppress100Warning": True,
                        "compoundTemplateName": "",
                        "dailyId": daily_id,
                        "final": is_final,
                        "latitude": None,
                        "longitude": None,
                        "methodDispName": "Alloy Plus",
                        "methodFamilyName": 1,
                        "methodId": "alloyPlus",
                        "repeatTestIndex": 1,
                        "repeatTestTotal": 1,
                        "statusId": 0,
                        "testDateTime": now_utc,
                        "testErrorInfo": "No error",
                        "testId": test_id,
                        "testType": "NORMAL",
                        "tiTemplateName": "",
                        "tidName": str(daily_id),
                        "userFactorName": "",
                    },
                    "chemistry": [
                        {"elementName": "Fe", "concentration": 67.4811, "error": 1.3044},
                        {"elementName": "Cr", "concentration": 16.2945, "error": 0.9173},
                        {"elementName": "Ni", "concentration": 11.3956, "error": 1.0371},
                        {"elementName": "Mn", "concentration": 2.6267, "error": 0.5692},
                        {"elementName": "Mo", "concentration": 2.2019, "error": 0.1594},
                    ],
                    "gradeMatch": [
                        {
                            "compGrade": 1,
                            "gradeName": "316",
                            "matchMessage": "aka CF8M",
                            "matchNumber": 0.42,
                            "nominalFactor": 1,
                            "passFailCutOff": 1.0,
                            "passFailNSigma": 2,
                            "passFailShowMatchNumber": True,
                            "testId": test_id,
                            "gradeSpec": [],
                        }
                    ],
                    "images": [],
                    "testId": test_id,
                    "testInfo": {"info": ""},
                }
            },
        }

    @Slot()
    def _sim_normal_test(self):
        """模拟一次完整的正常 Vanta iX 检测流程: 702 -> 200 -> 202 -> 207 -> 206 -> 201"""
        self._sim_test_id += 1
        self._sim_daily_id += 1
        self._on_message_received({"commandId": 403, "id": 702, "params": {}}, 38)
        self._on_message_received({"commandId": 403, "id": 100, "params": {"systemStatus": "Testing", "info": "X-rays on"}}, 76)
        self._on_message_received({"commandId": 403, "id": 200, "params": {}}, 38)
        self._on_message_received({"commandId": 403, "id": 207, "params": {"elapsedTime": 5, "totalTime": 5, "exposureNum": 1, "maxExposures": 1}}, 110)
        pkt_206 = self._build_mock_206_packet(self._sim_test_id, self._sim_daily_id, is_final=True)
        self._on_message_received(pkt_206, len(json.dumps(pkt_206)))
        self._on_message_received({"commandId": 403, "id": 201, "params": {"stopReason": "Test Complete", "stopReasonInt": 0}}, 85)
        self._on_message_received({"commandId": 403, "id": 100, "params": {"systemStatus": "Ready", "info": "X-rays off"}}, 75)

    @Slot()
    def _sim_skipped_test_id(self):
        """模拟 testID 跳过 2 个递增 (例如设备内部完成了 2 次检测但未传出或丢失)"""
        self._sim_test_id += 3
        self._sim_daily_id += 3
        self._on_message_received({"commandId": 403, "id": 200, "params": {}}, 38)
        pkt_206 = self._build_mock_206_packet(self._sim_test_id, self._sim_daily_id, is_final=True)
        self._on_message_received(pkt_206, len(json.dumps(pkt_206)))
        self._on_message_received({"commandId": 403, "id": 201, "params": {"stopReason": "Test Complete", "stopReasonInt": 0}}, 85)

    @Slot()
    def _sim_test_without_206(self):
        """模拟触发并开始检测 (200)，但未产生最终 206 结果便停止 (201) 的漏检场景"""
        self._on_message_received({"commandId": 403, "id": 702, "params": {}}, 38)
        self._on_message_received({"commandId": 403, "id": 200, "params": {}}, 38)
        # 仅发送一条 final=False, testId=-1 的中间消息或完全不发
        inter_pkt = self._build_mock_206_packet(-1, -1, is_final=False)
        self._on_message_received(inter_pkt, len(json.dumps(inter_pkt)))
        self._on_message_received({"commandId": 403, "id": 201, "params": {"stopReason": "User Cancelled / Abort", "stopReasonInt": 2}}, 92)

    def closeEvent(self, event):
        self._stop_listening()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = VantaIXListenerGUI()
    win.show()
    sys.exit(app.exec() if hasattr(app, "exec") else app.exec_())


if __name__ == "__main__":
    main()
