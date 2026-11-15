"""Parse chemistry and keep a history of final Vanta results."""

from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass(frozen=True)
class Element:
    name: str
    concentration: Any
    error: Any
    unit: str
    source: str


@dataclass(frozen=True)
class ResultNotice:
    test_id: str = ""
    is_final: bool | None = None
    id_status: str | None = None
    id_delta: int | None = None
    daily_id_num: int | None = None
    daily_id_status: str | None = None
    daily_id_delta: int | None = None


@dataclass
class Measurement:
    seq: int
    session: int
    endpoint: str
    result_ns: int
    result_at: datetime
    raw_result: dict
    test_id: str = ""
    daily_id: str = ""
    method: str = ""
    elements: list[Element] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    daily_id_num: int | None = None

    @property
    def device_timing(self) -> tuple[str, int | float | None]:
        return read_device_timing(self.raw_result)


def parse_device_json(raw: str) -> tuple[Any, bool]:
    """Preserve non-finite readings as strings in otherwise valid JSON."""
    nonfinite = False

    def constant(name: str) -> str:
        nonlocal nonfinite
        nonfinite = True
        return name

    def number(source: str) -> float | str:
        value = float(source)
        if math.isfinite(value):
            return value
        return constant("-Infinity" if value < 0 else "Infinity")

    data = json.loads(raw, parse_constant=constant, parse_float=number)
    return data, nonfinite


def _identifier(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int):
        return str(value) if value >= 0 else ""
    if isinstance(value, str) and value.strip() and not value.strip().startswith("-"):
        return value.strip()
    return ""


def _test_id(result: dict) -> str:
    analysis = result.get("analysis")
    analysis = analysis if isinstance(analysis, dict) else {}
    for source in (result, analysis):
        for key in ("testId", "testID", "TESTID"):
            value = _identifier(source.get(key))
            if value:
                return value
    return ""


def _scalar(value: Any) -> Any:
    # Preserve zero, BDL strings and missing values. Do not create zero readings.
    return value if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None


def result_payload(params: Any) -> dict | None:
    if not isinstance(params, dict):
        return None
    result = params.get("result", params)
    return result if isinstance(result, dict) else None


def read_device_timing(result: dict | None) -> tuple[str, int | float | None]:
    analysis = result.get("analysis") if result is not None else None
    if not isinstance(analysis, dict):
        return "", None
    timestamp = analysis.get("testDateTime")
    device_time = timestamp.strip() if isinstance(timestamp, str) else ""
    elapsed = analysis.get("elapsedTime")
    valid_elapsed = (
        (type(elapsed) is int and elapsed >= 0)
        or (type(elapsed) is float and math.isfinite(elapsed) and elapsed >= 0)
    )
    return device_time, elapsed if valid_elapsed else None


def _device_day(analysis: dict) -> str | None:
    timestamp = analysis.get("testDateTime")
    if isinstance(timestamp, str):
        try:
            return datetime.fromisoformat(timestamp.strip().replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    return None


def parse_elements(result: dict, *, source: str | None = None) -> tuple[list[Element], list[str]]:
    issues: list[str] = []
    if source is None:
        processed = result.get("processedChemistry")
        source = "processedChemistry" if isinstance(processed, list) and processed else "chemistry"
    values = result.get(source, [])
    if not isinstance(values, list):
        return [], ["元素数据不是数组"]
    elements = []
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("elementName"), str) or not value["elementName"].strip():
            issues.append("已跳过无效元素行")
            continue
        unit = value.get("unit") or value.get("units") or result.get("unit") or result.get("units")
        unit = unit if isinstance(unit, str) and unit.strip() else "%"
        elements.append(Element(value["elementName"].strip(), _scalar(value.get("concentration")),
                                _scalar(value.get("error")), unit, source))
    if not elements:
        issues.append("结果没有有效元素行")
    return elements, list(dict.fromkeys(issues))


