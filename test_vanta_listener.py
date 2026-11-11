#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端自动化自测脚本：
验证 VantaIXListenerGUI 的核心功能：
1. 正常 206 消息解析 (testID 连续递增、dailyID / tidName 解析)。
2. testID 跳号检测 (例如 1001 -> 1002 -> 1005，检测出缺失 [1003, 1004])。
3. 中间结果 (final=False, testId=-1) 过滤，不误报跳号。
4. 有启动 (200) 无 206 结果即停止 (201) 的漏检捕获。
5. 自动导出 206 原始 JSON 与汇总 CSV 文件校验。
"""

import csv
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import base64
import hashlib
import socket
import struct
import threading
import time
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from vanta_listener_gui import VantaIXListenerGUI


def _ws_encode_text(text: str) -> bytes:
    payload = text.encode("utf-8")
    n = len(payload)
    if n < 126:
        header = bytes([0x81, n])
    elif n < 65536:
        header = struct.pack("!BBH", 0x81, 126, n)
    else:
        header = struct.pack("!BBQ", 0x81, 127, n)
    return header + payload


def _ws_recv_text(conn: socket.socket) -> str:
    hdr = conn.recv(2)
    if len(hdr) < 2:
        return ""
    masked = (hdr[1] & 0x80) != 0
    length = hdr[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", conn.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", conn.recv(8))[0]
    mask = conn.recv(4) if masked else b""
    data = bytearray()
    while len(data) < length:
        chunk = conn.recv(length - len(data))
        if not chunk:
            break
        data.extend(chunk)
    if masked:
        data = bytearray(b ^ mask[i % 4] for i, b in enumerate(data))
    return data.decode("utf-8", errors="replace")


def run_websocket_wire_test(win: VantaIXListenerGUI):
    """启动本地模拟 Vanta WebSocket 服务端，验证 'Hi i am a listener' 握手与实时 206 传输"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
    except OSError:
        print("Skipping wire test (sandbox prohibits local socket listen)")
        return

    port = srv.getsockname()[1]

    def server_thread():
        try:
            conn, _ = srv.accept()
            req = conn.recv(4096).decode("utf-8", errors="ignore")
            key = ""
            for line in req.split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
            accept = base64.b64encode(
                hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
            ).decode()
            resp = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            )
            conn.sendall(resp.encode("utf-8"))
            handshake_msg = _ws_recv_text(conn)
            if handshake_msg == "Hi i am a listener":
                conn.sendall(_ws_encode_text("Client connected as a listener."))
                pkt_200 = json.dumps({"commandId": 403, "id": 200, "params": {}})
                pkt_206 = json.dumps(win._build_mock_206_packet(2001, 88, is_final=True))
                pkt_201 = json.dumps({"commandId": 403, "id": 201, "params": {"stopReason": "Test Complete", "stopReasonInt": 0}})
                conn.sendall(_ws_encode_text(pkt_200))
                conn.sendall(_ws_encode_text(pkt_206))
                conn.sendall(_ws_encode_text(pkt_201))
                time.sleep(0.3)
            conn.close()
        except Exception:
            pass
        finally:
            srv.close()

    t = threading.Thread(target=server_thread, daemon=True)
    t.start()

    win._on_clear_all_records()
    win.host_input.setText("127.0.0.1")
    win.port_input.setValue(port)
    win._start_listening()

    loop = QEventLoop()
    QTimer.singleShot(800, loop.quit)
    loop.exec()

    win._stop_listening()

    assert win.current_test_id == 2001, f"Wire test expected test_id=2001, got {win.current_test_id}"
    assert win.last_valid_daily_id == 88, f"Wire test expected daily_id=88, got {win.last_valid_daily_id}"
    print(f"WEBSOCKET WIRE HANDSHAKE & 206 STREAM TEST PASSED (port {port})!")


def run_self_test():
    app = QApplication.instance() or QApplication(sys.argv)
    tmp_dir = Path(tempfile.mkdtemp(prefix="vanta_test_export_"))

    try:
        win = VantaIXListenerGUI()
        win.export_dir = tmp_dir
        win.export_dir_edit.setText(str(tmp_dir))
        win.session_csv_path = tmp_dir / "test_summary.csv"

        # 1. 测试正常检测 #1 (testId=1001, dailyId=1)
        win._sim_test_id = 1000
        win._sim_daily_id = 0
        win._sim_normal_test()
        assert win.current_test_id == 1001, f"Expected 1001, got {win.current_test_id}"
        assert win.last_valid_daily_id == 1, f"Expected dailyId 1, got {win.last_valid_daily_id}"
        assert win.skipped_event_count == 0

        # 2. 测试正常检测 #2 (testId=1002, dailyId=2)
        win._sim_normal_test()
        assert win.current_test_id == 1002
        assert win.last_valid_daily_id == 2
        assert win.skipped_event_count == 0
        assert win.records_206[-1].id_status.startswith("OK")

        # 3. 测试 testID 跳号 (从 1002 跳到 1005，缺失 1003, 1004)
        win._sim_skipped_test_id()
        assert win.current_test_id == 1005
        assert win.skipped_event_count == 1
        assert win.skipped_ids_total_count == 2
        assert win.records_206[-1].skipped_ids == [1003, 1004]
        assert win.records_206[-1].id_status.startswith("SKIPPED")

        # 4. 测试有启动 (200) 但无有效 206 最终结果即停止 (201)
        win._sim_test_without_206()
        assert win.no_result_stop_count == 1

        # 5. 校验导出的 CSV 和 JSON 文件
        assert win.session_csv_path.exists(), "汇总 CSV 文件未生成"
        json_files = list((tmp_dir / "json_206").glob("*.json"))
        assert len(json_files) == 3, f"应生成 3 个 Final 206 JSON 文件，实际: {len(json_files)}"

        with open(win.session_csv_path, "r", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        assert len(rows) == 4, f"CSV 应包含表头 + 3 行记录，实际: {len(rows)}"
        assert rows[3][4] == "1005"
        assert rows[3][7] == "1003;1004"

        run_websocket_wire_test(win)
        print("ALL SELF-TESTS PASSED SUCCESSFULLY!")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_self_test()
