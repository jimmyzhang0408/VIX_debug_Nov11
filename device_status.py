"""Translate Vanta notifications for the status bar."""

from __future__ import annotations

import math

from log_format import bounded_line, log_preview


STATUS_NOTIFICATION_IDS = frozenset((100, 200, 201, 202, 203, 207, 209, 704))
SYSTEM_STATES = {
    "ready": "就绪",
    "x-rays off": "X 射线关闭",
    "x-rays on": "X 射线开启",
}
STATUS_DETAILS = {
    "ending test...": "正在结束检测",
    "test complete": "检测完成",
}
STOP_REASONS = {
    "test complete": "检测完成",
    "complete": "检测完成",
    "time elapsed": "达到设定曝光时间",
}


def _text(value, labels: dict[str, str]) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()[:160]
    return bounded_line(labels.get(text.casefold(), text))


def _count(value) -> int | None:
    return value if type(value) is int and 0 < value <= 1_000_000 else None


def _seconds(value) -> str:
    if type(value) is int and value >= 0:
        return str(value)[:24]
    if type(value) is float and math.isfinite(value) and value >= 0:
        return f"{value:g}"
    return ""


class DeviceStatus:
    def __init__(self):
        self.connection_changed(False)

    def connection_changed(self, connected: bool) -> None:
        self.system = "等待设备状态" if connected else "未连接"
        self.phase = "等待检测" if connected else "—"

    def notification(self, event: int, params) -> str:
        if not isinstance(params, dict):
            return "通知参数格式无效"
        if event == 100:
            system = _text(params.get("systemStatus"), SYSTEM_STATES) or "状态未提供"
            info = _text(params.get("info"), STATUS_DETAILS)
            bits = params.get("statusBits")
            details = [system]
            if info:
                details.append(info)
            if type(bits) is int and bits != 0:
                details.append(f"状态位 {bits}")
            self.system = " · ".join(details)
            return f"设备报告 · {self.system}"
        if event == 200:
            self.phase = "检测开始 · 等待曝光"
            return "检测开始"
        if event == 201:
            reason = _text(params.get("stopReason"), STOP_REASONS)
            code = params.get("stopReasonInt")
            parts = ["检测结束"]
            if reason:
                parts.append(reason)
            self.phase = " · ".join(parts)
            if type(code) is int:
                parts.append(f"原因码 {code}")
            return " · ".join(parts)
        if event == 209:
            self.phase = "设备报告检测错误"
            return f"检测错误 · {log_preview(params)}" if params else "检测错误"
        if event == 704:
            key = params.get("keyActivated")
            if type(key) is int and key in (6, 7):
                return "START 输入激活" if key == 6 else "START 输入释放"
            return f"按键事件 · {log_preview(params)}"

        exposure = _count(params.get("exposureNum"))
        maximum = _count(params.get("maxExposures"))
        if exposure is not None and maximum is not None:
            beam = f"曝光 {exposure}/{maximum}"
        elif exposure is not None:
            beam = f"第 {exposure} 段曝光"
        else:
            beam = "曝光"

        if event == 202:
            line = f"{beam} 开始"
            phase = f"{beam} 进行中"
        elif event == 203:
            line = f"{beam} 结束"
            reason = _text(params.get("finalExposureStatus"), STOP_REASONS)
            if reason:
                line += f" · {reason}"
            phase = line
        else:
            elapsed = _seconds(params.get("elapsedTime"))
            total = _seconds(params.get("totalTime"))
            line = f"{beam} 进度"
            if elapsed and total:
                line += f" · {elapsed} / {total} s"
            elif elapsed:
                line += f" · 已曝光 {elapsed} s"
            repeat = _count(params.get("repeatTestNum"))
            total_repeats = _count(params.get("totalRepeatTests"))
            if repeat is not None and total_repeats is not None and total_repeats > 1:
                line += f" · 重复检测 {repeat}/{total_repeats}"
            phase = line
        self.phase = phase
        return line