class ListenerModel:
    """Read each result independently and detect repeated final results."""

    def __init__(self, max_records: int = 1000, max_seen: int = 100_000):
        self.max_records = max(1, max_records)
        self.max_seen = max(self.max_records, max_seen)
        self.records: list[Measurement] = []
        self.intermediate_count = 0
        self.duplicate_count = 0
        self.session = 0
        self.endpoint = ""
        self._seq = 0
        self._last_final_number: int | None = None
        self._reconnected = False
        self._last_daily: tuple[str, int] | None = None
        self._seen: OrderedDict[tuple[str, str | bytes], tuple[bytes, int]] = OrderedDict()

    def begin_session(self, endpoint: str) -> None:
        if self.session and endpoint == self.endpoint:
            self._reconnected = self._last_final_number is not None
        else:
            self.reset_test_id_sequence()
        self.session += 1
        self.endpoint = endpoint

    def reset_test_id_sequence(self) -> None:
        self._last_final_number = None
        self._reconnected = False
        self._last_daily = None

    def process(self, message: dict, received_ns: int, received_at: datetime, *,
                compare_test_ids: bool = True, nonfinite: bool = False) -> ResultNotice | None:
        if not isinstance(message, dict) or message.get("commandId") != 403 or message.get("id") != 206:
            return None
        result = result_payload(message.get("params"))
        if result is None:
            return ResultNotice()
        test_id = _test_id(result)
        analysis = result.get("analysis")
        final = analysis.get("final") if isinstance(analysis, dict) else None
        if final is True:
            return self._final(result, test_id, received_ns, received_at,
                               compare_test_ids=compare_test_ids, nonfinite=nonfinite)
        if final is False:
            self.intermediate_count += 1
            return ResultNotice(test_id, False)
        return ResultNotice(test_id)

    def _check_test_id(self, test_id: str, *, conflict: bool = False) -> tuple[str, int | None]:
        number = None
        if test_id.isascii() and test_id.isdecimal():
            try:
                number = int(test_id)
            except ValueError:
                # An oversized decimal string can exceed Python's conversion limit.
                pass
        previous = self._last_final_number
        delta = number - previous if number is not None and previous is not None else None
        if conflict:
            return "conflict", delta

        # A final result without a usable ID breaks the chain of comparisons.
        self._last_final_number = number
        if number is None:
            status = "missing_id" if not test_id else "invalid_id"
        elif delta is None:
            status = "first"
        elif delta == 1:
            status = "consecutive"
        elif delta > 1:
            status = "gap_after_reconnect" if self._reconnected else "gap"
        elif delta < 0:
            status = "backward"
        else:
            status = "repeated_id"
        if number is not None:
            self._reconnected = False
        return status, delta

    def _check_daily(self, day: str | None, number: int | None) -> tuple[str | None, int | None]:
        previous = self._last_daily
        if day is None or number is None:
            self._last_daily = None
            return None, None
        self._last_daily = (day, number)
        if previous is None:
            return "first", None
        if day != previous[0]:
            return ("daily_reset" if number == 1 else "first"), None
        delta = number - previous[1]
        if delta == 1:
            return "consecutive", delta
        if delta > 1:
            return "gap", delta
        return ("backward" if delta < 0 else "repeated_id"), delta

    def _final(self, result: dict, test_id: str, ns: int, at: datetime, *,
               compare_test_ids: bool, nonfinite: bool) -> ResultNotice:
        fingerprint = hashlib.sha256(json.dumps(result, sort_keys=True,
                                                separators=(",", ":")).encode("ascii")).digest()
        # The local project defines TESTID as the result identity. Changed
        # content with the same ID is a conflict, even if date/method changes.
        analysis = result["analysis"]
        daily = analysis.get("dailyId")
        daily = daily if type(daily) is int and daily > 0 else None
        key = (self.endpoint, test_id or fingerprint)
        previous = self._seen.get(key)
        if previous is not None:
            self._seen.move_to_end(key)
            self.duplicate_count += 1
            if previous[0] != fingerprint:
                issue = "同一 testID 的结果内容有冲突。已保留第一份结果。"
                if self.records:
                    history_index = previous[1] - self.records[0].seq
                    if 0 <= history_index < len(self.records) and issue not in self.records[history_index].issues:
                        self.records[history_index].issues.append(issue)
                if compare_test_ids:
                    status, delta = self._check_test_id(test_id, conflict=True)
                    return ResultNotice(test_id, True, status, delta, daily)
                return ResultNotice(test_id, True, "conflict", daily_id_num=daily)
            return ResultNotice(test_id, True, "duplicate", daily_id_num=daily)
        self._seq += 1
        elements, issues = parse_elements(result)
        if not test_id:
            issues.append("缺少有效 testID。按结果内容去重。")
        if analysis.get("testErrorInfo") not in (None, "", "No error", "No error "):
            issues.append(f"设备结果信息 · {analysis['testErrorInfo']}")
        if nonfinite:
            issues.append("报文含非有限数值（NaN/Infinity），已按字符串保存。")
        status, delta = self._check_test_id(test_id) if compare_test_ids else (None, None)
        daily_status, daily_delta = self._check_daily(_device_day(analysis), daily) if compare_test_ids else (None, None)
        if delta is not None and daily_delta is not None and delta != daily_delta:
            issues.append(f"testID 与 dailyId 增量不同（{delta:+d} / {daily_delta:+d}）。")
        record = Measurement(
            self._seq, self.session, self.endpoint, ns, at, result,
            test_id=test_id, daily_id=str(analysis.get("tidName", "")),
            method=str(analysis.get("methodDispName") or analysis.get("methodId") or "未声明"),
            elements=elements, issues=issues, daily_id_num=daily,
        )
        self.records.append(record)
        del self.records[:-self.max_records]
        self._seen[key] = (fingerprint, record.seq)
        while len(self._seen) > self.max_seen:
            self._seen.popitem(last=False)
        return ResultNotice(test_id, True, status, delta, daily, daily_status, daily_delta)
