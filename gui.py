"""Tk views for Arduino status, Vanta notifications and chemistry."""

from __future__ import annotations

import base64
import csv
import json
from collections import deque
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from statistics import median

from arduino import ArduinoClient, ArduinoLine, ArduinoReport, BAUD_RATE, parse_arduino_control
from core import ListenerModel, Measurement, parse_device_json, parse_elements, read_device_timing, result_payload
from cycle_tracker import CycleTracker
from device_status import DeviceStatus, STATUS_NOTIFICATION_IDS
from journal import AsyncJournal
from log_format import bounded_line
from monitor_view import CHEMISTRY_SOURCES, PacketMonitor, chemistry_table, scroll_table, show_elements
from transport import DemoClient, ListenerClient


ROOT = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
DEFAULT_IP = "169.254.90.208"
DEFAULT_PORT = 7860
APP_VERSION = "0.2.0-field.1"
ARDUINO_STALE_NS = 4_000_000_000
API_STALE_WITH_CYCLE_NS = 30_000_000_000
MAX_PACKETS_PER_TICK = 25
POLL_BUDGET_SECONDS = 0.008
REFRESH_SECONDS = 0.1
MAX_LOG_BATCH = 40
DEVICE_EVENT_IDS = STATUS_NOTIFICATION_IDS | {206}
CONNECTION_EVENTS = frozenset(("connected", "disconnected", "stopped", "start_failed",
                               "arduino_connected", "arduino_disconnected"))
TEST_ID_STATUS_LABELS = {
    "first": "首条最终结果",
    "consecutive": "连续",
    "gap": "告警 · 跳号",
    "gap_after_reconnect": "断线期间跳号 · 需核对",
    "backward": "回退",
    "repeated_id": "编号重复",
    "duplicate": "重复最终结果",
    "conflict": "同号内容冲突",
    "missing_id": "缺少 testID",
    "invalid_id": "testID 无法比较",
}
CONTROL_LABELS = {
    "WAIT_READY": "等待就绪",
    "READY_HOLD": "就绪保持",
    "TRIGGER": "已发触发",
    "WAIT_READY_RETURN": "等待就绪恢复",
    "DONE": "批次完成",
    "STOPPED": "批次停止",
    "FAULT_STOPPED": "故障停止",
    "FAULT_LOCKED": "故障锁定",
    "FAULT_CLEARED": "故障锁定已清除",
    "NO_FAULT_LOCK": "无故障锁定",
    "DOUBLE_FIRST": "双 START 第一脉冲",
    "DOUBLE_GAP": "双 START 间隔",
    "DOUBLE_SECOND": "双 START 第二脉冲",
    "DOUBLE_DONE": "双 START 完成",
    "START_BLOCKED": "触发条件变化，重新等待",
    "NO_RESPONSE": "板端未见响应",
    "CYCLE_END": "板端周期结束",
    "READY_RETURN_TIMEOUT": "告警 · READY 未恢复",
    "SUMMARY": "板端批次汇总",
}
CYCLE_LABELS = {
    "NORMAL": "正常",
    "EMPTY_SHOT": "接近停测 · 无终态",
    "DOUBLE_START_STOP": "双 START 停测",
    "NO_RESPONSE": "未见设备响应",
    "NO_START": "设备已见触发 · 未见启动",
    "NO_RESULT": "正常停测 · 未收终态",
    "ABNORMAL_STOP": "异常停测",
    "RESULT_ERROR": "终态结果报错",
    "UNKNOWN_STOP": "未知停测",
    "UNSOLICITED": "无对应触发记录",
    "INCONCLUSIVE": "无法判定",
}
CYCLE_ALERTS = frozenset(("NO_RESPONSE", "NO_START", "NO_RESULT", "ABNORMAL_STOP", "RESULT_ERROR",
                         "UNKNOWN_STOP", "INCONCLUSIVE"))
TIMING_FIELDS = (
    ("t_trigger_to_ack_ms", "trigger_ns", "ack_ns"),
    ("t_trigger_to_200_ms", "trigger_ns", "ev200_ns"),
    ("t_200_to_201_ms", "ev200_ns", "ev201_ns"),
)


def stamp(value: datetime | None) -> str:
    return value.isoformat(sep=" ", timespec="milliseconds") if value else ""


def timing_ms(start: int | None, end: int | None) -> float | None:
    return round((end - start) / 1_000_000, 3) if start is not None and end is not None else None


def spectrum_summary(message: dict) -> dict:
    params = message.get("params")
    params = params if isinstance(params, dict) else {}
    spectrum = params.get("spectrum")
    data = spectrum.get("data") if isinstance(spectrum, dict) else params.get("data")
    return {**{k: message[k] for k in ("commandId", "id", "tickCount") if k in message},
            "keys": list(params), "dataLength": len(data) if isinstance(data, (str, list, dict)) else None}


def write_results_csv(path: Path, records: list[Measurement]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["序号", "连接会话", "数据来源", "testId", "每日编号_tidName", "dailyId", "方法",
                         "最终206接收时间", "设备检测时刻", "设备检测耗时_s", "备注"])
        for r in records:
            device_time, device_elapsed = r.device_timing
            writer.writerow([r.seq, r.session, r.endpoint, r.test_id, r.daily_id, r.daily_id_num, r.method,
                             stamp(r.result_at), device_time, device_elapsed, " / ".join(r.issues)])


def write_elements_csv(path: Path, record: Measurement) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["序号", "数据来源", "testId", "方法", "最终206接收时间", "元素", "含量", "误差_1sigma", "单位", "字段来源"])
        for e in record.elements:
            writer.writerow([record.seq, record.endpoint, record.test_id, record.method, stamp(record.result_at),
                             e.name, e.concentration, e.error, e.unit, e.source])


