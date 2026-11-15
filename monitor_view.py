"""Show each 206 packet and load packet details only when selected."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from itertools import islice
import json
import tkinter as tk
from tkinter import ttk

from core import Element
from log_format import bounded_line, display_value


MAX_PACKETS = 300
JSON_PAGE_SIZE = 80
CHEMISTRY_SOURCES = ("chemistry", "processedChemistry")
PACKET_HIDDEN_FIELDS = frozenset((*CHEMISTRY_SOURCES, "olympusResult"))
EXPORT_LABELS = {
    "saved": "已导出",
    "already_saved": "文件已存在",
    "conflict": "同名文件冲突",
    "invalid_id": "文件名无效",
    "error": "导出失败",
}


def scroll_table(frame, table):
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    table.grid(row=0, column=0, sticky="nsew")
    vertical = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=table.xview)
    horizontal.grid(row=1, column=0, sticky="ew")
    table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)


def chemistry_table(frame, height: int) -> ttk.Treeview:
    columns = ("element", "value", "error", "unit", "source")
    table = ttk.Treeview(frame, columns=columns, show="headings", height=height)
    for key, title, width in zip(columns, ("元素", "含量", "误差 / 1σ", "单位", "字段来源"),
                                  (65, 115, 115, 65, 155)):
        table.heading(key, text=title)
        table.column(key, width=width, minwidth=45)
    scroll_table(frame, table)
    return table


def _display_number(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return format(value, ".9g")
    return bounded_line(str(value))


def show_elements(table: ttk.Treeview, elements: list[Element]) -> None:
    children = table.get_children()
    if children:
        table.delete(*children)
    for item in elements:
        table.insert("", "end", values=(bounded_line(item.name), _display_number(item.concentration),
                                        _display_number(item.error), bounded_line(item.unit), item.source))


@dataclass
class PacketRow:
    entry: dict
    check: str
    export: dict | None = None

    @property
    def export_text(self) -> str:
        if self.export is None:
            return "等待导出" if self.entry["isFinal"] is True else "—"
        label = EXPORT_LABELS[self.export["status"]]
        file = self.export.get("file")
        return f"{label} · {file}" if file else label


class PacketMonitor(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.rows: OrderedDict[str, PacketRow] = OrderedDict()
        self.follow = tk.BooleanVar(self, value=True)
        self._selection_status = tk.StringVar(self, value="等待 206")
        self._displayed = None
        self._dirty = False
        self._row_cache = {}
        self._json_pending = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1, minsize=65)
        self.rowconfigure(2, weight=2, minsize=90)
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 2))
        ttk.Label(bar, textvariable=self._selection_status).pack(side="left")
        ttk.Checkbutton(bar, text="跟随最新 206", variable=self.follow,
                        command=self._refresh_selection).pack(side="right")

        list_frame = ttk.Frame(self)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=6)
        columns = ("seq", "test_id", "final", "device_time", "device_elapsed", "received", "check", "export")
        self.packets = ttk.Treeview(list_frame, columns=columns, show="headings", height=4, selectmode="browse")
        for key, title, width in zip(columns,
                                      ("序号", "testID", "isFinal", "设备检测时刻", "设备耗时 / s",
                                       "接收时间", "编号检查", "JSON 导出"),
                                      (55, 80, 65, 170, 100, 195, 155, 200)):
            self.packets.heading(key, text=title)
            self.packets.column(key, width=width, minwidth=45)
        scroll_table(list_frame, self.packets)
        self.packets.bind("<<TreeviewSelect>>", self._show_packet)
        self.packets.tag_configure("warning", foreground="#a35b13")
        self.packets.tag_configure("gap", background="#fff0d4", foreground="#8d350f")

        packet_frame = ttk.Labelframe(self, text="报文字段（展开查看）", padding=6)
        packet_frame.grid(row=2, column=0, sticky="nsew", padx=6, pady=(6, 3))
        self.fields = ttk.Treeview(packet_frame, columns=("value",), height=4)
        self.fields.heading("#0", text="字段")
        self.fields.heading("value", text="值")
        self.fields.column("#0", width=165, minwidth=75)
        self.fields.column("value", width=260, minwidth=90)
        scroll_table(packet_frame, self.fields)
        self.fields.bind("<<TreeviewOpen>>", self._open_field)

    def add(self, entry: dict, check: str) -> None:
        self.rows[str(entry["packetNo"])] = PacketRow(entry, check)
        if len(self.rows) > MAX_PACKETS:
            self.rows.popitem(last=False)
        self._dirty = True

    def set_export(self, seq: int, outcome: dict) -> None:
        packet = self.rows.get(str(seq))
        if packet is not None:
            packet.export = outcome
            self._dirty = True

    def clear(self) -> None:
        self.rows.clear()
        self._dirty = True
        self.refresh()

    def refresh(self) -> None:
        if not self._dirty:
            return
        self._dirty = False
        current = set(self.packets.get_children())
        for iid in current - self.rows.keys():
            self.packets.delete(iid)
            self._row_cache.pop(iid, None)
        for iid, packet in self.rows.items():
            entry = packet.entry
            test_id = bounded_line((entry["testID"] or "—")[:64])
            device_elapsed = entry.get("deviceElapsedSeconds")
            values = (entry["roundPacketNo"], test_id, json.dumps(entry["isFinal"]), bounded_line(entry.get("deviceTestTime") or "—"),
                      str(device_elapsed) if device_elapsed is not None else "—", entry["received_at"],
                      bounded_line(packet.check) or "—", bounded_line(packet.export_text))
            warning = entry.get("testIDStatus") in ("gap", "backward", "conflict", "repeated_id")
            if packet.export and packet.export["status"] in ("conflict", "invalid_id", "error"):
                warning = True
            tags = ("warning",) if warning else ()
            if entry.get("testIDStatus") == "gap":
                tags = ("gap",)
            if iid not in current:
                self.packets.insert("", "end", iid=iid, values=values, tags=tags)
            elif self._row_cache[iid] != (values, tags):
                self.packets.item(iid, values=values, tags=tags)
            self._row_cache[iid] = (values, tags)
        self._refresh_selection()

    def _refresh_selection(self) -> None:
        if self.rows and (self.follow.get() or not self.packets.selection()):
            iid = next(reversed(self.rows))
            if self.packets.selection() != (iid,):
                self.packets.selection_set(iid)
                self.packets.see(iid)
        self._show_packet()

    def _show_packet(self, _event=None) -> None:
        iid = next(iter(self.packets.selection()), None)
        packet = self.rows.get(iid)
        if packet is not None:
            endpoint = packet.entry["endpoint"]
            detail = f"206 #{packet.entry['roundPacketNo']} · {endpoint or '设备'} · {packet.export_text}"
            if packet.export and packet.export.get("error"):
                detail += f" · {packet.export['error']}"
            self._selection_status.set(bounded_line(detail)[:180])
        else:
            self._selection_status.set("等待 206")
        if iid == self._displayed:
            return
        self._displayed = iid
        self._json_pending.clear()
        children = self.fields.get_children()
        if children:
            self.fields.delete(*children)
        if packet is not None:
            self._add_fields("", packet.entry["message"], 0)

    @staticmethod
    def _field_count(value: dict | list) -> int:
        if isinstance(value, dict):
            return len(value) - sum(key in value for key in PACKET_HIDDEN_FIELDS)
        return len(value)

    def _add_fields(self, parent: str, value: dict | list, start: int) -> None:
        end = start + JSON_PAGE_SIZE
        if isinstance(value, dict):
            entries = islice((pair for pair in value.items() if pair[0] not in PACKET_HIDDEN_FIELDS), start, end)
        else:
            entries = enumerate(value[start:end], start)
        for key, item in entries:
            label = bounded_line(str(key)[:120])
            if isinstance(item, (dict, list)):
                count = self._field_count(item)
                description = f"{count} 个字段" if isinstance(item, dict) else f"{count} 项"
                self._add_branch(parent, label, description, item, 0)
            else:
                self.fields.insert(parent, "end", text=label,
                                   values=(bounded_line(display_value(item, key=label)),))
        if end < self._field_count(value):
            self._add_branch(parent, f"更多（从第 {end + 1} 项起）", "", value, end)

    def _add_branch(self, parent: str, label: str, description: str, value, offset: int) -> None:
        node = self.fields.insert(parent, "end", text=label, values=(description,))
        if self._field_count(value):
            self._json_pending[node] = (value, offset)
            self.fields.insert(node, "end", text="…")

    def _open_field(self, _event=None) -> None:
        node = self.fields.focus()
        pending = self._json_pending.pop(node, None)
        if pending is not None:
            self.fields.delete(*self.fields.get_children(node))
            self._add_fields(node, *pending)
