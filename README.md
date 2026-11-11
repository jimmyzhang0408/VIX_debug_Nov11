# Vanta iX 漏检监控系统 (Listener 模式 - PySide GUI)

本工具基于 `Vanta-API-master` 官方 WebSocket API 规范开发，使用 **Listener (监听) 模式** 连接到 Vanta iX，在不干扰设备原有主控端（PC 软件或 PLC 控制器）的前提下，实时监控设备状态、捕获并导出 `206` (`ResultReceived`) 检测结果，重点排查客户反馈的 **漏检问题**。

---

## 核心功能

1. **标准 Listener 模式连接 (`ws://<host>:7860`)**
   - 连接建立后自动以 **Text (文本)** 模式发送 `"Hi i am a listener"`，并校验返回 `"Client connected as a listener."`。
   - 支持局域网 IP（如 `10.163.210.80`）或 USB OTG（`192.168.7.2`），支持断线自动重连。

2. **监控 `testID` 是否跳过递增 & 实时显示 `dailyID`**
   - 实时从 `206` (`ResultReceived`) 的 `params.result.analysis` 中提取：
     - **`testID`** (`analysis.testId` / `result.testId`)：全局递增测试 ID。
     - **`dailyID`** (`analysis.dailyId` / `analysis.tidName`)：每日递增测试 ID（午夜自动重置为 1）。
   - **跳号检测 (`SKIPPED` 告警)**：
     - 每次收到有效最终 `206` 结果时，自动对比 `当前 testID` 与 `上一个 testID + 1`。
     - 若发现 `当前 testID > 上一个 testID + 1`（例如从 `1001` 直接跳到 `1004`），立即判定为 **跳号 (`SKIPPED`)**：
       - 顶部状态横幅变红告警，显示跳过的具体 `testID` 列表（如 `[1002, 1003]`）；
       - 累加“跳号发生次数”与“累计缺失 testID 数”；
       - 表格对应行高亮标红，并写入右侧 `⚠️ 漏检与跳号告警` 日志与本地 `vanta_missed_detection_alarms.log`。
   - **双重监控 `dailyID`**：同时校验 `dailyID` 是否连续递增或发生跳号。

3. **监控 Vanta iX 实时状态与“有启动无结果”漏检**
   - 实时监控：
     - `100` (`SystemStatus`)：系统状态与 X-Ray 射线开启/关闭指示灯。
     - `139` (`DigitalIOStateChanged`)：Vanta iX 专有 GPIO Bank 1~4 状态及输入/输出位状态。
     - `702` (`TriggerPulled`) / `704` (`KeyPressed`)：硬件或 GPIO 触发信号计数。
     - `200` (`TestStarted`) / `202` (`ExposureStarted`) / `207` (`ExposureStatus`) / `203` (`ExposureStopped`) / `201` (`TestStopped`)：完整检测生命周期与曝光进度条。
     - `209` (`ErrorDuringTest`)：检测中报错告警。
   - **“有启动无 206 结果”漏检捕获**：若收到 `200 (TestStarted)` 后收到 `201 (TestStopped)`，但期间未收到任何有效的最终 `206` 结果（例如因超时、安全联锁断开或外部中断导致漏检），立即触发告警并累加计数。

4. **导出 206 检测结果**
   - **实时自动导出**：
     - 原始 JSON 文件自动保存至 `exports_206/json_206/206_seqXXXX_testID_<id>_dailyID_<did>_<timestamp>.json`。
     - 汇总表格实时追加至 `exports_206/vanta_206_summary_<timestamp>.csv`（包含序号、接收时间、设备时间、`final`、`testID`、期望 `testID`、是否跳号、缺失 `testID`、`dailyID`、`tidName`、检测方法、牌号匹配、主要化学成分、原始 JSON 路径）。
   - **手动导出**：支持一键导出汇总 CSV、另存单条 206 JSON、导出漏检告警日志。

5. **内置离线仿真调试栏**
   - 底部提供三个仿真按钮，无需连接真实设备即可测试：
     - **模拟正常检测 (`testID +1, dailyID +1`)**
     - **模拟 `testID` 跳号漏检 (跳过 2 个 `testID`)**
     - **模拟有触发/启动(`200`)但无 `206` 结果即停止(`201`)**

---

## 启动方式

```bash
# 使用项目虚拟环境直接运行
/Users/jiez/Desktop/VIX_debug_Nov11/.venv/bin/python /Users/jiez/Desktop/VIX_debug_Nov11/vanta_listener_gui.py
```
