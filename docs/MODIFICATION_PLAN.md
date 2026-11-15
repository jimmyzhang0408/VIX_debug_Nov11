# 修改计划：让工具能可靠判定"漏检 / 漏发"

> 基线版本：commit `257cb71`（Add DEMO Arduino firmware and bench wiring）
> 编写日期：2026-11-15
> 文中行号均以基线版本为准。改动后行号会变化，请以函数名定位。

---

## 0. 背景与判定口径

### 0.1 测试目的

判断 Vanta iX 是否存在以下两类问题，并把它们与"预期内的不出结果"区分开：

- **漏检**：收到 START，但没有启动检测。
- **漏发**：检测完成并出了读数，但没有发出最终 `206`。

### 0.2 已实测确认的设备行为（2026-11-15）

- **空打**：没有读数时触发接近报警，**testID 不递增**。
- **双 START**：连续收到两个 START，**testID 不递增**。

### 0.3 由此得出的判定口径

| 分类代码 | 中文 | 判定依据 | 是否异常 |
| --- | --- | --- | --- |
| `NORMAL` | 正常 | 收到 201（正常完成），并收到 final 206 | 否 |
| `EMPTY_SHOT` | 空打（接近报警） | 收到 201（接近报警），没有 final 206 | 预期内，单独计数 |
| `DOUBLE_START_STOP` | 双 START 停测 | 第二个 START 到达后收到 201（停测），没有 final 206 | 预期内，单独计数 |
| `NO_RESPONSE` | START 无响应（**漏检**） | TRIGGER 后超时，READY 没有下降、RAD_ON 没有上升、也没有收到 200 | **是** |
| `NO_RESULT` | 测完未发结果（**漏发**） | 201 为正常完成，但超时内没有 final 206 | **是** |
| `TESTID_GAP` | testID 跳号（**漏发**证据） | final 206 的 testID 跳号 | **是** |
| `UNKNOWN_STOP` | 未知停测原因 | 201 的 stopReason 不在已知表里 | 需人工复核 |
| `UNSOLICITED` | 无触发的检测 | 收到 200 或 206，但前面没有对应的 TRIGGER | 记录（手动启动、PC 软件启动等） |
| `INCONCLUSIVE` | 无法判定 | 周期期间发生断线、Reset、工具丢包 | 结论不可用 |

> **关键推论**：因为空打和双 START 都不消耗 testID，所以修完 P0-1 到 P0-4（排除工具自身丢包）之后，**testID 跳号就等于设备漏发**。但空打、双 START、无响应这三类，单靠 testID 完全看不到，必须靠 P0-6 的"触发对账"来识别。

---

## 修改清单总览

| 编号 | 优先级 | 内容 | 涉及文件 |
| --- | --- | --- | --- |
| P0-1 | P0 | 所有报文都写日志，包括非白名单报文和解析失败的报文 | `gui.py`, `transport.py` |
| P0-2 | P0 | 含 NaN / Infinity 的报文不再整条丢弃 | `gui.py`, `core.py` |
| P0-3 | P0 | 增加通知类型 702 / 139 / 701 / 204 的处理 | `device_status.py`, `gui.py` |
| P0-4 | P0 | 重连后保留 testID 链；记录连接事件；本轮断线计数 | `core.py`, `gui.py`, `monitor_view.py` |
| P0-5 | P0 | WebSocket 存活检测：TCP keepalive，显示"最后报文距今" | `transport.py`, `gui.py` |
| P0-6 | P0 | 新增触发对账状态机 `cycle_tracker.py`，以及对应的 GUI 页面 | 新文件 + `gui.py`, `arduino.py` |
| P0-7 | P0 | 固件：START 无响应超时、每周期报告、汇总行 | `.ino`, `arduino.py`, Arduino README |
| P1-1 | P1 | `_poll` 异常保护 | `gui.py` |
| P1-2 | P1 | stopReason 分类表（需要实测数据） | `device_status.py`, `cycle_tracker.py` |
| P1-3 | P1 | dailyId 作为第二条连续性链 | `core.py`, `gui.py` |
| P1-4 | P1 | 日志按运行分文件，扩大轮转上限，生成每轮汇总 | `journal.py`, `gui.py` |
| P1-5 | P1 | 演示模式加入异常场景 | `transport.py` |
| P1-6 | P1 | 单元测试 | 新目录 `tests/` |
| P2-x | P2 | 小问题 | 多处 |

**建议实施顺序**：

1. P1-1 → P0-1 → P0-2 → P0-3 → P0-4 → P0-5。这一组都是小改动，先保证工具自身不丢证据。
2. P0-7 固件改动，然后改 `arduino.py` 的解析。
3. P0-6 对账状态机，同时做 P1-5 演示场景和 P1-6 测试。
4. 拿到实测 201 报文后做 P1-2，其余 P1、P2 最后做。

每一项建议单独提交，方便回滚。

---

## P0-1 所有报文都写日志

### 问题

