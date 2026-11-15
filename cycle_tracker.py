"""Reconcile Arduino pulses and Vanta notifications on the host clock."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from core import ResultNotice
from device_status import classify_stop

ACK_TIMEOUT_NS = 3_000_000_000
START_TIMEOUT_NS = 5_000_000_000
TEST_TIMEOUT_NS = 180_000_000_000
RESULT_TIMEOUT_NS = 5_000_000_000
ABORT_GRACE_NS = 3_000_000_000
DOUBLE_LINK_WINDOW_NS = 2_000_000_000
REORDER_WINDOW_NS = 250_000_000


class Outcome(str, Enum):
    NORMAL = "NORMAL"
    EMPTY_SHOT = "EMPTY_SHOT"
    DOUBLE_START_STOP = "DOUBLE_START_STOP"
    ABNORMAL_STOP = "ABNORMAL_STOP"
    NO_RESPONSE = "NO_RESPONSE"
    NO_RESULT = "NO_RESULT"
    UNKNOWN_STOP = "UNKNOWN_STOP"
    UNSOLICITED = "UNSOLICITED"
    INCONCLUSIVE = "INCONCLUSIVE"


def _elapsed_ms(start: int | None, end: int | None) -> float | None:
    return round((end - start) / 1_000_000, 3) if start is not None and end is not None else None


@dataclass
class Cycle:
    no: int
    trigger_no: int | None
    trigger_ns: int | None
    first_ns: int
    double_second_ns: int | None = None
    ready_drop_ns: int | None = None
    rad_on_ns: int | None = None
    rad_off_ns: int | None = None
    ev702_ns: int | None = None
    ev704_ns: int | None = None
    second_key_ns: int | None = None
    activity_ns: int | None = None
    ev200_ns: int | None = None
    ev201_ns: int | None = None
    stop_reason: str | None = None
    stop_code: int | None = None
    stop_class: str | None = None
    ev209: list[dict] = field(default_factory=list)
    intermediate_206: int = 0
    final_206_ns: int | None = None
    test_id: str | None = None
    test_id_status: str | None = None
    result_key: str | None = None
    disconnected: bool = False
    board_no_response: bool = False
    board_rad_on: bool = False
    uncertain: bool = False
    outcome: Outcome | None = None
    closed_ns: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ack_ns(self) -> int | None:
        return min(
            (ns for ns in (self.ready_drop_ns, self.rad_on_ns, self.ev702_ns, self.ev704_ns,
                           self.ev200_ns, self.activity_ns)
             if ns is not None),
            default=None,
        )

    @property
    def unsolicited(self) -> bool:
        return self.trigger_ns is None

    def to_entry(self) -> dict:
        return {
            "kind": "cycle", "id": None, "cycleNo": self.no, "triggerNo": self.trigger_no,
            "outcome": self.outcome.value if self.outcome is not None else None,
            "triggerNs": self.trigger_ns, "startNs": self.ev200_ns, "stopNs": self.ev201_ns,
            "finalNs": self.final_206_ns, "closedNs": self.closed_ns, "testID": self.test_id,
            "deviceTestTime": self.result_key, "testIDStatus": self.test_id_status,
            "readyDropNs": self.ready_drop_ns, "radOnNs": self.rad_on_ns, "radOffNs": self.rad_off_ns,
            "triggerReportedNs": self.ev702_ns, "startKeyNs": self.ev704_ns, "stopReason": self.stop_reason,
            "stopCode": self.stop_code, "stopClass": self.stop_class,
            "t_trigger_to_ack_ms": _elapsed_ms(self.trigger_ns, self.ack_ns),
            "t_trigger_to_200_ms": _elapsed_ms(self.trigger_ns, self.ev200_ns),
            "t_200_to_201_ms": _elapsed_ms(self.ev200_ns, self.ev201_ns),
            "t_201_to_final_ms": _elapsed_ms(self.ev201_ns, self.final_206_ns),
            "intermediate206": self.intermediate_206, "ev209": list(self.ev209),
            "doubleSecond": self.double_second_ns is not None or self.second_key_ns is not None,
            "secondStartKeyNs": self.second_key_ns, "disconnected": self.disconnected,
            "boardNoResponse": self.board_no_response, "boardRadOn": self.board_rad_on,
            "unsolicited": self.unsolicited, "notes": list(self.notes),
        }


class CycleTracker:
    """Count each observed attempt once. A test ID identifies a result, not a pulse."""

    def __init__(self, on_close: Callable[[Cycle], None]):
        self._on_close = on_close
        self.counts: Counter[Outcome] = Counter()
        self.triggers = 0
        self.open_cycles: list[Cycle] = []
        self._sequence = 0
        self._capture: set[str] = set()
        self._gpio: tuple[bool, bool] | None = None
        self._key_down = False
        self._pending_key_ns: int | None = None
        self._double_pending: Cycle | None = None
        self._second_candidate: Cycle | None = None
        self._endpoint: str | None = None
        # Keep recent identities to keep late packets out of newer cycles.
        self._closed: deque[Cycle] = deque(maxlen=128)

    def _new(self, now_ns: int, *, sent: int | None = None, trigger: bool = False) -> Cycle:
        self._sequence += 1
        cycle = Cycle(self._sequence, sent, now_ns if trigger else None, now_ns)
        if trigger and "api" not in self._capture:
            self._mark(cycle, "触发时 API 监听未连接")
        self.open_cycles.append(cycle)
        return cycle

    @staticmethod
    def _mark(cycle: Cycle, note: str) -> None:
        cycle.uncertain = True
        if note not in cycle.notes:
            cycle.notes.append(note)

    def _close(self, cycle: Cycle, outcome: Outcome, now_ns: int, note: str | None = None) -> None:
        if note is not None:
            cycle.notes.append(note)
        cycle.outcome = Outcome.INCONCLUSIVE if cycle.uncertain else outcome
        cycle.closed_ns = now_ns
        self.open_cycles.remove(cycle)
        self._closed.append(cycle)
        self.counts[cycle.outcome] += 1
        self._on_close(cycle)

    def on_connect(self, now_ns: int, target: str = "api", *, endpoint: str | None = None) -> None:
        self._capture.add(target)
        if target == "arduino":
            self._gpio = None
        elif endpoint is not None and endpoint != self._endpoint:
            self._closed.clear()
            self._endpoint = endpoint

    def on_disconnect(self, now_ns: int, target: str = "api") -> None:
        self._capture.discard(target)
        if target == "arduino":
            self._gpio = None
        else:
            self._key_down = False
            self._pending_key_ns = None
        for cycle in self.open_cycles[:]:
            if target == "api" or not cycle.unsolicited:
                cycle.disconnected = True
                self._close(cycle, Outcome.INCONCLUSIVE, now_ns, f"周期期间 {target} 断开")
        self._double_pending = None
        self._second_candidate = None

    def on_invalid(self, now_ns: int, note: str = "无效报文") -> None:
        for cycle in self.open_cycles:
            self._mark(cycle, note)

    def finish_open(self, now_ns: int, reason: str = "本轮结束") -> list[Cycle]:
        pending = self.open_cycles[:]
        for cycle in pending:
            self._close(cycle, Outcome.INCONCLUSIVE, now_ns, reason)
        self._double_pending = None
        self._second_candidate = None
        self._pending_key_ns = None
        return pending

    def reset(self, now_ns: int) -> list[Cycle]:
        pending = self.finish_open(now_ns, "计数重置")
        self.counts.clear()
        self.triggers = 0
        self._sequence = 0
        return pending

    def on_trigger(self, sent: int, now_ns: int) -> None:
        self.triggers += 1
        self.tick(now_ns)
        self._second_candidate = None
        cycle = self._new(now_ns, sent=sent, trigger=True)
        for other in self.open_cycles[:-1]:
            if (other.unsolicited and other.ev200_ns is not None and other.ev201_ns is None
                    and 0 <= now_ns - other.ev200_ns <= REORDER_WINDOW_NS):
                note = "收到 200 后才收到板端触发，无法确认对应关系"
                self._mark(other, note)
                self._mark(cycle, note)

    def on_double_first(self, now_ns: int) -> None:
        self.on_trigger(1, now_ns)
        self._double_pending = self.open_cycles[-1]

    def on_double_second(self, now_ns: int) -> None:
        active = self._double_pending
        self._double_pending = None
        if (active is not None and active.outcome is None and active.ev201_ns is None
                and 0 <= now_ns - active.first_ns <= DOUBLE_LINK_WINDOW_NS):
            self.triggers += 1
            active.double_second_ns = now_ns
            self._second_candidate = active
        else:
            self.on_trigger(2, now_ns)

    def _board_cycle(self, sent: int, now_ns: int) -> Cycle | None:
        return next((cycle for cycle in reversed(self.open_cycles)
                     if cycle.trigger_no == sent and cycle.first_ns <= now_ns), None)

    def on_board_no_response(self, sent: int, now_ns: int) -> None:
        cycle = self._board_cycle(sent, now_ns)
        if cycle is not None:
            cycle.board_no_response = True
            if cycle.ack_ns is not None or cycle.board_rad_on:
                cycle.notes.append("板端未观察到 GPIO 确认，API 或串口有响应证据")

    def on_board_cycle_end(self, sent: int, now_ns: int, *, rad_on: bool = False) -> None:
        cycle = self._board_cycle(sent, now_ns)
        if cycle is not None:
            cycle.board_rad_on = rad_on

    def on_board_ready_timeout(self, sent: int, now_ns: int) -> None:
        cycle = self._board_cycle(sent, now_ns)
        if cycle is not None:
            self._mark(cycle, "板端等待 READY 恢复超时")

    def _ack(self, field_name: str, now_ns: int) -> None:
        for cycle in reversed(self.open_cycles):
            if (cycle.trigger_ns is not None and cycle.ev201_ns is None
                    and cycle.trigger_ns <= now_ns):
                if getattr(cycle, field_name) is None:
                    setattr(cycle, field_name, now_ns)
                return

    def on_gpio(self, ready: bool, rad_on: bool, now_ns: int) -> None:
        previous = self._gpio
        self._gpio = (ready, rad_on)
        if previous is None:
            return
        if previous[0] and not ready:
            self._ack("ready_drop_ns", now_ns)
        if previous[1] != rad_on:
            self._ack("rad_on_ns" if rad_on else "rad_off_ns", now_ns)

    def _unique(self, candidates: list[Cycle], detail: str) -> Cycle | None:
        if len(candidates) == 1:
            return candidates[0]
        for candidate in candidates:
            self._mark(candidate, detail)
        return None

    def on_api(self, event_id: int, params: dict, now_ns: int) -> None:
        if event_id == 702:
            self._ack("ev702_ns", now_ns)
        elif event_id == 704:
            self._on_start_key(params.get("keyActivated"), now_ns)
        elif event_id == 200:
            self._on_start(now_ns)
        elif event_id == 201:
            self._on_stop(params, now_ns)
        elif event_id in (202, 203, 204):
            self._ack("activity_ns", now_ns)
        elif event_id == 209:
            active = self._active(now_ns)
            if active is not None:
                active.ev209.append(params)

    def _on_start_key(self, key, now_ns: int) -> None:
        if key == 7:
            self._key_down = False
        elif key == 6 and not self._key_down:
            self._key_down = True
            active = self._active(now_ns)
            if (active is not None and active.ev704_ns is not None
                    and 0 <= now_ns - active.ev704_ns <= DOUBLE_LINK_WINDOW_NS):
                active.second_key_ns = now_ns
            else:
                self._pending_key_ns = now_ns
                self._ack("ev704_ns", now_ns)

    def _on_start(self, now_ns: int) -> None:
        candidates = [c for c in self.open_cycles if c.trigger_ns is not None
                      and c.ev200_ns is None and c.ev201_ns is None
                      and 0 <= now_ns - c.trigger_ns < START_TIMEOUT_NS]
        previous = self._second_candidate
        cycle = self._unique(candidates, "多个板端触发可对应同一条 200")
        if (not candidates and previous is not None and previous.double_second_ns is not None
                and previous.ev201_ns is not None
                and previous.ev201_ns <= now_ns
                and 0 <= now_ns - previous.double_second_ns < START_TIMEOUT_NS):
            cycle = self._new(previous.double_second_ns, sent=2, trigger=True)
            self._second_candidate = None
            if previous.stop_class == "stopped":
                self._mark(cycle, "前一周期报停测，无法确认同一脉冲是否再次启动")
        if cycle is None:
            cycle = self._new(now_ns)
            if candidates:
                self._mark(cycle, "200 与板端触发的对应关系不明确")
        cycle.ev200_ns = now_ns
        key_ns, self._pending_key_ns = self._pending_key_ns, None
        if (key_ns is not None and 0 <= now_ns - key_ns <= REORDER_WINDOW_NS
                and (cycle.trigger_ns is None or cycle.trigger_ns <= key_ns)):
            cycle.ev704_ns = key_ns

    def _active(self, now_ns: int) -> Cycle | None:
        candidates = [c for c in self.open_cycles if c.ev200_ns is not None
                      and c.ev200_ns <= now_ns and c.ev201_ns is None]
        return self._unique(candidates, "多次检测同时等待停测或错误通知")

    def _on_stop(self, params: dict, now_ns: int) -> None:
        cycle = self._active(now_ns)
        if cycle is None:
            waiting = [c for c in self.open_cycles if c.first_ns <= now_ns and c.ev201_ns is None
                       and c.ev200_ns is None]
            cycle = self._unique(waiting, "多个周期可对应同一条 201")
            if cycle is None:
                cycle = self._new(now_ns)
            self._mark(cycle, "收到 201，缺少与其对应的 200")
        cycle.ev201_ns = now_ns
        reason, code = params.get("stopReason"), params.get("stopReasonInt")
        cycle.stop_reason = reason if isinstance(reason, str) else None
        cycle.stop_code = code if type(code) is int else None
        cycle.stop_class = classify_stop(cycle.stop_reason, cycle.stop_code)
        self._resolve(cycle, now_ns)

    def on_result(self, notice: ResultNotice, now_ns: int, *, result_key: str | None = None) -> None:
        if notice.id_status == "duplicate":
            return
        if notice.is_final is None:
            self.on_invalid(now_ns, "206 缺少有效的终态标记")
            return
        cycle = self._pick_result(notice.test_id, result_key, now_ns, notice.is_final)
        if cycle is None:
            if notice.is_final:
                self._orphan_result(notice, result_key, now_ns)
            return
        if cycle.ev200_ns is None:
            cycle.activity_ns = now_ns
            self._mark(cycle, "收到 206，缺少与其对应的 200")
        if notice.id_status in ("conflict", "backward", "repeated_id"):
            self._mark(cycle, "最终结果编号冲突、回退或重复")
        cycle.test_id = notice.test_id or cycle.test_id
        cycle.result_key = result_key or cycle.result_key
        if notice.is_final:
            cycle.final_206_ns = now_ns
            cycle.test_id_status = notice.id_status
            self._resolve(cycle, now_ns)
        else:
            cycle.intermediate_206 += 1

    def _pick_result(self, test_id: str, key: str | None, now_ns: int, final: bool) -> Cycle | None:
        if test_id and any(c.test_id == test_id and (not key or c.result_key == key)
                           for c in self._closed):
            return None
        candidates = [c for c in self.open_cycles if c.first_ns <= now_ns
                      and c.final_206_ns is None]
        started = [c for c in candidates if c.ev200_ns is not None or c.ev201_ns is not None]
        candidates = started or candidates
        exact = [c for c in candidates if key is not None and c.result_key == key
                 and (not c.test_id or c.test_id == test_id)]
        if exact:
            return self._unique(exact, "多个周期报告同一结果时间和编号")
        compatible = [c for c in candidates if (not key or not c.result_key)
                      and (not c.test_id or not test_id or c.test_id == test_id)]
        # An unidentified earlier envelope can consume a final-only result from
        # a newer cycle. Its ambiguity survives closure during the late window.
        unresolved = any(c.ev200_ns is not None and c.final_206_ns is None
                         and c.stop_class not in ("stopped", "proximity")
                         and c.result_key is None and c.closed_ns is not None
                         and 0 <= now_ns - c.closed_ns <= RESULT_TIMEOUT_NS
                         for c in self._closed)
        if unresolved and compatible:
            for c in compatible:
                self._mark(c, "206 可能来自先前缺少结果标识的检测")
            if final:
                return None
        return self._unique(compatible, "结果可能对应多个检测周期")

    def _orphan_result(self, notice: ResultNotice, key: str | None, now_ns: int) -> None:
        cycle = self._new(now_ns)
        cycle.test_id = notice.test_id or None
        cycle.test_id_status = notice.id_status
        cycle.result_key = key
        cycle.final_206_ns = now_ns
        if self.open_cycles[:-1] or any(
                c.result_key is not None and c.result_key == key and c.test_id == cycle.test_id
                for c in self._closed):
            self._close(cycle, Outcome.INCONCLUSIVE, now_ns, "无法将最终 206 与检测周期唯一关联")
        else:
            self._close(cycle, Outcome.UNSOLICITED, now_ns, "最终 206 无对应的 200 或板端触发")

    def _resolve(self, cycle: Cycle, now_ns: int) -> None:
        stop_ns = cycle.ev201_ns
        if stop_ns is not None:
            if cycle.stop_class == "complete":
                if cycle.final_206_ns is not None:
                    outcome = Outcome.UNSOLICITED if cycle.unsolicited else Outcome.NORMAL
                    self._close(cycle, outcome, now_ns)
                elif now_ns - stop_ns >= RESULT_TIMEOUT_NS:
                    self._close(cycle, Outcome.NO_RESULT, now_ns, "正常 201 后未在等待时间内收到最终 206")
            elif cycle.final_206_ns is not None or now_ns - stop_ns >= ABORT_GRACE_NS:
                self._resolve_abnormal(cycle, now_ns)
        elif cycle.ev200_ns is not None:
            if now_ns - cycle.ev200_ns >= TEST_TIMEOUT_NS:
                self._close(cycle, Outcome.INCONCLUSIVE, now_ns, "未收到 201")
        elif cycle.trigger_ns is not None:
            elapsed = now_ns - cycle.trigger_ns
            acknowledged = cycle.ack_ns is not None or cycle.board_rad_on
            if acknowledged and elapsed >= START_TIMEOUT_NS:
                self._close(cycle, Outcome.INCONCLUSIVE, now_ns, "观察到响应信号，但未收到 200")
            elif not acknowledged and elapsed >= ACK_TIMEOUT_NS:
                if {"api", "arduino"} <= self._capture:
                    self._close(cycle, Outcome.NO_RESPONSE, now_ns, "未观察到启动通知或 GPIO 响应")
                else:
                    self._close(cycle, Outcome.INCONCLUSIVE, now_ns, "API 或 Arduino 监听不连续")

    def _resolve_abnormal(self, cycle: Cycle, now_ns: int) -> None:
        if cycle.stop_class == "unknown":
            self._close(cycle, Outcome.UNKNOWN_STOP, now_ns, "需要核对停测原因")
        elif cycle.stop_class == "stopped" and (cycle.double_second_ns is not None or cycle.second_key_ns is not None):
            note = "双 START 停测期间收到最终 206" if cycle.final_206_ns is not None else None
            self._close(cycle, Outcome.DOUBLE_START_STOP, now_ns, note)
        elif cycle.final_206_ns is not None:
            self._close(cycle, Outcome.ABNORMAL_STOP, now_ns, "异常停测期间收到最终 206")
        elif cycle.stop_class == "proximity":
            self._close(cycle, Outcome.EMPTY_SHOT, now_ns, "接近故障且无最终 206，无法确认样品是否在位")
        else:
            self._close(cycle, Outcome.ABNORMAL_STOP, now_ns)

    def tick(self, now_ns: int) -> None:
        for cycle in self.open_cycles[:]:
            self._resolve(cycle, now_ns)
