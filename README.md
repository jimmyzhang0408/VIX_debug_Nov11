# Vanta iX 实时监控

此版本使用 Tk 界面，显示 Vanta iX 的 WebSocket 通知、Arduino 串口状态和元素结果。收到新的最终 `206` 时，程序记录该结果。验收检测时，请同时核对 `201` 的停测原因。

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

## Arduino 固件与接线

DEMO 台架使用 Arduino UNO R4 WiFi。固件和五根线的接线表在同一目录。先阅读接线条件，再连接设备。 [固件与接线说明](arduino/Vanta_iX_PLC_Direct_5V/README.md)

## 构建目录式 EXE

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean VantaListener.spec
```

打开 `dist/VantaListener/VantaListener.exe`。交付时请复制整个 `VantaListener` 目录，并保留 `_internal`。源码运行时，程序把日志和结果写到仓库根目录的 `runtime`。EXE 运行时，程序把它们写到 EXE 旁边的 `runtime`。

[Vanta iX API 命令列表](Vanta-API-master/Vanta_API_Documents/API-Command-List.md)

## 待修改计划

漏检 / 漏发判定相关的完整修改清单见 [docs/MODIFICATION_PLAN.md](docs/MODIFICATION_PLAN.md)。