[gui.py#L490-L497](../gui.py) `_receive_packet()`：

```python
message = json.loads(raw, parse_constant=...)
if not isinstance(message, dict):
    raise ValueError("JSON 顶层不是对象")
event = message.get("id")
if message.get("commandId") != 403 or type(event) is not int or event not in DEVICE_EVENT_IDS:
    return False          # ← 直接丢弃，不写日志
```

- 白名单之外的报文（702、139、701、204、非 403 报文等）**完全不留痕迹**。
- 解析失败时抛出异常，`_poll` 里 L593-L594 只把它写到状态栏，很快就被覆盖。**原始文本不落盘**。
- `ReceivedPacket.raw` 从来没有写进日志。

### 修改

**1）`transport.py`：给每条报文加接收序号**

```python
@dataclass(frozen=True)
class ReceivedPacket:
    raw: str | bytes
    received_ns: int
    received_at: datetime
    rx_no: int = 0          # 新增：本连接内的接收序号，从 1 开始
```

在 `ListenerClient._run()` 的内层循环里维护一个计数器 `rx_no`：每次 `connected` 时清零，每收到一条报文加 1，传给 `ReceivedPacket`。`DemoClient._send()` 也照这样处理。

用途：如果 GUI 侧丢了包，journal 里的 `rxNo` 会出现断号，可以直接证明是工具的问题。

**2）`gui.py`：改写 `_receive_packet()`，按三种情况分别写日志**

```python
def _receive_packet(self, packet) -> bool:
    self._last_packet_ns = packet.received_ns          # 供 P0-5 使用
    base = {
        "received_at": stamp(packet.received_at), "received_ns": packet.received_ns,
        "rxNo": packet.rx_no, "session": self.model.session, "endpoint": self.model.endpoint,
        "source": "demo" if self.mode.get() == "本地演示" else "device",
    }
    # (a) 解码 + 解析，失败时写原始文本
    try:
        raw = packet.raw.decode("utf-8") if isinstance(packet.raw, bytes) else packet.raw
        message, nonfinite = parse_device_json(raw)     # 见 P0-2
        if not isinstance(message, dict):
            raise ValueError("JSON 顶层不是对象")
    except (ValueError, RecursionError) as exc:
        self._invalid_count += 1
        text = packet.raw if isinstance(packet.raw, str) else packet.raw.decode("utf-8", "replace")
        self._submit_log({**base, "kind": "api_invalid", "id": None,
                          "error": str(exc)[:500], "raw": text[:4_000_000],
                          "rawLength": len(packet.raw)})
        self._pending_logs.append(f"... 无效报文（第 {self._invalid_count} 条）：{exc}\n")
        return True
    event = message.get("id")
    # (b) 非 403 或非白名单：完整写日志，204 只记摘要
    if message.get("commandId") != 403 or type(event) is not int or event not in DEVICE_EVENT_IDS:
        self._submit_log({**base, "kind": "api_other", "id": event,
                          "message": summarize_other(message)})
        return False
    # (c) 白名单：保持原有逻辑（entry 里加入 rxNo，以及 P0-2 的 nonfinite 标记）
    ...
```

`summarize_other(message)` 规则：

- `id == 204`（频谱，体积大、频率高）：只记 `{"commandId", "id", "keys": [...], "dataLength": len(params.data)}`。
- 其他报文：原样返回 message。

**3）界面上一直显示"无效报文计数"**

在 API 面板加一个 Label：`无效报文 N 条`。N > 0 时显示为红色。不要只写到会被覆盖的 `self.status`。按 Reset 时清零（同时在日志里记下清零前的值）。

**4）连接事件也写日志**

`_poll` 里的 `connected`、`disconnected`、`stopped`、`arduino_connected`、`arduino_disconnected` 目前**都不写日志**。每个分支都补上 `_submit_log`：

```python
{"kind": "connection", "id": None, "target": "api" | "arduino",
 "event": "connected" | "disconnected" | "stopped",
 "detail": str(payload), "received_at": ..., "received_ns": time.perf_counter_ns()}
```

### 验收

- 用演示模式发一条非白名单报文（比如 `{"commandId":403,"id":702,"params":{}}`），journal 里能看到 `kind=api_other`。
- 发一条不合法的 JSON，journal 里能看到 `kind=api_invalid`，界面计数加 1。

---

## P0-2 NaN / Infinity 报文不再整条丢弃

### 问题

`gui.py` L492 `json.loads(raw, parse_constant=lambda v: throw ValueError)`：只要报文里出现一个 `NaN`，整条 206 就被丢弃，工具会把它算成"设备没发"。

`journal.py` L188、L227 用的是 `allow_nan=False`，所以即使解析通过，写日志时也会失败。

### 修改

新增一个函数，放在 `core.py` 或单独的 `jsonutil.py`：

```python
def parse_device_json(raw: str) -> tuple[Any, bool]:
    """把 NaN/Infinity/-Infinity 解析成字符串，保证后续可以按标准 JSON 写盘。"""
    seen = []
    def constant(name: str) -> str:
        seen.append(name)
        return name                     # 返回字符串 "NaN" / "Infinity" / "-Infinity"
    return json.loads(raw, parse_constant=constant), bool(seen)
```

- `core._scalar()` 会把字符串原样保留，界面上显示 `NaN`，不会被当成 0。
- `ListenerModel.process()` 增加一个参数 `nonfinite: bool`。为 True 时，往 `issues` 里追加 `"报文含非有限数值（NaN/Infinity），已按字符串保存"`。
- 日志 entry 里增加 `"nonFinite": true`。
- **不要**把 journal 改成 `allow_nan=True`，那样写出的文件不是标准 JSON。

### 验收

单元测试：含 `"concentration": NaN` 的 final 206 应该被计数，并导出为 JSON 文件，文件里的值是 `"NaN"`。

---

## P0-3 增加通知类型 702 / 139 / 701 / 204 的处理

API 文档（`Vanta-API-master/Vanta_API_Documents/API-Command-List.md`，通知列表在 L57-L80）里，以下几种对排查漏检有用：

| ID | 名称 | 用途 |
| --- | --- | --- |
| 702 | Trigger Pulled（Vanta iX 上是 START 按下） | **证明设备软件收到了 START**，对账的关键节点 |
| 704 | Key Pressed（`keyActivated` 6=按下，7=释放） | 已经在处理，保留 |
| 139 | Digital IO state changed | 设备侧看到的 IO 变化，可以和 Arduino 观测互相校验 |
| 701 | New Log Messages（`params.messages` 是字符串数组） | 设备内部日志，排查漏发原因最直接的证据 |
| 204 | Spectrum update | 只需要知道"检测在进行"，记摘要即可 |
| 209 | Error During Test | 已经在处理，保留 |

### 修改

**`device_status.py`**

```python
STATUS_NOTIFICATION_IDS = frozenset((100, 139, 200, 201, 202, 203, 207, 209, 701, 702, 704))
```

在 `notification()` 里补上以下分支：

```python
if event == 702:
    return "设备报告 START / 触发"
if event == 139:
    return f"数字 IO 变化 · {log_preview(params)}"
if event == 701:
    messages = params.get("messages")
    if isinstance(messages, list):
        first = bounded_line(str(messages[0])[:300]) if messages else ""
        return f"设备日志 {len(messages)} 行 · {first}"
    return f"设备日志 · {log_preview(params)}"
```

- 701 每一行都要完整写进 journal，`message` 字段里本来就有。界面上只显示第一行和行数。
- 建议在界面上加一个"设备日志"页签，用只读 Text 控件显示 701 的全部行，最多保留 2000 行。
- 204 不加入白名单，按 P0-1 的方式只记摘要。如果对账需要知道"有曝光进行中"，可以让 `cycle_tracker` 也订阅 204 的到达事件。

### 待确认

listener 模式下，GPIO START 是否会产生 702、704、139？需要上台架确认。不管结果如何，对账逻辑都要能处理"收不到这几种通知"的情况。

---

## P0-4 重连后保留 testID 链，并统计断线

### 问题

[core.py#L131-L137](../core.py)：

```python
def begin_session(self, endpoint):
    self.session += 1
    self.endpoint = endpoint
    self.reset_test_id_sequence()     # ← 每次重连都清空 _last_final_number
```

已经用脚本验证过：1、2 之后重连，再收到 5，结果判为 `first`。3、4 丢了，但没有报警。

### 修改

**`core.py`**

```python
def begin_session(self, endpoint: str) -> None:
    self.session += 1
    if endpoint != self.endpoint:
        self.reset_test_id_sequence()          # 换了设备才清链
    elif self._last_final_number is not None:
        self._reconnected = True               # 同一设备重连：保留链，打标记
    self.endpoint = endpoint

def reset_test_id_sequence(self) -> None:
    self._last_final_number = None
    self._reconnected = False
```

在 `_check_test_id()` 里：

```python
elif delta > 1:
    status = "gap_after_reconnect" if self._reconnected else "gap"
...
# 只要处理过一条带有效 ID 的 final（非 conflict），就清除标记
if number is not None:
    self._reconnected = False
```

**`gui.py`**

- `TEST_ID_STATUS_LABELS` 增加 `"gap_after_reconnect": "告警 · 断线期间跳号"`。
- L539 `if notice.id_status == "gap"` 改为 `in ("gap", "gap_after_reconnect")`，告警文字里注明"断线期间"。
- 增加计数器 `self._round_disconnects`：在一轮内（`_count_start_ns` 之后）每收到一次 API 的 `disconnected` 就加 1。界面显示 `本轮断线 N 次`，N > 0 时显示为红色。Reset 时清零。

**`monitor_view.py`** L160、L164：`warning` 和 `gap` 的标签判断里加上 `gap_after_reconnect`。

### 验收

单元测试：`1, 2, begin_session(同 endpoint), 5` 的结果应该是 `gap_after_reconnect`，delta = 3；`begin_session(不同 endpoint), 5` 的结果应该是 `first`。

---

## P0-5 WebSocket 存活检测

### 问题

[transport.py#L131-L156](../transport.py) 没有任何心跳，只是用 0.5 s 超时反复 `recv()`。如果网线被拔掉，或者交换机掉电，TCP 可能几分钟甚至更久都察觉不到。在这段时间里，界面一直显示"已连接"，设备发出的结果全部丢失，看起来就像设备漏发。

### 修改

**1）开启 TCP keepalive（必做，不依赖设备支持）**

```python
import socket, sys

ws.connect(self.endpoint, timeout=3.0, http_no_proxy=["*"],
           sockopt=((socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),))
sock = ws.sock
if sys.platform == "win32":
    # (开启, 空闲 5000 ms 后开始探测, 每 1000 ms 探测一次)。Windows 默认重试 10 次，约 15 s 判定断线
    sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 5000, 1000))
else:
    for name, value in (("TCP_KEEPIDLE", 5), ("TCP_KEEPINTVL", 1), ("TCP_KEEPCNT", 5)):
        if hasattr(socket, name):
            sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, name), value)
```

TCP 判定断线后，`recv()` 会抛出异常，代码会进入现有的 `disconnected` 和重连流程。

**2）WebSocket ping（可选，需要先确认设备会回 pong）**

ping 是协议层的控制帧，不是设备命令。但要先用 Wireshark 确认 Vanta 会回 pong，再启用。实现方式：

- 在内层循环里每 5 s 调用一次 `ws.ping()`。
- 把 `ws.recv()` 换成 `ws.recv_data(control_frame=True)`，这样能拿到 opcode。收到 `ABNF.OPCODE_PONG` 时更新 `last_pong`。
- 如果超过 15 s 没有收到 pong，主动 `raise ConnectionError("心跳超时")`。

默认关闭，用常量 `WS_PING_ENABLED = False` 控制。

**3）`gui.py`：显示"最后报文距今"**

- 每收到一条报文，更新 `self._last_packet_ns`（P0-1 已加）。
- 在 `refresh()` 里，连接状态下显示 `最后报文 X s 前`。
- 如果对账器里有未结束的周期（P0-6），并且超过 `STALE_WITH_PENDING_S = 30` 秒没有收到任何报文，标红显示：`有进行中的检测，但 30 s 没有收到任何报文`。

### 待确认

设备空闲时会不会周期性发送 100 SystemStatus？如果会，说明它可以当作天然心跳，可以把阈值调低。

### 验收

连上设备后拔掉网线，20 s 内界面应该变成"已断开"，并开始重连；journal 里有 `kind=connection, event=disconnected`。

---

## P0-6 触发对账状态机（核心改动）

### 6.1 新文件 `cycle_tracker.py`

这个模块只放纯逻辑，不依赖 Tk，方便写单元测试。所有时间都用 PC 的 `perf_counter_ns`。

```python
from dataclasses import dataclass, field
from enum import Enum

class Outcome(str, Enum):
    NORMAL = "NORMAL"
    EMPTY_SHOT = "EMPTY_SHOT"
    DOUBLE_START_STOP = "DOUBLE_START_STOP"
    NO_RESPONSE = "NO_RESPONSE"
    NO_RESULT = "NO_RESULT"
    UNKNOWN_STOP = "UNKNOWN_STOP"
    UNSOLICITED = "UNSOLICITED"
    INCONCLUSIVE = "INCONCLUSIVE"

# 超时参数（单位 ns）。上台架后按实测分布调整，取实测最大值的 3 倍
ACK_TIMEOUT_NS        = 3_000_000_000     # TRIGGER 之后，READY↓、RAD_ON↑、702、200 至少出现一个
START_TIMEOUT_NS      = 5_000_000_000     # TRIGGER 之后必须收到 200
TEST_TIMEOUT_NS       = 180_000_000_000   # 200 之后必须收到 201
RESULT_TIMEOUT_NS     = 5_000_000_000     # 201（正常完成）之后必须收到 final 206
ABORT_GRACE_NS        = 3_000_000_000     # 201（中止）之后等 206 的宽限期，超时就按中止结案
DOUBLE_LINK_WINDOW_NS = 2_000_000_000     # 第二个 START 与第一个 START 关联的时间窗口

@dataclass
class Cycle:
    no: int                              # 本轮周期序号，从 1 开始
    trigger_no: int | None               # Arduino 的 sent 值；UNSOLICITED 时为 None
    trigger_ns: int | None
    double_second_ns: int | None = None  # 双 START 第二个脉冲的时间
    ready_drop_ns: int | None = None
    rad_on_ns: int | None = None
    rad_off_ns: int | None = None
    ev702_ns: int | None = None
    ev200_ns: int | None = None
    ev201_ns: int | None = None
    stop_reason: str | None = None
    stop_code: int | None = None
    stop_class: str | None = None        # complete / proximity / stopped / unknown，见 P1-2
    ev209: list = field(default_factory=list)
    intermediate_206: int = 0
    final_206_ns: int | None = None
    test_id: str | None = None
    test_id_status: str | None = None
    disconnected: bool = False
    board_no_response: bool = False      # 来自固件的 CTRL NO_RESPONSE
    outcome: Outcome | None = None
    closed_ns: int | None = None
```

### 6.2 输入事件接口

```python
class CycleTracker:
    def __init__(self, on_close: Callable[[Cycle], None]): ...
    def reset(self, now_ns) -> list[Cycle]      # 把未结束的周期按 INCONCLUSIVE 结案，返回列表，然后清空计数
    # Arduino
    def on_trigger(self, sent: int, now_ns)     # CTRL TRIGGER sent=n
    def on_double_first(self, now_ns)           # CTRL DOUBLE_FIRST
    def on_double_second(self, now_ns)          # CTRL DOUBLE_SECOND
    def on_board_no_response(self, sent, now_ns)# CTRL NO_RESPONSE（P0-7）
    def on_gpio(self, ready: bool, rad_on: bool, now_ns)   # 来自 ArduinoReport 的 READY / RAD_ON 跳变
    # API
    def on_api(self, event_id: int, params: dict, now_ns)  # 702 / 704(6) / 200 / 201 / 209
    def on_result(self, notice: ResultNotice, now_ns)      # 206，包含中间结果和最终结果
    def on_disconnect(self, now_ns)
    # 定时
    def tick(self, now_ns)                      # 每次 _poll 都调用，处理超时
    # 统计
    counts: dict[Outcome, int]; triggers: int; open_cycles: list[Cycle]
```

### 6.3 关联规则

1. **TRIGGER**：新建一个 Cycle（带 `trigger_no` 和 `trigger_ns`），放入 `open` 列表。
2. **DOUBLE_FIRST**：和 TRIGGER 一样新建 Cycle，同时记下 `self._double_pending = cycle`。
3. **DOUBLE_SECOND**：如果 `_double_pending` 还没结案，并且时间在窗口内，就写入它的 `double_second_ns`，**不新建周期**。如果第一个周期已经结案，说明设备已经测完并恢复了就绪，就为第二个脉冲新建一个 Cycle（第二个脉冲可能启动了一轮新检测）。
4. **READY 下降 / RAD_ON 上升 / 702 / 704(keyActivated=6)**：写入最早一个还没有对应字段、且已经有 TRIGGER 的 open 周期。
5. **200**：绑定到最早一个还没收到 200 的 open 周期。如果找不到，就新建一个 `trigger_no=None` 的周期，最终结果标为 `UNSOLICITED`（但仍按后续事件判断有没有漏发，见第 9 条）。
6. **201**：绑定到"已收到 200、还没收到 201"的周期中最早的一个。如果找不到，就绑定到最早的 open 周期，并在 journal 里记一条 `"201 无对应 200"`。写入 `stop_reason` 和 `stop_code`，然后用 P1-2 的表得出 `stop_class`。
7. **206（中间结果）**：对应周期的 `intermediate_206` 加 1。
8. **206（最终结果，非 duplicate / conflict）**：
   - 优先绑定"已收到 201、还没收到 final"的周期，其次绑定"已收到 200、还没收到 final"的周期（兼容 final 206 先于 201 到达的情况）。
   - 如果 `test_id_status` 是 `gap` 或 `gap_after_reconnect`，在 journal 里**另外**记一条 `kind=anomaly, type=TESTID_GAP`（包含 previous、current、skipped），计数 `TESTID_GAP += skipped`。
9. **结案（在 `tick()` 和事件处理时都要检查）**：

| 条件 | 结果 |
| --- | --- |
| 周期期间发生过 `on_disconnect` | `INCONCLUSIVE`（优先级最高） |
| 收到 final 206，并且收到 201（或已经过了 201 的宽限期） | `NORMAL`（如果 trigger 为 None，则为 `UNSOLICITED`） |
| `stop_class == "proximity"`，201 之后过了 `ABORT_GRACE_NS` 仍没有 final | `EMPTY_SHOT` |
| `stop_class == "stopped"` 并且有 `double_second_ns`，过了宽限期仍没有 final | `DOUBLE_START_STOP` |
| `stop_class == "complete"`，过了 `RESULT_TIMEOUT_NS` 仍没有 final | **`NO_RESULT`** |
| `stop_class == "unknown"`，过了宽限期仍没有 final | `UNKNOWN_STOP` |
| 有 TRIGGER，过了 `ACK_TIMEOUT_NS` 仍没有 READY↓、RAD_ON↑、702、200；或者收到固件的 `NO_RESPONSE` | **`NO_RESPONSE`** |
| 有 ack，但过了 `START_TIMEOUT_NS` 仍没有 200 | `NO_RESPONSE`，标注 `"有 GPIO 响应但无 200"` |
| 收到 200，但过了 `TEST_TIMEOUT_NS` 仍没有 201 | `NO_RESULT`，标注 `"无 201"` |

   注意：收到 final 206 但 stop_class 是 proximity 或 stopped，这种情况和"空打不出结果"的实测结论矛盾，应标为 `UNKNOWN_STOP` 并记下来。

10. **没有 Arduino 的情况**（只接 WebSocket）：没有 TRIGGER，所有周期都从 200 开始，都标为 `UNSOLICITED`，再按 201 和 206 判断有没有漏发。`NO_RESPONSE` 检测不了，界面上要注明"未接 Arduino，无法检测漏检"。

### 6.4 结案输出

`on_close(cycle)` 回调由 GUI 写入 journal：

```json
{"kind":"cycle","id":null,"cycleNo":12,"triggerNo":12,"outcome":"NO_RESULT",
 "testID":null,"stopReason":"Test Complete","stopCode":0,"stopClass":"complete",
 "t_trigger_to_ack_ms":85,"t_trigger_to_200_ms":140,"t_200_to_201_ms":10230,
 "t_201_to_final_ms":null,"intermediate206":3,"ev209":[],"doubleSecond":false,
 "disconnected":false,"notes":["201 后 5000 ms 未收到 final 206"]}
```

时间差字段统一用 `t_<from>_to_<to>_ms`，缺失时写 null。**这些字段同时用来统计实测分布，再据此调整 6.1 里的超时参数。**

### 6.5 GUI 改动（`gui.py`）

1. 新增页签 **"触发对账"**：
   - 上方一行计数：`触发 N · 正常 · 空打 · 双START停测 · 无响应(漏检) · 漏发 · testID跳号 · 未知 · 无触发 · 无法判定 · 进行中`。漏检、漏发、跳号这几项只要大于 0 就显示为红色粗体。
   - 下方是 Treeview，每个周期一行。列：`周期号 | 触发号 | testID | 结果 | stopReason | 触发→200 ms | 200→201 ms | 201→206 ms | 备注`。异常行用红色背景。
2. Header 区域在"最终结果数"旁边加一个"**异常数**"大字计数（漏检 + 漏发 + 跳号）。
3. 接入点：
   - `_receive_arduino_line()` 拿到 `control` 后，按 `control.event` 分发：`TRIGGER` → `on_trigger`，`DOUBLE_FIRST`、`DOUBLE_SECOND`、`NO_RESPONSE` → 对应方法。
   - `_receive_arduino()` 检测 READY / RAD_ON 跳变 → `on_gpio`。
   - `_receive_packet()` 在白名单分支里调用 `on_api` 或 `on_result`。
   - `_poll()` 里 `disconnected` → `on_disconnect`。
   - `_poll()` 每次 tick 末尾调用 `tracker.tick(time.perf_counter_ns())`。
   - `reset_result_count()` → `tracker.reset()`。
4. **时间戳**：`ArduinoLine` 现在只有 `at: datetime`，需要增加 `received_ns: int` 字段（在 `arduino.py` 的 `_emit_line()` 里用 `time.perf_counter_ns()` 赋值）。这样 CTRL 行和 WebSocket 报文用的是同一个时钟。

---

## P0-7 固件：START 无响应超时与每周期报告

文件：`arduino/Vanta_iX_PLC_Direct_5V/Vanta_iX_PLC_Direct_5V.ino`

### 问题

L278-L288 的 `WaitReturn` 要等到 READY 撤销一次才继续，**没有超时**。如果设备不响应这次 START（也就是要抓的漏检），`START 100` 会永远卡住，串口上也没有专门的输出。

### 修改

**1）新增常量和计数**

```cpp
constexpr uint32_t kStartAckTimeoutMs   = 3000;    // 脉冲开始后，READY 必须下降或 RAD_ON 必须上升
constexpr uint32_t kReadyReturnTimeoutMs = 300000; // 收到 ack 后，READY 必须在这个时间内恢复
volatile uint32_t radOnRises = 0;                  // 在 ISR 里统计 RAD_ON 上升沿
```

在 `captureLevel()` 里，`readyDrops` 加 1 的位置旁边加上：

```cpp
if (signal == kRadOn && active) { ++radOnRises; }
```

`InputSample` 增加 `radOnRises` 字段，在 `sampleInputs()` 里读取。

**2）扩展 `TriggerCycle`**

```cpp
uint32_t pulseAtMs = 0;           // 本次脉冲开始的时间
uint32_t radOnRisesAtStart = 0;
bool acked = false;               // 本次脉冲后看到过 READY 下降或 RAD_ON 上升
bool sawRadOn = false;
uint32_t noResponse = 0;          // 本批次无响应次数
uint32_t radOnCycles = 0;         // 本批次实际出束次数
```

**3）HoldReady → Pulse**（原 L259-L269）

```cpp
if (!assertStart(sample)) {
  cycle.phase = CyclePhase::WaitReady;
  printCycle("START_BLOCKED");          // 新增：原来这里静默返回
  break;
}
cycle.phaseSince = millis();
cycle.pulseAtMs = cycle.phaseSince;
cycle.readyDropsAtStart = sample.readyDrops;
cycle.radOnRisesAtStart = sample.radOnRises;
cycle.acked = false;
cycle.sawRadOn = false;
```

**4）在 Pulse 和 WaitReturn 中检测 ack 和超时**（替换原 L271-L288）

```cpp
case CyclePhase::Pulse:
case CyclePhase::WaitReturn: {
  if (sample.readyDrops != cycle.readyDropsAtStart) cycle.acked = true;
  if (sample.radOnRises != cycle.radOnRisesAtStart) { cycle.acked = true; cycle.sawRadOn = true; }

  if (cycle.phase == CyclePhase::Pulse) {
    if (sample.timeMs - cycle.phaseSince >= kStartPulseMs) {
      releaseStart();
      cycle.phase = CyclePhase::WaitReturn;
      printCycle("WAIT_READY_RETURN");
    }
    break;
  }
  const uint32_t sincePulse = sample.timeMs - cycle.pulseAtMs;
  if (!cycle.acked && sincePulse >= kStartAckTimeoutMs) {
    ++cycle.noResponse;
    printCycleResult("NO_RESPONSE", sincePulse);
    finishOrNext(sample);               // 按"继续"策略进入下一次，见第 5 点
    break;
  }
  if (cycle.acked && sincePulse >= kReadyReturnTimeoutMs) {
    printCycleResult("READY_RETURN_TIMEOUT", sincePulse);
    endCycle("STOPPED");
    break;
  }
  if (cycle.acked && eligible) {        // READY 已经恢复：本周期结束
    if (cycle.sawRadOn) ++cycle.radOnCycles;
    printCycleResult("CYCLE_END", sincePulse);
    finishOrNext(sample);
  }
  break;
}
```

**5）辅助函数**

```cpp
// 输出示例：CTRL CYCLE_END sent=3 total=100 rad_on=1 ms=12345
void printCycleResult(const char* event, uint32_t ms) {
  char line[112];
  const int n = snprintf(line, sizeof(line), "CTRL %s sent=%lu total=%lu rad_on=%d ms=%lu\r\n",
      event, (unsigned long)cycle.sent, (unsigned long)cycle.requested,
      cycle.sawRadOn ? 1 : 0, (unsigned long)ms);
  if (n > 0 && (size_t)n < sizeof(line)) Serial.write((uint8_t*)line, n);
}

void finishOrNext(const InputSample& sample) {
  if (cycle.sent >= cycle.requested) {
    printSummary();
    endCycle("DONE");
  } else if ((sample.active & (kReady | kRadOn | kFault)) == kReady) {
    beginReadyHold(sample);
  } else {
    cycle.phase = CyclePhase::WaitReady;
    printCycle("WAIT_READY");
  }
}

// 输出示例：CTRL SUMMARY sent=100 total=100 no_response=2 rad_on_cycles=97
void printSummary() { /* 用 snprintf 输出，格式同上 */ }
```

`STOP` 命令（`handleCommand` 里的 `endCycle("STOPPED")`）在结束前也要调用一次 `printSummary()`。

**策略说明**：遇到 NO_RESPONSE 时默认**继续**下一次，这样一批 100 次可以完整跑完，最后再统计。如果需要"遇到无响应就停"，可以增加命令 `START <n> HALT`，用 `cycle.haltOnNoResponse` 控制。注意这会改变 `handleCommand` 的参数解析：目前第三个词只允许出现在 `DOUBLE START <gap>` 中。

**6）DOUBLE START**：`updateDoubleStart()` 的 `DOUBLE_DONE` 之后，不做 ack 检测。由 PC 端对账器根据 201 判断结果。

**7）串口阻塞说明**

UNO R4 WiFi 的 USB 口经过 ESP32-S3 桥接，`Serial` 实际上是一路 115200 波特的 UART。TX 缓冲满时，`Serial.write` 会阻塞到缓冲有空位为止，大约 87 µs/字节，一行 80 字节约 7 ms。连续多行输出时，脉冲释放可能被推迟几十毫秒。

**建议**：
- 用示波器或逻辑分析仪实测 D4 的低电平宽度，确认在 100 ms ± 20 ms 以内。
- 可选：在 `printStatus()` 和 `printCycle()` 前检查 `Serial.availableForWrite()`。空间不够时丢弃 STATE 心跳行（不要丢 CTRL 行），并计数 `serialDropped`，在下一行里输出。

### `arduino.py` 解析改动

L19 的 `CONTROL_PROGRESS` 正则用的是 fullmatch，新格式带额外字段，会匹配失败，结果被当成普通文本。改为：

```python
CONTROL_PROGRESS = re.compile(
    r"CTRL ([A-Z_]+) sent=([0-9]{1,10}) total=([0-9]{1,10})((?: [a-z_]+=[0-9]{1,10})*)")

@dataclass(frozen=True)
class ArduinoControl:
    event: str
    sent: int | None = None
    total: int | None = None
    error: str | None = None
    extra: dict[str, int] = field(default_factory=dict)   # rad_on / ms / no_response / rad_on_cycles

def parse_arduino_control(text):
    m = CONTROL_PROGRESS.fullmatch(text)
    if m:
        event, s, t, rest = m.groups()
        extra = {k: int(v) for k, v in (p.split("=") for p in rest.split())}
        ...
```

同时在 `gui.py` 的 `CONTROL_LABELS` 里补上：

```python
"DOUBLE_FIRST": "双 START 第一脉冲", "DOUBLE_GAP": "双 START 间隔",
"DOUBLE_SECOND": "双 START 第二脉冲", "DOUBLE_DONE": "双 START 完成",
"START_BLOCKED": "触发条件变化，重新等待", "NO_RESPONSE": "告警 · START 无响应",
"CYCLE_END": "周期结束", "READY_RETURN_TIMEOUT": "告警 · READY 未恢复",
"SUMMARY": "批次汇总",
```

收到 `SUMMARY` 时，在状态事件里打印一行汇总，内容包括板端的 sent、no_response、rad_on_cycles，以及 PC 端对账器的统计，方便直接对比。

### Arduino README 更新

在 `arduino/Vanta_iX_PLC_Direct_5V/README.md` 的"串口操作"一节，补充 `NO_RESPONSE`、`CYCLE_END`、`SUMMARY`、`START_BLOCKED`、`READY_RETURN_TIMEOUT` 的含义，并在"先做单板检查"里加一项：

> 发送 `START`，在 D2 接 GND 的状态下等到 `CTRL TRIGGER` 出现。之后**不要**断开 D2。约 3 秒后，串口应显示 `CTRL NO_RESPONSE sent=1 total=1 rad_on=0 ms=3000`，紧接着显示 `CTRL SUMMARY ...` 和 `CTRL DONE`。

---

## P1-1 `_poll` 异常保护

[gui.py#L560-L650](../gui.py) 里，`self._poll_id = self.window.after(30, self._poll)` 写在函数末尾。只要中间出现一次未捕获的异常，事件循环就**永久停止**。EXE 是 `console=False`，traceback 看不到。

### 修改

```python
def _poll(self):
    try:
        self._poll_body()                    # 把原来的函数体整体挪到这里
    except Exception as exc:                 # noqa: BLE001
        self._poll_errors += 1
        detail = traceback.format_exc()
        self.status.set(f"内部错误（第 {self._poll_errors} 次），已记录：{exc}")
        self._submit_log({"kind": "internal_error", "id": None,
                          "received_at": stamp(datetime.now().astimezone()), "traceback": detail})
    finally:
        # 窗口销毁时，_on_destroy 会取消 after，所以这里无条件重新调度即可（与原逻辑一致）
        self._poll_id = self.window.after(30, self._poll)
```

`_submit_log` 本身如果再次抛出异常，会被 finally 之外的 Tk 吞掉。可以把它包在 `try/except Exception: pass` 里，保证 finally 一定会执行。

另外，`_receive_packet` 外层目前只捕获 `ValueError`、`TypeError`、`RecursionError`。可以保持不变，由上面的兜底处理其余异常。

---

## P1-2 stopReason 分类表

### 需要的实测数据

请在台架上分别触发**空打一次**、**双 START 一次**、**手动 STOP 一次**（如果有），从 journal 里把 `201` 的完整报文复制出来。重点看 `stopReason` 和 `stopReasonInt`，同时确认这几种情况下：

- 有没有 `209`
- 有没有中间 `206`
- 有没有 702、704、139

### 修改

在 `device_status.py` 里新增分类表，`cycle_tracker.py` 引用它：

```python
# key 统一转成小写并去掉首尾空格。值为 complete / proximity / stopped
STOP_REASON_CLASS = {
    "test complete": "complete",
    "complete": "complete",
    "time elapsed": "complete",
    # TODO(实测后填写)：空打 / 接近报警
    # "proximity ...": "proximity",
    # TODO(实测后填写)：双 START / 用户停止
    # "user stopped": "stopped",
}
STOP_CODE_CLASS = {
    0: "complete",
    # TODO(实测后填写)
}

def classify_stop(reason: str | None, code: int | None) -> str:
    if isinstance(code, int) and code in STOP_CODE_CLASS:
        return STOP_CODE_CLASS[code]
    if isinstance(reason, str):
        return STOP_REASON_CLASS.get(reason.strip().casefold(), "unknown")
    return "unknown"
```

`STOP_REASONS`（中文显示用）也同步补上对应条目。

**原则**：遇到没见过的 stopReason，**一律归为 unknown**，交给人工复核。不要猜。

---

## P1-3 dailyId 作为第二条连续性链

API 文档里 `analysis.dailyId` 是整数（示例里是 -1）。目前代码把 `tidName` 当成每日编号（[core.py#L213](../core.py)），没有检查 `dailyId`。

### 修改

1. 先在设备上确认 `dailyId` 和 `tidName` 的实际含义：是否每天从 1 开始？空打时是否递增？
2. 如果 `dailyId` 有意义：
   - 给 `Measurement` 增加 `daily_id_num: int | None`。
   - 在 `ListenerModel` 里另外维护一条 `_last_daily_number`，状态值与 testID 相同。如果日期变了、并且新值为 1，标为 `daily_reset`，不算告警。
   - CSV 和历史表各加一列 `dailyId`。
   - testID 和 dailyId 跳号的结果不一致时，在备注里写明。

---

## P1-4 日志按运行分文件，并生成每轮汇总

### 问题

`journal.py` L157-L159 的轮转上限是 `maxBytes=20_000_000, backupCount=5`，总共只有 100 MB。206 报文里可能带有 `olympusResult` 或图像信息，过夜运行时，早期证据会被覆盖。另外，所有运行都写在同一个 `listener_ids.jsonl` 里，不方便按次分析。

### 修改

1. `gui.py` L120-L125：日志路径改为 `ROOT / "runtime" / "logs" / f"listener_{datetime.now():%Y%m%d_%H%M%S}.jsonl"`，每次启动程序都新建一个文件。
2. `journal.py`：改为 `maxBytes=200_000_000, backupCount=50`，并作为构造参数暴露出来。
3. 每次按 **Reset 计数**、断开连接、关闭程序时，把对账器的统计写成 `runtime/summaries/summary_<时间>.json`，并在 journal 里记一条 `kind=round_summary`。内容包括：

```json
{"start":"...","end":"...","triggers":100,"NORMAL":95,"EMPTY_SHOT":2,
 "DOUBLE_START_STOP":0,"NO_RESPONSE":1,"NO_RESULT":1,"TESTID_GAP":1,
 "UNKNOWN_STOP":1,"UNSOLICITED":0,"INCONCLUSIVE":0,
 "disconnects":0,"invalidPackets":0,"journalDropped":0,"journalFailures":0,
 "board":{"sent":100,"no_response":1,"rad_on_cycles":98},
 "testIdRange":{"first":"1201","last":"1296"},
 "timing_ms":{"t_201_to_final":{"min":..,"p50":..,"max":..}}}
```

4. 汇总里要包含 `AsyncJournal.dropped_count` 和 `failure_count`。只要其中任何一个大于 0，这一轮的结论就不可用，界面要明确提示。

---

## P1-5 演示模式加入异常场景

`transport.py` 的 `DemoClient._run()` 目前只会模拟正常周期。建议按固定顺序轮流模拟以下场景，这样不接设备也能验证 GUI 和对账器：

| 第 n 个周期 (n % 6) | 场景 | 模拟方式 |
| --- | --- | --- |
| 0 | 正常 | 和现在一样 |
| 1 | 空打 | 200 → 202 → 201(stopReason=`<空打值，实测后填写>`)，没有 206，testID 不变 |
| 2 | 漏发 | 200 → 201(Test Complete)，没有 final 206，**testID +1**（下一条 final 就会出现跳号） |
| 3 | 无响应 | 发 TRIGGER，没有 READY 跳变，也没有 200 |
| 4 | 双 START | DOUBLE_FIRST → 200 → DOUBLE_SECOND → 201(stopped)，没有 206 |
| 5 | NaN 结果 | 正常，但 final 206 里有一个元素是 `NaN`（用原始字符串拼出来） |

演示时也要发出 `arduino_line`，内容是 CTRL 文本（`CTRL TRIGGER sent=n total=0` 等），这样会走到和真机相同的解析路径。

**演示的验收结果**：每 6 个周期，对账页显示正常 2、空打 1、漏发 1、无响应 1、双 START 1、跳号 1。正常 2 次是因为 NaN 那次也算正常。

---

## P1-6 单元测试

新建 `tests/` 目录，使用标准库 `unittest`，不需要新增依赖。运行命令：`python -m unittest discover -s tests -v`。

| 文件 | 测试点 |
| --- | --- |
| `tests/test_core.py` | first / consecutive / gap / backward / repeated_id / duplicate / conflict / missing_id；重连后跳号为 `gap_after_reconnect`；换 endpoint 后为 first；含 NaN 的 final 206 被计数且有 issue |
| `tests/test_arduino_parse.py` | 旧格式 CTRL 行；新格式带 extra 的 CTRL 行；`CTRL ERROR X`；状态行 `t_ms=... event=...`；非法行返回 None |
| `tests/test_cycle_tracker.py` | 对第 0 节表格里的每个结果各写一个场景；final 206 先于 201 到达；双 START 第二脉冲在第一个周期已结案后到达；周期期间断线时为 INCONCLUSIVE；Reset 时进行中的周期为 INCONCLUSIVE；没有 Arduino 时的 UNSOLICITED |
| `tests/test_journal.py` | `_export_final` 的 saved / already_saved / conflict / invalid_id；含 NaN 的 entry 能写入（转成字符串之后） |

另外建议在 README 里加一节"开发者测试"，写明上面的运行命令。

---

## P2 小问题

| # | 位置 | 问题 | 修改 |
| --- | --- | --- | --- |
| P2-1 | `gui.py` L302 | 命令提示里没有 `DOUBLE START` | 改为 `START [次数] · DOUBLE START [1/0.5] · STOP · CLEAR FAULT` |
| P2-2 | `arduino.py` L145 | 提示里提到 `run_gui.bat`，但仓库里没有这个文件 | 改为 `请运行 .\.venv\Scripts\python.exe -m pip install -r requirements.txt` |
| P2-3 | `gui.py` L782-L791 `clear()` | 清空时会新建 `ListenerModel()`，session 和 endpoint 都被清零 | 同时重置对账器；在 journal 里记一条 `kind=ui_clear` |
| P2-4 | `core.py` L220 | `_seen` 最多保留 4096 条，超过后会淘汰旧的，过夜长跑时可能把旧的重复报文当成新结果 | 调大到 100000，或者按 testID 数值做区间判断 |
| P2-5 | `.ino` L367-L380 | `requestDoubleStart` 不检查故障锁（README 写明这是有意的） | 保持不变，但在 GUI 上发送 `DOUBLE START` 前弹窗确认 |
| P2-6 | `README.md` | 链接后面有一个多余的 `\r` | 删除 |
| P2-7 | `requirements.txt` | 运行依赖和打包依赖混在一起 | 可以拆成 `requirements.txt`（websocket-client、pyserial）和 `requirements-build.txt`（pyinstaller 等） |
| P2-8 | `gui.py` L26-L29 | 默认 IP、端口、COM 口写死在代码里 | 可选：保存到 `runtime/settings.json`，下次启动时恢复上次的值 |

---

## 台架验收清单（全部改完后执行）

| # | 操作 | 期望结果 |
| --- | --- | --- |
| 1 | 演示模式运行 10 分钟 | 对账统计符合 P1-5 的比例；无效报文为 0；日志没有丢失或写入失败 |
| 2 | 真机：Reset 计数，然后 `START 20`，样品正常放置 | 正常 20；板端 SUMMARY 为 sent=20、no_response=0、rad_on_cycles=20；testID 连续 |
| 3 | 真机：不放样品，`START 5`（空打） | 空打 5；testID 不变；没有漏发告警 |
| 4 | 真机：`DOUBLE START 1`，以及 `DOUBLE START 0.5` | 双 START 停测（或者第二脉冲启动了新检测，此时为正常），不产生漏发误报 |
| 5 | 拔掉 Vanta 的 START 线，`START 3` | 无响应 3；板端 no_response=3；批次能跑完，不会卡住 |
| 6 | 检测进行中拔掉网线，约 20 s 后插回 | 界面在 20 s 内显示已断开；该周期为无法判定；重连后如果有跳号，显示为"断线期间跳号" |
| 7 | 长跑：`START 500` 或者过夜运行 | 日志完整（rxNo 没有断号）；生成汇总文件；漏检 + 漏发 = 设备真实异常数 |
| 8 | 用示波器测 D4 | 低电平宽度为 100 ms ± 20 ms |

---

## 待确认事项（上台架时一并记录）

1. 空打、双 START、手动停止时，`201` 的 `stopReason` 和 `stopReasonInt` 的真实值（P1-2）。
2. 上面三种情况下，有没有 `209`、有没有中间 `206`、有没有 702 / 704 / 139（P0-3）。
3. 正常检测时，`201` 和 final `206` 哪个先到达，时间差的分布如何（据此设置 `RESULT_TIMEOUT_NS`）。
4. START 脉冲之后，READY 下降、RAD_ON 上升、200 分别延迟多久（据此设置 `ACK_TIMEOUT_NS` 和固件的 `kStartAckTimeoutMs`）。
5. 设备空闲时会不会周期性发送 100；会不会回应 WebSocket ping（P0-5）。
6. `dailyId` 和 `tidName` 的含义（P1-3）。
7. 重复检测（`repeatTestTotal > 1`）、多方法检测时，每次检测会发出几个 final 206，testID 如何递增。
