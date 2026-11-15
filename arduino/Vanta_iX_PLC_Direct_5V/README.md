# Vanta iX 5 V 台架直连

Arduino UNO R4 WiFi 通过电脑 USB 供电和接收命令。接线端使用五根线。Arduino 以 `D4` 拉低 Vanta iX 的 `START` 输入，脉冲结束后将 `D4` 切回高阻输入。`READY`、`RAD_ON` 和 `FAULT` 由三个 Arduino 输入读取。

## 接线条件

1. 使用独立台架。停机断电后，确认原厂端子 3、4、5、6 已与 PLC 和外部上拉电源断开。确认 `COMMON` 允许与电脑 USB 地共地。
2. 断开分线板左下角的 mini-USB 供电线。该线给分线板状态灯供电。按原厂程序使用联锁、辐射警示灯和防护设施。
3. 在 Arduino 信号线断开的情况下，测量原厂 `START` 端子 5 释放时对 `COMMON` 的电压。再测 Arduino `5V` 对 Arduino `GND` 的电压。确认各信号在工作时始终处于 0 V 至 Arduino 的实际 `5V` 电源电压范围内。USB 供电时，该电源电压通常约为 4.7 V。
4. 断电接线。先给 Arduino 供电，再给 Vanta iX 供电。关机时，先关闭并断开 Vanta iX 电源。确认原厂信号线无电后，再断开 Arduino USB。

以上条件用于台架验证。若存在 24 V 信号或不能确认接地、电压及断电条件，请使用与现场匹配的隔离接口。Vanta iX 的电气规格见原厂《Vanta iX GPIO primer》的 “GPIO inputs” 和 “GPIO outputs” 两节。 [Arduino 供电规格](https://docs.arduino.cc/resources/datasheets/ABX00087-datasheet.pdf)

## 五根线

使用分线板上半部的 `Evident / OLYMPUS GPIO`。以端子号为准。Arduino 端使用杜邦公头。螺丝端子侧用能夹牢的裸铜线。

| 原厂 GPIO | Arduino | 功能 |
| --- | --- | --- |
| 1 或 2 `COMMON / GND_ISO` | `GND` | 共地 |
| 3 `READY`，橙线 | `D2` | 低电平有效 |
| 4 `RAD_ON`，黄线 | `D3` | 低电平有效 |
| 6 `FAULT`，深蓝线 | `D8` | 低电平有效 |
| 5 `START`，绿线 | `D4` | 下拉约 100 ms 后释放 |

程序对三个状态输入使用 `INPUT_PULLUP`。UNO R4 WiFi 的内部上拉在这套接法中每路约提供 0.1 至 0.5 mA。原厂建议 GPIO 输出的导通电流为每路 5 至 20 mA。使用短线做台架验证，并确认各状态切换稳定后再执行循环。 [RA4M1 内部上拉规格](https://www.renesas.com/en/document/dst/ra4m1-group-datasheet)

## 串口操作

在 Arduino IDE 打开固件文件。选择 **Arduino UNO R4 WiFi**。先在只有 USB 接线时上传。打开串口监视器。设置为 **115200**，行尾选 **新行**。 [固件源码](Vanta_iX_PLC_Direct_5V.ino)

| 命令 | 动作 |
| --- | --- |
| `START` | 请求一次触发。 |
| `START 100` | 请求发出 100 次触发。 |
| `DOUBLE START` 或 `DOUBLE START 1` | 立即发第一脉冲。释放后等 1 秒，再发第二脉冲。 |
| `DOUBLE START 0.5` | 立即发第一脉冲。释放后等 0.5 秒，再发第二脉冲。 |
| `STOP` | 释放 `START`，取消剩余次数。 |
| `CLEAR FAULT` | 实际 `FAULT=0` 时解除 Arduino 的故障锁。 |

`START` 和 `START 100` 在每次启动检测前，都等 `READY=1`、`RAD_ON=0` 和 `FAULT=0` 连续保持 2 秒。`START 100` 每次脉冲后，程序等待 `READY` 撤销并重新有效。随后才开始下一次等待。`CTRL TRIGGER` 中的 `sent` 是已发脉冲数。用设备结果记录核对实际完成次数。

`DOUBLE START` 用于在受控台架上复现 PLC 误发。命令在空闲时接收。每次接收发出两个约 100 ms 的低脉冲。间隔从第一脉冲释放时算起，因此两次下降沿约相隔 0.6 秒或 1.1 秒。`READY`、`RAD_ON` 和 `FAULT` 供串口记录。两次脉冲只按定时发送，即使 Arduino 已锁定 `FAULT`。可用 `STOP` 取消发送。

发出两个脉冲时分别显示 `CTRL DOUBLE_FIRST` 和 `CTRL DOUBLE_SECOND`。`CTRL DOUBLE_DONE` 表示两次脉冲已发送。若第二脉冲到达时本轮检测仍在运行，它会请求停测。若设备已提前结束并恢复就绪，第二脉冲可能启动一轮新检测。用设备日志核对实际停测原因。设备行为见原厂《Vanta iX GPIO primer》的 “START” 一节。

普通 `START` 循环收到 `FAULT` 时会释放 `D4` 并取消余下的触发。故障锁在本次上电期间有效。`DOUBLE START` 期间收到的故障也会锁定普通 `START`。等实际 `FAULT=0` 后发送 `CLEAR FAULT`，再输入新的 `START`。已开始的测量由 Vanta iX 及原厂保护系统处理。

## 先做单板检查

Arduino 只接 USB。把 `D2` 接到 Arduino `GND` 来模拟 `READY`。发送 `START`。约 2 秒后，串口应显示 `CTRL TRIGGER sent=1 total=1`。断开 `D2` 跳线再接回，模拟设备重新就绪。串口应显示 `CTRL DONE`。

发送 `START 100`。在等待期间把 `D8` 接到 Arduino `GND`，确认收到 `CTRL FAULT_STOPPED`。移除 `D8` 跳线。输入 `CLEAR FAULT`，再输入 `START`，确认可以开始新的一轮。
