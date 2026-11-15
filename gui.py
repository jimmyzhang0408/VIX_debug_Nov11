"""Tk views for Arduino status, Vanta notifications and chemistry."""

from __future__ import annotations

import csv
import json
from collections import deque
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime

from arduino import ArduinoClient, ArduinoLine, ArduinoReport, BAUD_RATE, parse_arduino_control
from core import ListenerModel, Measurement, parse_elements, read_device_timing, result_payload
from device_status import DeviceStatus, STATUS_NOTIFICATION_IDS
from journal import AsyncJournal
from log_format import bounded_line
from monitor_view import CHEMISTRY_SOURCES, PacketMonitor, chemistry_table, scroll_table, show_elements
from transport import DemoClient, ListenerClient


ROOT = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
DEFAULT_IP = "169.254.90.208"
DEFAULT_PORT = 7860
DEFAULT_SERIAL_PORT = "COM4"
ARDUINO_STALE_NS = 4_000_000_000
MAX_PACKETS_PER_TICK = 25
POLL_BUDGET_SECONDS = 0.008
REFRESH_SECONDS = 0.1
MAX_LOG_BATCH = 40
DEVICE_EVENT_IDS = STATUS_NOTIFICATION_IDS | {206}
TEST_ID_STATUS_LABELS = {
    "first": "首条最终结果",
    "consecutive": "连续",
    "gap": "告警 · 跳号",
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
}


def stamp(value: datetime | None) -> str:
    return value.isoformat(sep=" ", timespec="milliseconds") if value else ""