class ListenerApp:
    def __init__(self, window: tk.Tk):
        self.window = window
        self.model = ListenerModel()
        self.device_status = DeviceStatus()
        self.client = None
        self.serial_client = None
        self.events: queue.Queue = queue.Queue()
        self.generation = 0
        self.selected_seq: int | None = None
        self._closing = False
        self._close_summarized = False
        self._destroyed = False
        self._stopping = False
        self._start_thread = None
        self._start_cancel = None
        self._pending_logs = deque(maxlen=300)
        self._pending_serial_logs = deque(maxlen=500)
        self._row_cache = {}
        self._detail_key = None
        self._dirty = False
        self._history_dirty = False
        self._next_refresh = 0.0
        self._poll_id = None
        self._stop_poll_id = None
        self._close_poll_id = None
        self._packet_no = 0
        self._round_packet_no = 0
        self._pending_journal = deque()
        self._live_entry = None
        self._live_displayed = None
        self._arduino_report: ArduinoReport | None = None
        self._arduino_source = ""
        self._arduino_deadline_ns: int | None = None
        self._trigger_progress: tuple[int, int] | None = None
        self._count_start_ns = 0
        self._round_start = datetime.now().astimezone()
        self._round_no = 1
        self._summary_no = 0
        self._round_invalid = 0
        self._round_rx_gaps = 0
        self._round_serial_issues = 0
        self._round_disconnects = 0
        self._round_gap_alerts = 0
        self._poll_errors = 0
        self._api_connected = False
        self._last_packet_ns = None
        self._api_connected_ns = None
        self._last_rx_no = 0
        self._board_summary = None
        self._round_first_id = self._round_last_id = None
        self._timings = {key: [] for key, _, _ in TIMING_FIELDS}
        self._pending_device_logs = deque(maxlen=2000)
        self.tracker = CycleTracker(self._cycle_closed)
        event_queue = self.events
        runtime = ROOT / "runtime"
        self._journal_writer = AsyncJournal(
            runtime / "logs" / f"listener_{self._round_start:%Y%m%d_%H%M%S_%f}.jsonl",
            on_error=lambda text: event_queue.put((None, "journal_error", text)),
            result_dir=runtime / "results",
            on_export=lambda seq, outcome: event_queue.put((None, "result_export", (seq, outcome))),
            summary_dir=runtime / "summaries",
            max_bytes=200_000_000,
            backup_count=50,
        )
        self.host = tk.StringVar(value=DEFAULT_IP)
        self.port = tk.StringVar(value=str(DEFAULT_PORT))
        self.serial_port = tk.StringVar()
        self.serial_command = tk.StringVar()
        self.result_count = tk.IntVar(value=0)
        self.mode = tk.StringVar(value="设备监听")
        self.follow = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="未连接")
        self.serial_status = tk.StringVar(value="未连接")
        self.control_status = tk.StringVar(value="板端批次 · —")
        self.live_caption = tk.StringVar(value="等待 Chemistry")
        self.summary = tk.StringVar(value="最终结果 0 条")
        self.device_report = tk.StringVar(value="设备报告 · 未连接")
        self.test_phase = tk.StringVar(value="检测阶段 · —")
        self.test_id_alert = tk.StringVar()
        self.capture_status = tk.StringVar(value="未收到报文")
        self.capture_health = tk.StringVar(value="无效报文 0 · 接收断号 0 · 本轮断线 0")
        self.alert_count = tk.IntVar(value=0)
        self.cycle_summary = tk.StringVar()
        self._build()
        self._submit_log({"kind": "app_started", "id": None, "appVersion": APP_VERSION,
                          "received_at": stamp(self._round_start)})
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Destroy>", self._on_destroy, add=True)
        self._poll_id = self.window.after(50, self._poll)

    def _build(self):
        w = self.window
        w.title(f"Vanta iX 实时监控 · {APP_VERSION}")
        w.geometry("1260x860")
        w.minsize(980, 700)
        w.configure(bg="#eef2f5")
        style = ttk.Style(w)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background="#eef2f5")
        style.configure("TLabel", background="#eef2f5", foreground="#263b4e")
        style.configure("TButton", padding=(12, 7))
        style.configure("Accent.TButton", background="#126d80", foreground="white")
        style.map("Accent.TButton", background=[("active", "#095567")])
        style.configure("Treeview", rowheight=28, background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), padding=6)
        style.configure("TLabelframe", background="#eef2f5")
        style.configure("TLabelframe.Label", background="#eef2f5", font=("Microsoft YaHei UI", 11, "bold"))

        header = tk.Frame(w, bg="#15374a", padx=24, pady=14)
        header.pack(fill="x")
        tk.Label(header, text="Vanta iX 实时监控", bg="#15374a", fg="white",
                 font=("Microsoft YaHei UI", 20, "bold")).pack(side="left")
        self.reset_button = ttk.Button(header, text="Reset 计数", command=self.reset_result_count)
        self.reset_button.pack(side="right")
        tk.Label(header, textvariable=self.result_count, bg="#15374a", fg="white",
                 font=("Consolas", 22, "bold"), padx=12).pack(side="right")
        tk.Label(header, text="最终结果数", bg="#15374a", fg="#dcecf0").pack(side="right")
        tk.Label(header, textvariable=self.alert_count, bg="#15374a", fg="#ffc7b4",
                 font=("Consolas", 22, "bold"), padx=12).pack(side="right")
        tk.Label(header, text="未见启动或终态", bg="#15374a", fg="#dcecf0").pack(side="right")

        body = ttk.Frame(w, padding=(18, 12))
        body.pack(fill="both", expand=True)
        controls = ttk.Frame(body)
        controls.grid(row=0, column=0, sticky="ew")
        ttk.Label(controls, text="设备 IP").pack(side="left")
        self.host_entry = ttk.Entry(controls, textvariable=self.host, width=17)
        self.host_entry.pack(side="left", padx=(6, 16))
        ttk.Label(controls, text="端口").pack(side="left")
        self.port_entry = ttk.Entry(controls, textvariable=self.port, width=7)
        self.port_entry.pack(side="left", padx=(6, 16))
        ttk.Label(controls, text="Arduino 串口").pack(side="left")
        self.serial_entry = ttk.Entry(controls, textvariable=self.serial_port, width=8)
        self.serial_entry.pack(side="left", padx=(6, 16))
        self.mode_entry = ttk.Combobox(controls, textvariable=self.mode, values=("设备监听", "本地演示"),
                                       width=11, state="readonly")
        self.mode_entry.pack(side="left", padx=(0, 12))
        self.connect_button = ttk.Button(controls, text="开始监听", command=self.connect, style="Accent.TButton")
        self.connect_button.pack(side="left")
        self.disconnect_button = ttk.Button(controls, text="断开", command=self.disconnect, state="disabled")
        self.disconnect_button.pack(side="left", padx=8)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1, minsize=185)
        body.rowconfigure(3, weight=3, minsize=230)
        statuses = ttk.Frame(body)
        statuses.grid(row=1, column=0, sticky="ew", pady=(10, 10))
        statuses.columnconfigure((0, 1), weight=1, uniform="status")
        serial_panel = ttk.Labelframe(statuses, text="Arduino GPIO", padding=(10, 7))
        serial_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        ttk.Label(serial_panel, textvariable=self.serial_status, wraplength=420).pack(anchor="w")
        signals = ttk.Frame(serial_panel)
        signals.pack(fill="x", pady=(8, 0))
        self.gpio_labels = {}
        for name in ("READY", "RAD_ON", "FAULT"):
            label = tk.Label(signals, text=f"{name}  —", bg="#e1e8ed", fg="#526779",
                             font=("Consolas", 12, "bold"), padx=8, pady=5)
            label.pack(side="left", fill="x", expand=True, padx=(0, 5))
            self.gpio_labels[name] = label
        ttk.Label(serial_panel, textvariable=self.control_status).pack(anchor="w", pady=(5, 0))
        api_panel = ttk.Labelframe(statuses, text="Vanta iX API", padding=(10, 7))
        api_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ttk.Label(api_panel, textvariable=self.status, wraplength=420).pack(anchor="w")
        ttk.Label(api_panel, textvariable=self.device_report, foreground="#126d80",
                  wraplength=420).pack(anchor="w", pady=(4, 0))
        ttk.Label(api_panel, textvariable=self.test_phase, wraplength=420).pack(anchor="w", pady=(3, 0))
        self.capture_label = ttk.Label(api_panel, textvariable=self.capture_status, wraplength=420)
        self.capture_label.pack(anchor="w")
        self.health_label = ttk.Label(api_panel, textvariable=self.capture_health, wraplength=420)
        self.health_label.pack(anchor="w")
        self.id_alert_label = ttk.Label(api_panel, textvariable=self.test_id_alert,
                                        foreground="#97361f", wraplength=420)

        views = ttk.Notebook(body, height=205)
        views.grid(row=2, column=0, sticky="nsew")
        live_page = ttk.Frame(views, padding=8)
        views.add(live_page, text="实时 Chemistry")
        ttk.Label(live_page, textvariable=self.live_caption).pack(anchor="w", pady=(0, 6))
        live_frame = ttk.Frame(live_page)
        live_frame.pack(fill="both", expand=True)
        self.live_elements = chemistry_table(live_frame, height=5)
        self.monitor = PacketMonitor(views)
        views.add(self.monitor, text="206 报文")
        views.select(self._build_cycle_page(views))
        device_log_page = ttk.Frame(views, padding=6)
        views.add(device_log_page, text="设备日志")
        self.device_log = self._log_text(device_log_page)
        history_page = ttk.Frame(views, padding=6)
        views.add(history_page, text="最终结果")
        history_page.columnconfigure(0, weight=1)
        history_page.rowconfigure(1, weight=1)
        history_page.rowconfigure(2, weight=2)
        history_header = ttk.Frame(history_page)
        history_header.grid(row=0, column=0, sticky="ew")
        ttk.Label(history_header, textvariable=self.summary).pack(side="left")
        self.clear_button = ttk.Button(history_header, text="清空列表", command=self.clear)
        self.clear_button.pack(side="right")
        ttk.Button(history_header, text="导出结果记录", command=self.export_results).pack(side="right", padx=8)
        ttk.Checkbutton(history_header, text="跟随最新结果", variable=self.follow,
                        command=self._refresh_history).pack(side="right")
        history_frame = ttk.Frame(history_page)
        history_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 10))
        columns = ("seq", "test", "daily", "method", "device_time", "device_elapsed", "final", "notes")
        self.history = ttk.Treeview(history_frame, columns=columns, show="headings", height=4, selectmode="browse")
        for key, title, width in zip(columns,
                                      ("序号", "testId", "dailyId", "检测方法", "设备检测时刻", "设备耗时 / s",
                                       "结果接收时间", "备注"),
                                      (50, 80, 65, 125, 170, 100, 205, 200)):
            self.history.heading(key, text=title)
            self.history.column(key, width=width, minwidth=45, stretch=True)
        scroll_table(history_frame, self.history)
        self.history.bind("<<TreeviewSelect>>", self._select)
        self.history.tag_configure("warning", foreground="#a35b13")

        lower = ttk.Panedwindow(history_page, orient="horizontal")
        lower.grid(row=2, column=0, sticky="nsew")
        elements_frame = ttk.Labelframe(lower, text="最终结果 · 元素含量", padding=8)
        details_frame = ttk.Labelframe(lower, text="所选记录", padding=8)
        lower.add(elements_frame, weight=3)
        lower.add(details_frame, weight=2)
        elements_bar = ttk.Frame(elements_frame)
        elements_bar.pack(fill="x", pady=(0, 6))
        ttk.Label(elements_bar, text="默认单位 %", foreground="#64788a").pack(side="left")
        ttk.Button(elements_bar, text="导出元素表", command=self.export_elements).pack(side="right")
        table = ttk.Frame(elements_frame)
        table.pack(fill="both", expand=True)
        self.elements = chemistry_table(table, height=4)
        self.detail = tk.Text(details_frame, height=4, width=40, bg="white", fg="#263b4e",
                              font=("Microsoft YaHei UI", 10), relief="flat", wrap="word", padx=10, pady=10)
        self.detail.pack(fill="both", expand=True)
        self.detail.configure(state="disabled")
        ttk.Button(details_frame, text="保存所选原始结果 JSON", command=self.export_json).pack(anchor="e", pady=(6, 0))

        self.activity = ttk.Frame(body)
        self.activity.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        self.activity.rowconfigure(0, weight=1)
        self.activity.columnconfigure(0, weight=3, uniform="activity")
        self.activity.columnconfigure(1, weight=2, uniform="activity")
        log_frame = ttk.Labelframe(self.activity, text="状态事件", padding=6)
        log_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.log = self._log_text(log_frame)

        console = ttk.Labelframe(self.activity, text="Arduino 串口", padding=6)
        console.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        console.rowconfigure(0, weight=1)
        console.columnconfigure(0, weight=1)
        console_text = ttk.Frame(console)
        console_text.grid(row=0, column=0, sticky="nsew")
        self.serial_log = self._log_text(console_text)
        command_bar = ttk.Frame(console)
        command_bar.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(command_bar, text="命令").pack(side="left", padx=(0, 8))
        self.send_button = ttk.Button(command_bar, text="发送", command=self.send_arduino_command, state="disabled")
        self.send_button.pack(side="right", padx=(6, 0))
        self.command_entry = ttk.Entry(command_bar, textvariable=self.serial_command, state="disabled", width=14)
        self.command_entry.pack(side="left", fill="x", expand=True)
        self.command_entry.bind("<Return>", self.send_arduino_command)
        ttk.Label(console, text="START [次数] · DOUBLE START [1/0.5] · STOP · CLEAR FAULT").grid(
            row=2, column=0, sticky="w", pady=(4, 0),
        )

    def _build_cycle_page(self, views):
        page = ttk.Frame(views, padding=6)
        views.add(page, text="触发对账")
        self.cycle_count_label = ttk.Label(page, textvariable=self.cycle_summary, wraplength=940)
        self.cycle_count_label.pack(fill="x", pady=(0, 5))
        table = ttk.Frame(page)
        table.pack(fill="both", expand=True)
        columns = ("cycle", "trigger", "id", "outcome", "stop", "start", "stop_ms", "notes")
        self.cycles = ttk.Treeview(table, columns=columns, show="headings", height=5)
        for key, title, width in zip(
            columns,
            ("周期", "触发", "testID", "结果", "停测原因", "触发→200 ms", "200→201 ms", "备注"),
            (45, 60, 55, 170, 130, 95, 95, 245),
        ):
            self.cycles.heading(key, text=title)
            self.cycles.column(key, width=width, minwidth=45)
        self.cycles.tag_configure("warning", background="#fff0e8", foreground="#97361f")
        scroll_table(table, self.cycles)
        return page

    @staticmethod
    def _log_text(parent) -> tk.Text:
        widget = tk.Text(parent, width=36, height=10, bg="#15374a", fg="#dcecf0", relief="flat",
                         font=("Consolas", 10), wrap="none", padx=8, pady=6, state="disabled")
        scroll_table(parent, widget)
        return widget

    def _busy(self, value: bool):
        self.connect_button.configure(state="disabled" if value else "normal")
        self.disconnect_button.configure(state="normal" if value else "disabled")
        self.clear_button.configure(state="disabled" if value else "normal")
        for entry in (self.host_entry, self.port_entry, self.serial_entry):
            entry.configure(state="disabled" if value else "normal")
        self.mode_entry.configure(state="disabled" if value else "readonly")

    def connect(self):
        if self.client is not None or self.serial_client is not None or self._stopping or self._closing:
            return
        self.generation += 1
        generation = self.generation
        event_queue = self.events
        def sink(kind, payload):
            if kind in CONNECTION_EVENTS:
                payload = (payload, datetime.now().astimezone(), time.perf_counter_ns())
            event_queue.put((generation, kind, payload))
        try:
            demo = self.mode.get() == "本地演示"
            client = DemoClient(sink) if demo else ListenerClient(self.host.get(), int(self.port.get()), sink)
            port = self.serial_port.get().strip()
            serial_client = ArduinoClient(port, sink) if port and not demo else None
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("无法开始监听", str(exc), parent=self.window)
            return
        self.client = client
        self.serial_client = serial_client
        self._busy(True)
        self.status.set("正在连接…" if not demo else "正在启动本地演示…")
        self._clear_arduino("正在连接…" if serial_client or demo else "未配置串口")
        if serial_client is not None:
            serial_client.start()
        # Loading the network library can trigger slow disk/virus-scanner work.
        # It must not block the button callback either.
        cancelled = threading.Event()
        self._start_cancel = cancelled
        def start_worker():
            try:
                if not cancelled.is_set():
                    client.start()
                if cancelled.is_set():
                    client.stop()
            except Exception as exc:
                sink("start_failed", str(exc))
        self._start_thread = threading.Thread(target=start_worker, daemon=True)
        self._start_thread.start()

    def disconnect(self):
        if self._stopping or (self.client is None and self.serial_client is None):
            return
        self._stopping = True
        if self._start_cancel is not None:
            self._start_cancel.set()
        self.disconnect_button.configure(state="disabled")
        self._enable_commands(False)
        self.status.set("正在断开…")
        # stop() may close a network socket. Keep this work out of the GUI loop.
        clients = (self.serial_client, self.client)
        generation = self.generation
        event_queue = self.events
        def worker():
            for client in clients:
                if client is not None:
                    client.stop()
            event_queue.put((generation, "stopped", ("手动断开", datetime.now().astimezone(), time.perf_counter_ns())))
        threading.Thread(target=worker, daemon=True).start()

    def _enable_commands(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.command_entry.configure(state=state)
        self.send_button.configure(state=state)

    def send_arduino_command(self, _event=None):
        command = self.serial_command.get()
        client = self.serial_client
        if client is None or self._stopping or self._closing or not command.strip():
            return "break"
        if command.strip().upper().split()[:2] == ["DOUBLE", "START"]:
            if not messagebox.askyesno("确认双 START 台架测试",
                                       "第二个脉冲可能停止当前检测，也可能启动新检测。确认发送？",
                                       parent=self.window, default="no"):
                return "break"
        try:
            client.send_command(command)
        except (ValueError, OSError, RuntimeError) as exc:
            self.events.put((self.generation, "arduino_line", ArduinoLine(
                "ERR", str(exc), datetime.now().astimezone(),
            )))
        else:
            self.serial_command.set("")
        return "break"

    def reset_result_count(self) -> None:
        if self._closing:
            return
        self.events.put((None, "counter_reset", (datetime.now().astimezone(), time.perf_counter_ns())))

    def _reset_result_count(self, at: datetime, ns: int) -> None:
        self._reset_audit("Reset 计数", at, ns)
        self._count_start_ns = ns
        previous = self.result_count.get()
        previous_packets = self._round_packet_no
        self.result_count.set(0)
        self._round_packet_no = 0
        self.model.reset_test_id_sequence()
        self.monitor.clear()
        self._show_test_id_alert("")
        self._submit_log({
            "kind": "counter_reset", "id": None, "source": "app",
            "received_at": stamp(at), "received_ns": ns,
            "previousCount": previous, "resultCount": 0,
            "previousPacketCount": previous_packets, "roundPacketNo": 0,
        })
        self._pending_logs.append(f"{stamp(at)}  最终结果计数和 206 序号已清零\n")

    def _show_test_id_alert(self, message: str) -> None:
        self.test_id_alert.set(bounded_line(message)[:200])
        if message:
            self.id_alert_label.pack(anchor="w", pady=(4, 0))
        else:
            self.id_alert_label.pack_forget()

    def _submit_log(self, entry: dict) -> None:
        entry.setdefault("roundNo", self._round_no)
        if self._pending_journal or not self._journal_writer.submit(entry, report_full=False):
            self._pending_journal.append(entry)

    def _cycle_closed(self, cycle) -> None:
        entry = cycle.to_entry()
        entry.update(kind="cycle", id=None, received_at=stamp(datetime.now().astimezone()),
                     received_ns=cycle.closed_ns, session=self.model.session)
        self._submit_log(entry)
        for key, values in self._timings.items():
            value = entry.get(key)
            if value is not None:
                values.append(value)
        outcome = entry["outcome"]
        trigger = "API" if entry["triggerSource"] == "api" else cycle.trigger_no
        display = (cycle.no, trigger, cycle.test_id, CYCLE_LABELS.get(outcome, outcome), cycle.stop_reason,
                   *(entry.get(k) for k, _, _ in TIMING_FIELDS[1:]), " / ".join(cycle.notes))
        self.cycles.insert("", "end", values=tuple("—" if v is None else bounded_line(v) for v in display),
                           tags=("warning",) if outcome in CYCLE_ALERTS else ())
        if len(rows := self.cycles.get_children()) > 1000:
            self.cycles.delete(rows[0])
        self._dirty = True

    def _write_round_summary(self, reason: str, at: datetime, ns: int) -> None:
        self._summary_no += 1
        counts = {key: self.tracker.counts.get(key, 0) for key in CYCLE_LABELS}
        self._submit_log({
            "kind": "round_summary", "id": None, "source": "app",
            "summaryNo": self._summary_no, "reason": reason, "start": stamp(self._round_start),
            "end": stamp(at), "received_at": stamp(at), "received_ns": ns,
            "appVersion": APP_VERSION, "triggers": self.tracker.triggers,
            "apiTriggers": self.tracker.api_triggers, **counts, "TESTID_GAP": self._round_gap_alerts,
            "openCycles": len(self.tracker.open_cycles), "finalResults": self.result_count.get(),
            "disconnects": self._round_disconnects, "invalidPackets": self._round_invalid,
            "rxSequenceGaps": self._round_rx_gaps, "serialIssues": self._round_serial_issues,
            "internalErrors": self._poll_errors,
            "board": self._board_summary,
            "testIdRange": {"first": self._round_first_id, "last": self._round_last_id},
            "evidenceComplete": not any((self._round_disconnects, self._round_invalid, self._round_rx_gaps,
                                         self._round_serial_issues, self._poll_errors,
                                         counts["INCONCLUSIVE"], self.tracker.open_cycles)),
            "timing_ms": {key.removeprefix("t_").removesuffix("_ms"):
                          {"min": min(values), "p50": median(values), "max": max(values)}
                          for key, values in self._timings.items() if values},
        })

    def _reset_audit(self, reason: str, at: datetime, ns: int) -> None:
        # Finish open cycles in the old round before the tracker clears its counts.
        self.tracker.finish_open(ns, reason)
        self._write_round_summary(reason, at, ns)
        self.tracker.reset(ns)
        self.cycles.delete(*self.cycles.get_children())
        self._round_no += 1
        self._round_start = at
        self._round_invalid = self._round_rx_gaps = self._round_disconnects = self._round_gap_alerts = 0
        self._round_serial_issues = 0
        self._round_first_id = self._round_last_id = self._board_summary = None
        for samples in self._timings.values():
            samples.clear()
        self._dirty = True

    def _receive_arduino_line(self, line: ArduinoLine) -> bool:
        text = line.text.replace("\r", "\\r").replace("\n", "\\n").replace("\0", "\\0")
        timestamp = line.at.strftime("%H:%M:%S.%f")[:-3]
        self._pending_serial_logs.append(f"{timestamp}  {line.direction}  {text}\n")
        if line.report is not None:
            self._receive_arduino(line.report)
            return True
        ns = line.received_ns or time.perf_counter_ns()
        source = "demo" if self.mode.get() == "本地演示" else "arduino"
        entry = {"kind": "arduino_serial", "id": None, "source": source, "port": self._arduino_source,
                 "received_at": stamp(line.at), "received_ns": ns, "direction": line.direction, "text": line.text}
        control = parse_arduino_control(line.text) if line.direction == "RX" else None
        if control is not None:
            entry.update(kind="arduino_control", event=control.event,
                         sent=control.sent, total=control.total, error=control.error, extra=control.extra)
            if control.sent is not None and control.total is not None:
                self._trigger_progress = (control.sent, control.total)
            detail = f"命令反馈 {control.error}" if control.error else CONTROL_LABELS.get(control.event, control.event)
            if self._trigger_progress is not None:
                sent, total = self._trigger_progress
                detail += f" · 已发 {sent} / {total}"
            if control.event == "SUMMARY":
                self._board_summary = {"sent": control.sent, "total": control.total, **control.extra}
                detail += f" · 无响应 {control.extra.get('no_response', '—')}"
                detail += f" · 出束 {control.extra.get('rad_on_cycles', '—')}"
                entry["pcCycleCounts"] = dict(self.tracker.counts)
                entry["pcOpenCycles"] = len(self.tracker.open_cycles)
                entry["pcPulses"] = self.tracker.triggers
            self.control_status.set(f"板端批次 · {detail}")
            self._pending_logs.append(f"{timestamp}  Arduino {self._arduino_source}  {detail}\n")
        self._submit_log(entry)
        if control is not None and ns >= self._count_start_ns:
            self._track_control(control, ns)
        elif control is None and ns >= self._count_start_ns and line.direction == "RX" and (
            "CTRL " in line.text or "t_ms=" in line.text
        ):
            self._serial_issue(ns, "板端状态或控制行格式无效")
        return True

    def _track_control(self, control, ns: int) -> None:
        event, sent = control.event, control.sent
        if event == "TRIGGER" and sent is not None:
            self.tracker.on_trigger(sent, ns)
        elif event == "DOUBLE_FIRST":
            self.tracker.on_double_first(ns)
        elif event == "DOUBLE_SECOND":
            self.tracker.on_double_second(ns)
        elif event == "NO_RESPONSE" and sent is not None:
            self.tracker.on_board_no_response(sent, ns)
        elif event == "CYCLE_END" and sent is not None:
            self.tracker.on_board_cycle_end(sent, ns, rad_on=control.extra.get("rad_on") == 1)
        elif event == "READY_RETURN_TIMEOUT" and sent is not None:
            self.tracker.on_board_ready_timeout(sent, ns)
        elif event == "FAULT_STOPPED":
            self.tracker.on_invalid(ns, "板端因 FAULT 停止")

    def _serial_issue(self, ns: int, note: str) -> None:
        self._round_serial_issues += 1
        self.tracker.on_invalid(ns, note)

    def _clear_arduino(self, status: str) -> None:
        self._arduino_report = None
        self._arduino_deadline_ns = None
        self.serial_status.set(status)

    def _receive_arduino(self, report: ArduinoReport) -> None:
        previous = self._arduino_report
        self._arduino_report = report
        self._arduino_deadline_ns = report.received_ns + ARDUINO_STALE_NS
        timestamp = report.received_at.strftime("%H:%M:%S.%f")[:-3]
        details = [self._arduino_source, f"{BAUD_RATE} 波特", f"接收 {timestamp}"]
        if report.dropped:
            details.append(f"板端丢失 {report.dropped} 条")
        if not report.matrix:
            details.append("矩阵未启动")
        self.serial_status.set(" · ".join(details))
        if previous and (report.dropped > previous.dropped
                         or report.uptime_ms < previous.uptime_ms
                         or ((report.sequence - previous.sequence) & 0xFFFFFFFF) > 1):
            self._serial_issue(report.received_ns, "Arduino 状态记录不连续")
        self.tracker.on_gpio(report.ready, report.rad_on, report.received_ns)
        if report.event == "STATE" and previous is not None and (
            report.sequence, report.ready, report.rad_on, report.fault, report.dropped, report.matrix
        ) == (
            previous.sequence, previous.ready, previous.rad_on, previous.fault, previous.dropped, previous.matrix
        ):
            return
        fault = "—" if report.fault is None else str(int(report.fault))
        line = (f"{timestamp}  Arduino {self._arduino_source}  {report.event}  "
                f"READY={int(report.ready)} RAD_ON={int(report.rad_on)} FAULT={fault}  "
                f"seq={report.sequence} t_ms={report.uptime_ms} dropped={report.dropped}")
        self._pending_logs.append(bounded_line(line) + "\n")
        self._submit_log({
            "kind": "arduino_status", "id": None,
            "source": "demo" if self.mode.get() == "本地演示" else "arduino",
            "port": self._arduino_source, "received_at": stamp(report.received_at), "received_ns": report.received_ns,
            "event": report.event, "t_ms": report.uptime_ms, "seq": report.sequence,
            "READY": report.ready, "RAD_ON": report.rad_on, "FAULT": report.fault,
            "dropped": report.dropped, "matrix": report.matrix,
        })

    def _receive_packet(self, packet) -> bool:
        in_round = packet.received_ns >= self._count_start_ns
        self._last_packet_ns = packet.received_ns
        entry = {
            "received_at": stamp(packet.received_at), "received_ns": packet.received_ns,
            "session": self.model.session, "endpoint": self.model.endpoint,
            "source": "demo" if self.mode.get() == "本地演示" else "device",
        }
        if packet.rx_no:
            entry["rxNo"] = packet.rx_no
            if packet.rx_no != self._last_rx_no + 1:
                entry["previousRxNo"] = self._last_rx_no
                self._round_rx_gaps += int(in_round)
                self.tracker.on_invalid(packet.received_ns, "WebSocket 接收序号不连续")
            self._last_rx_no = packet.rx_no
        try:
            raw = packet.raw.decode("utf-8") if isinstance(packet.raw, bytes) else packet.raw
            message, nonfinite = parse_device_json(raw)
            if not isinstance(message, dict):
                raise ValueError("JSON 顶层不是对象")
        except (ValueError, TypeError, RecursionError) as exc:
            self._record_invalid_packet(packet, entry, exc, in_round)
            return True
        event = message.get("id")
        entry.update(id=event, message=message)
        if nonfinite:
            entry["nonFinite"] = True
            if event != 204:
                entry["raw"] = raw
        if message.get("commandId") != 403 or type(event) is not int or event not in DEVICE_EVENT_IDS:
            if event == 204 and message.get("commandId") == 403:
                entry["message"] = spectrum_summary(message)
            self._submit_log({**entry, "kind": "api_other"})
            if in_round and event == 204 and message.get("commandId") == 403:
                self.tracker.on_api(event, {}, packet.received_ns)
            return True

        entry["kind"] = "api_status"
        try:
            notice, device_time, params = self._process_packet(packet, entry, in_round, nonfinite)
        except Exception as exc:
            entry["processingError"] = bounded_line(str(exc))[:500]
            raise
        finally:
            self._submit_log(entry)
        if in_round:
            if notice is not None:
                self.tracker.on_result(notice, packet.received_ns, result_key=device_time or None)
            else:
                self.tracker.on_api(event, params, packet.received_ns)
        return True

    def _process_packet(self, packet, entry: dict, in_round: bool, nonfinite: bool):
        event, message = entry["id"], entry["message"]
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        device_time = ""
        notice = self.model.process(message, packet.received_ns, packet.received_at,
                                    compare_test_ids=in_round, nonfinite=nonfinite)
        timestamp = packet.received_at.strftime("%H:%M:%S.%f")[:-3]
        line = f"{timestamp}  {event}"
        if notice is not None:
            self._packet_no += 1
            if in_round:
                self._round_packet_no += 1
            device_time, device_elapsed = read_device_timing(result_payload(message.get("params")))
            counted = in_round and notice.is_final is True and notice.id_status not in ("duplicate", "conflict")
            if counted:
                self.result_count.set(self.result_count.get() + 1)
                if notice.test_id:
                    self._round_first_id = self._round_first_id or notice.test_id
                    self._round_last_id = notice.test_id
            entry.update(
                kind="api_result",
                packetNo=self._packet_no,
                roundPacketNo=self._round_packet_no if in_round else None,
                testID=notice.test_id or None,
                isFinal=notice.is_final,
                deviceTestTime=device_time or None,
                deviceElapsedSeconds=device_elapsed,
                counted=counted,
                resultCount=self.result_count.get(),
            )
            if notice.result_error:
                entry["resultError"] = notice.result_error
            test_id = notice.test_id or "—"
            if len(test_id) > 64:
                test_id = test_id[:64] + "…"
            line += f"  testID={test_id}  isFinal={json.dumps(notice.is_final)}"
            check = ""
            if notice.id_status is not None:
                entry["testIDStatus"] = notice.id_status
                check = TEST_ID_STATUS_LABELS[notice.id_status]
            if notice.id_delta is not None:
                entry["testIDDelta"] = notice.id_delta
                check += f"（{notice.id_delta:+d}）"
            if notice.id_status in ("gap", "gap_after_reconnect") and notice.id_delta is not None:
                previous_id = str(int(notice.test_id) - notice.id_delta)
                skipped = notice.id_delta - 1
                entry["testIDGap"] = {"previous": previous_id, "skipped": skipped}
                self._round_gap_alerts += 1
                context = "断线期间" if notice.id_status == "gap_after_reconnect" else ""
                warning = f"待核对 · {context}testID 跳号 {previous_id} → {test_id} · {skipped} 个编号"
                self._show_test_id_alert(warning)
                line += f"  {warning}"
            elif check:
                line += f"  {check}"
            if notice.daily_id_num is not None:
                entry.update(dailyId=notice.daily_id_num, dailyIdStatus=notice.daily_id_status,
                             dailyIdDelta=notice.daily_id_delta)
            if notice.daily_id_status == "gap":
                line += f"  每日编号跳号（+{notice.daily_id_delta}）"
            if in_round:
                self.monitor.add(entry, check)
            self._live_entry = entry
            self._history_dirty = self._history_dirty or notice.is_final is True
        else:
            detail = self.device_status.notification(event, params)
            entry["description"] = detail
            line += f"  {detail}"
            if event == 701 and isinstance(params, dict) and isinstance(params.get("messages"), list):
                for item in params["messages"][-2000:]:
                    self._pending_device_logs.append(f"{timestamp}  {bounded_line(str(item))}\n")
        self._pending_logs.append(bounded_line(line) + "\n")
        return notice, device_time, params

    def _record_invalid_packet(self, packet, entry: dict, exc: Exception, in_round: bool) -> None:
        self._round_invalid += int(in_round)
        raw = packet.raw
        entry.update(kind="api_invalid", id=None, error=bounded_line(str(exc))[:500],
                     rawLength=len(raw), truncated=len(raw) > 4_000_000)
        if isinstance(raw, bytes):
            try:
                entry["raw"] = raw.decode("utf-8")[:4_000_000]
            except UnicodeDecodeError:
                entry["rawBase64"] = base64.b64encode(raw[:4_000_000]).decode("ascii")
        else:
            entry["raw"] = raw[:4_000_000]
        self._submit_log(entry)
        self._pending_logs.append(f"无效报文 · {entry['error']}\n")
        if in_round:
            self.tracker.on_invalid(packet.received_ns, "收到无法解析的 WebSocket 报文")

    def _poll(self):
        if self._poll_id is not None:
            self.window.after_cancel(self._poll_id)
            self._poll_id = None
        try:
            self._poll_body()
        except Exception as exc:
            self._poll_errors += 1
            ns = time.perf_counter_ns()
            self.status.set(f"内部错误 {self._poll_errors} 次 · {bounded_line(str(exc))[:180]}")
            self._submit_log({"kind": "internal_error", "id": None, "received_ns": ns,
                              "received_at": stamp(datetime.now().astimezone()),
                              "traceback": traceback.format_exc()})
            self.tracker.on_invalid(ns, "监听程序内部错误")
        finally:
            if not self._destroyed:
                self._poll_id = self.window.after(30, self._poll)

    def _poll_body(self):
        deadline = time.perf_counter() + POLL_BUDGET_SECONDS
        changed = False
        for index in range(MAX_PACKETS_PER_TICK):
            if index and time.perf_counter() >= deadline:
                break
            while self._pending_journal:
                if not self._journal_writer.submit(self._pending_journal[0], report_full=False):
                    break
                self._pending_journal.popleft()
            if self._pending_journal:
                break
            try:
                generation, kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "journal_error":
                self.status.set(f"日志文件写入失败：{payload}")
                self.tracker.on_invalid(time.perf_counter_ns(), "日志写入失败")
                continue
            if kind == "result_export":
                self.monitor.set_export(*payload)
                changed = True
                continue
            if kind == "counter_reset":
                self._reset_result_count(*payload)
                continue
            if generation != self.generation:
                continue
            if kind in CONNECTION_EVENTS:
                if isinstance(payload, tuple):
                    payload, at, ns = payload
                else:
                    at, ns = datetime.now().astimezone(), time.perf_counter_ns()
                target = "arduino" if kind.startswith("arduino_") else "api"
                self._submit_log({"kind": "connection", "id": None, "target": target,
                                  "event": kind.removeprefix("arduino_"), "detail": str(payload),
                                  "received_at": stamp(at), "received_ns": ns,
                                  "session": self.model.session + int(kind == "connected")})
            if kind == "packet":
                changed = self._receive_packet(payload) or changed
            elif kind == "connected":
                self.model.begin_session(str(payload))
                self.tracker.on_connect(ns, endpoint=str(payload))
                self._api_connected = True
                self._api_connected_ns = ns
                self._last_packet_ns = None
                self._last_rx_no = 0
                self.device_status.connection_changed(True)
                self._live_entry = None
                self.status.set(f"已连接 · {payload}" + (" · 演示数据" if self.mode.get() == "本地演示" else " · 监听者"))
                changed = True
            elif kind in ("disconnected", "stopped"):
                lost = self._api_connected and not (self._closing or self._stopping)
                self._api_connected = False
                self._api_connected_ns = None
                self.device_status.connection_changed(False)
                self.tracker.on_disconnect(ns)
                self._live_entry = None
                self.status.set(f"已断开 · {payload}")
                changed = True
                if lost:
                    self._round_disconnects += 1
                    self._write_round_summary("API 意外断开", at, ns)
                if kind == "stopped":
                    self._clear_arduino("未连接")
                    self._write_round_summary("手动断开", at, ns)
                    self._finish_stop()
            elif kind == "start_failed":
                if self._stopping:
                    self._finish_stop()
                else:
                    self.status.set(f"无法开始监听：{payload}")
                    self.client = None
                    self._busy(self.serial_client is not None)
            elif kind == "arduino_connected":
                self.tracker.on_connect(ns, "arduino")
                self._arduino_source = str(payload)
                self._trigger_progress = None
                self.control_status.set("板端批次 · 等待控制回报")
                self._clear_arduino(f"{payload} · {BAUD_RATE} 波特 · 等待状态")
                self._arduino_deadline_ns = ns + ARDUINO_STALE_NS
                self._enable_commands(self.serial_client is not None and not self._stopping and not self._closing)
                changed = True
            elif kind == "arduino_disconnected":
                self.tracker.on_disconnect(ns, "arduino")
                self._clear_arduino(str(payload))
                self._trigger_progress = None
                self.control_status.set("板端批次 · —")
                self._enable_commands(False)
                changed = True
            elif kind == "arduino_line":
                changed = self._receive_arduino_line(payload) or changed
            elif kind == "arduino_report":
                self._receive_arduino(payload)
                changed = True
            elif kind == "arduino_status":
                self.serial_status.set(str(payload))
            else:
                self.status.set(str(payload))
        now_ns = time.perf_counter_ns()
        if self.events.empty() and not self._pending_journal and (
            self._arduino_deadline_ns is not None and now_ns >= self._arduino_deadline_ns
        ):
            detail = "状态超时" if self._arduino_report is not None else "等待 GPIO 报告"
            self._serial_issue(now_ns, "Arduino 状态报告超时")
            self._clear_arduino(f"{self._arduino_source} · 串口已打开 · {detail}")
            changed = True
        if self.events.empty() and not self._pending_journal:
            self.tracker.tick(now_ns)
        self._dirty = self._dirty or changed
        if time.perf_counter() >= self._next_refresh:
            self._refresh_audit(now_ns)
            if self._dirty:
                self.refresh()
            self._dirty = False
            self._next_refresh = time.perf_counter() + REFRESH_SECONDS
        self._flush_log(self.log, self._pending_logs)
        self._flush_log(self.serial_log, self._pending_serial_logs)
        self._flush_log(self.device_log, self._pending_device_logs)

    def _refresh_audit(self, now_ns: int) -> None:
        counts = self.tracker.counts
        missing = sum(counts.get(key, 0) for key in ("NO_RESPONSE", "NO_START", "NO_RESULT"))
        self.alert_count.set(missing)
        self.cycle_summary.set(" · ".join([
            f"板端脉冲 {self.tracker.triggers}", f"API 独立触发 {self.tracker.api_triggers}",
            *(f"{label} {counts.get(key, 0)}" for key, label in CYCLE_LABELS.items()),
            f"跳号记录 {self._round_gap_alerts}", f"待结案 {len(self.tracker.open_cycles)}",
        ]))
        self.cycle_count_label.configure(foreground="#97361f" if self.alert_count.get() else "#263b4e")
        reference = self._last_packet_ns or self._api_connected_ns
        lag = timing_ms(reference, now_ns)
        stalled = bool(self._api_connected and self.tracker.open_cycles and reference is not None
                       and now_ns - reference >= API_STALE_WITH_CYCLE_NS)
        if self._api_connected and self._last_packet_ns is not None:
            self.capture_status.set(f"最后报文 {lag / 1000:.1f} s 前" + (" · 尚有周期待结案" if stalled else ""))
        elif stalled:
            self.capture_status.set(f"{lag / 1000:.1f} s 未收到首条报文 · 尚有周期待结案")
        else:
            self.capture_status.set("等待报文" if self._api_connected else "API 未连接")
        self.capture_label.configure(foreground="#97361f" if stalled else "#263b4e")
        writer = self._journal_writer
        incomplete = any((self._round_invalid, self._round_rx_gaps, self._round_disconnects,
                          self._round_serial_issues, self._poll_errors, writer.dropped_count, writer.failure_count))
        self.capture_health.set(f"无效报文 {self._round_invalid} · 接收断号 {self._round_rx_gaps}"
                                f" · 断线 {self._round_disconnects} · 串口异常 {self._round_serial_issues}"
                                f" · 内部错误 {self._poll_errors}"
                                f" · 日志失败/丢弃 {writer.failure_count + writer.dropped_count}"
                                f" · 导出异常 {writer.export_issue_count}")
        self.health_label.configure(foreground="#97361f" if incomplete or writer.export_issue_count else "#263b4e")

    def _finish_stop(self):
        if self._stop_poll_id is not None:
            self.window.after_cancel(self._stop_poll_id)
            self._stop_poll_id = None
        if self._closing:
            return
        if self._client_running():
            self.status.set("正在等待连接线程退出…")
            self._stop_poll_id = self.window.after(100, self._finish_stop)
            return
        self.client = None
        self.serial_client = None
        self._stopping = False
        self._enable_commands(False)
        self._busy(False)

    def _client_running(self) -> bool:
        return ((self._start_thread is not None and self._start_thread.is_alive())
                or any(client.is_alive for client in (self.client, self.serial_client) if client is not None))

    @staticmethod
    def _flush_log(widget: tk.Text, pending: deque) -> None:
        if not pending:
            return
        lines = [pending.popleft() for _ in range(min(MAX_LOG_BATCH, len(pending)))]
        widget.configure(state="normal")
        widget.insert("end", "".join(lines))
        count = int(widget.index("end-1c").split(".")[0]) - 1
        if count > pending.maxlen:
            widget.delete("1.0", f"{count - pending.maxlen + 1}.0")
        widget.see("end")
        widget.configure(state="disabled")

    def refresh(self):
        self.monitor.refresh()
        self.device_report.set(f"设备报告 · {self.device_status.system}")
        self.test_phase.set(f"检测阶段 · {self.device_status.phase}")
        report = self._arduino_report
        signals = (report.ready, report.rad_on, report.fault) if report else (None, None, None)
        for (name, label), value in zip(self.gpio_labels.items(), signals):
            bit = "—" if value is None else str(int(value))
            background = "#e1e8ed"
            foreground = "#526779"
            if value:
                background, foreground = ("#d9f1e5", "#175c3b") if name == "READY" else ("#ffe8dd", "#923318")
            label.configure(text=f"{name}  {bit}", bg=background, fg=foreground)
        if self._live_entry is not self._live_displayed:
            self._live_displayed = self._live_entry
            self._show_live_chemistry()
        self.summary.set(f"最终结果 {len(self.model.records)} 条 · 中间结果 {self.model.intermediate_count} 条"
                         f" · 重复或冲突 {self.model.duplicate_count} 条")
        if self._history_dirty:
            self._history_dirty = False
            self._refresh_history()

    def _show_live_chemistry(self) -> None:
        entry = self._live_entry
        if entry is None:
            show_elements(self.live_elements, [])
            self.live_caption.set("等待 Chemistry")
            return
        result = result_payload(entry["message"].get("params")) or {}
        source = next((key for key in CHEMISTRY_SOURCES if isinstance(result.get(key), list) and result[key]), "chemistry")
        elements, _ = parse_elements(result, source=source)
        show_elements(self.live_elements, elements)
        final = entry["isFinal"]
        kind = {True: "最终结果", False: "中间结果", None: "结果类型未提供"}[final]
        test_id = bounded_line((entry["testID"] or "—")[:64])
        detail = f"{source} · {len(elements)} 个元素" if elements else "本条报文没有元素数据"
        self.live_caption.set(f"{kind} · testID={test_id} · {detail} · 接收 {entry['received_at']}")

    def _refresh_history(self):
        current = set(self.history.get_children())
        wanted = {str(r.seq) for r in self.model.records}
        for iid in current - wanted:
            self.history.delete(iid)
            self._row_cache.pop(iid, None)
        for record in self.model.records:
            device_time, device_elapsed = record.device_timing
            values = (record.seq, bounded_line(record.test_id) or "—", record.daily_id_num or "—",
                      bounded_line(record.method) or "—",
                      bounded_line(device_time) or "—",
                      str(device_elapsed) if device_elapsed is not None else "—", stamp(record.result_at),
                      bounded_line(record.issues[0]) if record.issues else "—")
            tags = ("warning",) if record.issues else ()
            iid = str(record.seq)
            if iid not in current:
                self.history.insert("", "end", iid=iid, values=values, tags=tags)
            elif self._row_cache.get(iid) != (values, tags):
                self.history.item(iid, values=values, tags=tags)
            self._row_cache[iid] = (values, tags)
        if self.model.records and (self.follow.get() or not self.history.selection()):
            iid = str(self.model.records[-1].seq)
            if self.history.selection() != (iid,):
                self.history.selection_set(iid)
                self.history.see(iid)
            self.selected_seq = int(iid)
        self._show_record()

    def _select(self, _event=None):
        selected = self.history.selection()
        if selected:
            self.selected_seq = int(selected[0])
        else:
            self.selected_seq = None
        self._show_record()

    def selected_record(self) -> Measurement | None:
        return next((r for r in self.model.records if r.seq == self.selected_seq), None)

    def _show_record(self):
        r = self.selected_record()
        key = None if r is None else (r.seq, tuple(r.issues))
        if key == self._detail_key:
            return
        self._detail_key = key
        device_time, device_elapsed = r.device_timing if r else ("", None)
        elapsed_text = str(device_elapsed) if device_elapsed is not None else "—"
        show_elements(self.elements, r.elements if r else [])
        detail = "选中一条记录，查看结果。"
        if r:
            detail = (f"本地序号：{r.seq}\n连接会话：{r.session}\n数据来源：{bounded_line(r.endpoint)}\n"
                      f"testId：{bounded_line(r.test_id) or '未声明'}\n"
                      f"每日编号 dailyId：{r.daily_id_num or '未声明'} · tidName：{bounded_line(r.daily_id) or '未声明'}\n"
                      f"检测方法：{bounded_line(r.method) or '未声明'}\n"
                      f"设备检测时刻：{bounded_line(device_time) or '—'}\n"
                      f"设备检测耗时 / s：{elapsed_text}\n"
                      f"结果接收时间：{stamp(r.result_at)}\n备注：{bounded_line(' / '.join(r.issues)) or '无'}")
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", detail)
        self.detail.configure(state="disabled")

    def clear(self):
        if self.client is not None or self.serial_client is not None:
            return
        at, ns = datetime.now().astimezone(), time.perf_counter_ns()
        self._reset_result_count(at, ns)
        self.model.records.clear()
        self.model.intermediate_count = self.model.duplicate_count = 0
        self._submit_log({"kind": "ui_clear", "id": None, "source": "app",
                          "received_at": stamp(at), "received_ns": ns, "session": self.model.session})
        self.selected_seq = None
        self._live_entry = None
        self._history_dirty = True
        self.monitor.clear()
        self.refresh()
        self.status.set("已清空界面记录。日志文件仍保存在 runtime。")

    def _save(self, title, extension, filename, writer):
        path = filedialog.asksaveasfilename(parent=self.window, title=title, defaultextension=extension,
                                           initialfile=filename, filetypes=[(extension[1:].upper() + " 文件", "*" + extension)])
        if path:
            try:
                writer(Path(path))
            except (OSError, ValueError) as exc:
                messagebox.showerror("保存失败", str(exc), parent=self.window)
            else:
                self.status.set(f"已保存：{path}")

    def export_results(self):
        if not self.model.records:
            messagebox.showinfo("导出结果记录", "当前没有记录。", parent=self.window)
            return
        self._save("导出结果记录", ".csv", "vanta_results.csv", lambda path: write_results_csv(path, self.model.records))

    def export_elements(self):
        r = self.selected_record()
        if r is None:
            messagebox.showinfo("导出元素表", "请先选择一条最终结果。", parent=self.window)
            return
        self._save("导出元素表", ".csv", f"vanta_elements_{r.seq}.csv", lambda path: write_elements_csv(path, r))

    def export_json(self):
        r = self.selected_record()
        if r is None:
            messagebox.showinfo("保存原始结果", "请先选择一条最终结果。", parent=self.window)
            return
        self._save("保存所选原始结果", ".json", f"vanta_result_{r.seq}.json",
                   lambda path: path.write_text(json.dumps(r.raw_result, ensure_ascii=False, indent=2), encoding="utf-8"))

    def close(self):
        if self._closing:
            return
        self._closing = True
        if self._start_cancel is not None:
            self._start_cancel.set()
        self._busy(True)
        self.disconnect_button.configure(state="disabled")
        self._enable_commands(False)
        self.reset_button.configure(state="disabled")
        for client in (self.serial_client, self.client):
            if client is not None:
                threading.Thread(target=client.stop, daemon=True).start()
        self.status.set("正在保存日志和结果…")
        self._finish_close()

    def _finish_close(self):
        self._close_poll_id = None
        if self._client_running() or self._pending_journal or not self.events.empty():
            self._close_poll_id = self.window.after(25, self._finish_close)
            return
        if not self._close_summarized:
            self._close_summarized = True
            ns = time.perf_counter_ns()
            self.tracker.finish_open(ns, "程序关闭")
            self._write_round_summary("程序关闭", datetime.now().astimezone(), ns)
            if self._pending_journal:
                self._close_poll_id = self.window.after(25, self._finish_close)
                return
        self._journal_writer.close(wait=False)
        if self._journal_writer.is_alive:
            self._close_poll_id = self.window.after(25, self._finish_close)
            return
        self.window.destroy()

    def _on_destroy(self, event):
        if event.widget is not self.window:
            return
        self._destroyed = True
        for name in ("_poll_id", "_stop_poll_id", "_close_poll_id"):
            token = getattr(self, name)
            if token is not None:
                try:
                    self.window.after_cancel(token)
                except tk.TclError:
                    pass
                setattr(self, name, None)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Vanta listener GUI")
    parser.add_argument("--version", action="version", version=APP_VERSION)
    parser.add_argument("--connect", action="store_true", help="Connect when the GUI opens")
    parser.add_argument("--demo", action="store_true", help="Use local sample data")
    args = parser.parse_args()
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    window = tk.Tk()
    app = ListenerApp(window)
    if args.demo:
        app.mode.set("本地演示")
    if args.connect or args.demo:
        window.after(100, app.connect)
    window.mainloop()
