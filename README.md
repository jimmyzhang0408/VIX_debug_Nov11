# Vanta iX 实时监控

此版本使用 Tk 界面，显示 Vanta iX 的 WebSocket 通知、Arduino 串口状态和元素结果。打开“触发对账”页查看每次板端触发对应的检测开始、停测和最终 `206`。

## 在 Windows 上运行

使用带 Tk 的 Python 3.12 x64。在仓库根目录打开 PowerShell。运行以下命令。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

连接设备前，请在界面中输入 Vanta iX 的 IP、端口和 Arduino 串口。只监听 WebSocket 时，请将串口留空。运行本地演示时，使用以下命令。演示数据来自程序本身。

```powershell
.\.venv\Scripts\python.exe app.py --demo
```

## 检查漏检和结果缺失

| 记录 | 判定依据 |
| --- | --- |
| 未见设备响应 | 板端记录已发脉冲，等待 3 秒后仍无设备启动通知、接收 START 或 GPIO 响应的证据。 |
| 正常停测 · 未收终态 | 收到正常停止通知 `201`，等待 5 秒后仍未收到可归入该周期的最终 `206`。 |
| 接近停测 · 无终态 | 收到 `Proximity Failure`，且无最终结果。用现场记录确认样品是否在位。 |
| 异常停测、双 START 停测 | 按停测原因记录。收到最终结果时一并保留。 |
| 无法判定 | 周期内断线、记录缺失、事件无法配对，或在周期结束前重置或关闭程序。 |

`testID` 跳号单独显示。重连后的跳号会带断线标记。`dailyId` 也会在无最终结果时递增，因此只作核对线索。同一次检测可能产生多个告警。需要确认设备是否漏发时，请对照设备数据库或发送端记录。

每次启动程序会在 `runtime/logs` 创建日志。日志保存每条收到的 WebSocket 数据消息的接收序号，`204` 频谱只保存摘要。日志也记录解码失败、断线、对账和导出状态。按 Reset、断开或退出时，在 `runtime/summaries` 保存汇总。轮转阈值为约 200 MB，单次运行最多保留 50 份轮转文件。每次运行的日志各自保留。

## Arduino 固件与接线

DEMO 台架使用 Arduino UNO R4 WiFi。固件和五根线的接线表在同一目录。先阅读接线条件，再连接设备。 [固件与接线说明](arduino/Vanta_iX_PLC_Direct_5V/README.md)

## 构建目录式 EXE

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --clean VantaListener.spec
```

打开 `dist/VantaListener/VantaListener.exe`。交付时请复制整个 `VantaListener` 目录，并保留 `_internal`。源码运行时，程序把日志和结果写到仓库根目录的 `runtime`。EXE 运行时，程序把它们写到 EXE 旁边的 `runtime`。

## 开发者测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

[Vanta iX API 命令列表](Vanta-API-master/Vanta_API_Documents/API-Command-List.md)

## 待修改计划

漏检 / 漏发判定相关的完整修改清单见 [docs/MODIFICATION_PLAN.md](docs/MODIFICATION_PLAN.md)。