def write_results_csv(path: Path, records: list[Measurement]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["序号", "连接会话", "数据来源", "testId", "每日编号_tidName", "方法",
                         "最终206接收时间", "设备检测时刻", "设备检测耗时_s", "备注"])
        for r in records:
            device_time, device_elapsed = r.device_timing
            writer.writerow([r.seq, r.session, r.endpoint, r.test_id, r.daily_id, r.method,
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
        self._pending_journal = None
        self._live_entry = None
        self._live_displayed = None
        self._arduino_report: ArduinoReport | None = None
        self._arduino_source = ""
        self._arduino_deadline_ns: int | None = None
        self._trigger_progress: tuple[int, int] | None = None
        self._count_start_ns = 0
        event_queue = self.events
        self._journal_writer = AsyncJournal(
            ROOT / "runtime" / "listener_ids.jsonl",
            on_error=lambda text: event_queue.put((None, "journal_error", text)),
            result_dir=ROOT / "runtime" / "results",
            on_export=lambda seq, outcome: event_queue.put((None, "result_export", (seq, outcome))),
        )
        self.host = tk.StringVar(value=DEFAULT_IP)
        self.port = tk.StringVar(value=str(DEFAULT_PORT))
        self.serial_port = tk.StringVar(value=DEFAULT_SERIAL_PORT)
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
        self._build()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Destroy>", self._on_destroy, add=True)
        self._poll_id = self.window.after(50, self._poll)

    def _build(self):
        w = self.window
        w.title("Vanta iX 实时监控")
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
        columns = ("seq", "test", "method", "device_time", "device_elapsed", "final", "notes")
        self.history = ttk.Treeview(history_frame, columns=columns, show="headings", height=4, selectmode="browse")
        for key, title, width in zip(columns,
                                      ("序号", "testId", "检测方法", "设备检测时刻", "设备耗时 / s",
                                       "结果接收时间", "备注"),
                                      (50, 80, 125, 170, 100, 205, 200)):
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
        ttk.Label(console, text="START [次数]   ·   STOP   ·   CLEAR FAULT").grid(
            row=2, column=0, sticky="w", pady=(4, 0),
        )

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
            event_queue.put((generation, "stopped", "手动断开"))
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
        self._count_start_ns = time.perf_counter_ns()
        previous = self.result_count.get()
        previous_packets = self._round_packet_no
        self.result_count.set(0)
        self._round_packet_no = 0
        self.model.reset_test_id_sequence()
        self.monitor.clear()
        self._show_test_id_alert("")
        self.events.put((None, "counter_reset", {
            "kind": "counter_reset", "id": None, "source": "app",
            "received_at": stamp(datetime.now().astimezone()), "received_ns": self._count_start_ns,
            "previousCount": previous, "resultCount": 0,
            "previousPacketCount": previous_packets, "roundPacketNo": 0,
        }))

    def _show_test_id_alert(self, message: str) -> None:
        self.test_id_alert.set(bounded_line(message)[:200])
        if message:
            self.id_alert_label.pack(anchor="w", pady=(4, 0))
        else:
            self.id_alert_label.pack_forget()

    def _submit_log(self, entry: dict) -> None:
        if not self._journal_writer.submit(entry, report_full=False):
            self._pending_journal = entry

    def _receive_arduino_line(self, line: ArduinoLine) -> bool:
        text = line.text.replace("\r", "\\r").replace("\n", "\\n").replace("\0", "\\0")
        timestamp = line.at.strftime("%H:%M:%S.%f")[:-3]
        self._pending_serial_logs.append(f"{timestamp}  {line.direction}  {text}\n")
        if line.report is not None:
            self._receive_arduino(line.report)
            return True
        entry = {
            "kind": "arduino_serial", "id": None, "source": "arduino", "port": self._arduino_source,
            "received_at": stamp(line.at), "direction": line.direction, "text": line.text,
        }
        control = parse_arduino_control(line.text) if line.direction == "RX" else None
        if control is not None:
            entry.update(kind="arduino_control", event=control.event,
                         sent=control.sent, total=control.total, error=control.error)
            if control.sent is not None and control.total is not None:
                self._trigger_progress = (control.sent, control.total)
            detail = f"命令反馈 {control.error}" if control.error else CONTROL_LABELS.get(control.event, control.event)
            if self._trigger_progress is not None:
                sent, total = self._trigger_progress
                detail += f" · 已发 {sent} / {total}"
            self.control_status.set(f"板端批次 · {detail}")
            self._pending_logs.append(f"{timestamp}  Arduino {self._arduino_source}  {detail}\n")
        self._submit_log(entry)
        return False

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
        raw = packet.raw.decode("utf-8") if isinstance(packet.raw, bytes) else packet.raw
        message = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if not isinstance(message, dict):
            raise ValueError("JSON 顶层不是对象")
        event = message.get("id")
        if message.get("commandId") != 403 or type(event) is not int or event not in DEVICE_EVENT_IDS:
            return False

        in_round = packet.received_ns >= self._count_start_ns
        notice = self.model.process(message, packet.received_ns, packet.received_at, compare_test_ids=in_round)
        entry = {
            "kind": "api_status", "id": event, "message": message,
            "received_at": stamp(packet.received_at), "received_ns": packet.received_ns,
            "session": self.model.session, "endpoint": self.model.endpoint,
            "source": "demo" if self.mode.get() == "本地演示" else "device",
        }
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
            if notice.id_status == "gap" and notice.id_delta is not None:
                previous_id = str(int(notice.test_id) - notice.id_delta)
                skipped = notice.id_delta - 1
                entry["testIDGap"] = {"previous": previous_id, "skipped": skipped}
                warning = f"告警 · testID 跳号 {previous_id} → {test_id} · 跳过 {skipped} 个编号"
                self._show_test_id_alert(warning)
                line += f"  {warning}"
            elif check:
                line += f"  {check}"
            if in_round:
                self.monitor.add(entry, check)
            self._live_entry = entry
            self._history_dirty = self._history_dirty or notice.is_final is True
        else:
            detail = self.device_status.notification(event, message.get("params", {}))
            entry["description"] = detail
            line += f"  {detail}"
        self._pending_logs.append(bounded_line(line) + "\n")
        self._submit_log(entry)
        return True

    def _poll(self):
        if self._poll_id is not None:
            self.window.after_cancel(self._poll_id)
            self._poll_id = None
        deadline = time.perf_counter() + POLL_BUDGET_SECONDS
        changed = False
        for index in range(MAX_PACKETS_PER_TICK):
            if index and time.perf_counter() >= deadline:
                break
            if self._pending_journal is not None:
                if not self._journal_writer.submit(self._pending_journal, report_full=False):
                    break
                self._pending_journal = None
            try:
                generation, kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "journal_error":
                self.status.set(f"日志文件写入失败：{payload}")
                continue
            if kind == "result_export":
                self.monitor.set_export(*payload)
                changed = True
                continue
            if kind == "counter_reset":
                self._submit_log(payload)
                self._pending_logs.append(f"{payload['received_at']}  最终结果计数和 206 序号已清零\n")
                continue
            if generation != self.generation:
                continue
            if kind == "packet":
                try:
                    changed = self._receive_packet(payload) or changed
                except (ValueError, TypeError, RecursionError) as exc:
                    self.status.set(f"无效消息，已跳过：{exc}")
            elif kind == "connected":
                self.model.begin_session(str(payload))
                self.device_status.connection_changed(True)
                self._live_entry = None
                self.status.set(f"已连接 · {payload}" + (" · 演示数据" if self.mode.get() == "本地演示" else " · 监听者"))
                changed = True
            elif kind in ("disconnected", "stopped"):
                self.device_status.connection_changed(False)
                self._live_entry = None
                self.status.set(f"已断开 · {payload}")
                changed = True
                if kind == "stopped":
                    self._clear_arduino("未连接")
                    self._finish_stop()
            elif kind == "start_failed":
                if self._stopping:
                    self._finish_stop()
                else:
                    self.status.set(f"无法开始监听：{payload}")
                    self.client = None
                    self._busy(self.serial_client is not None)
            elif kind == "arduino_connected":
                self._arduino_source = str(payload)
                self._trigger_progress = None
                self.control_status.set("板端批次 · 等待控制回报")
                self._clear_arduino(f"{payload} · {BAUD_RATE} 波特 · 等待状态")
                self._arduino_deadline_ns = time.perf_counter_ns() + ARDUINO_STALE_NS
                self._enable_commands(self.serial_client is not None and not self._stopping and not self._closing)
                changed = True
            elif kind == "arduino_disconnected":
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
        if self._arduino_deadline_ns is not None and time.perf_counter_ns() >= self._arduino_deadline_ns:
            detail = "状态超时" if self._arduino_report is not None else "等待 GPIO 报告"
            self._clear_arduino(f"{self._arduino_source} · 串口已打开 · {detail}")
            changed = True
        self._dirty = self._dirty or changed
        if self._dirty and time.perf_counter() >= self._next_refresh:
            self.refresh()
            self._dirty = False
            self._next_refresh = time.perf_counter() + REFRESH_SECONDS
        self._flush_log(self.log, self._pending_logs)
        self._flush_log(self.serial_log, self._pending_serial_logs)
        self._poll_id = self.window.after(30, self._poll)

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
            values = (record.seq, record.test_id or "—", record.method or "—", bounded_line(device_time) or "—",
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
            detail = (f"本地序号：{r.seq}\n连接会话：{r.session}\n数据来源：{r.endpoint}\n"
                      f"testId：{r.test_id or '未声明'}\n每日编号 tidName：{r.daily_id or '未声明'}\n"
                      f"检测方法：{r.method or '未声明'}\n"
                      f"设备检测时刻：{bounded_line(device_time) or '—'}\n"
                      f"设备检测耗时 / s：{elapsed_text}\n"
                      f"结果接收时间：{stamp(r.result_at)}\n备注：{' / '.join(r.issues) or '无'}")
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", detail)
        self.detail.configure(state="disabled")

    def clear(self):
        if self.client is not None or self.serial_client is not None:
            return
        self.model = ListenerModel()
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
        if self._client_running() or self._pending_journal is not None or not self.events.empty():
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
