# Smart Firmware ⚡

Smart IoT device firmware migration toolchain, pre-built binaries, and guides. Focuses on **wire-free, OTA (Over-The-Air)** transitions from proprietary/carrier cloud firmware to open-source firmware (such as **ESPHome**, **OpenBeken**, etc.) for local-first smart home integration (e.g. **Home Assistant**).

智能硬件 / 智能插座免拆 OTA 固件迁移工具库与固件包。旨在无需拆机、无需焊接串口，通过局域网 OTA 平滑迁移到 **ESPHome** / **OpenBeken** 等开放固件，接入 **Home Assistant** 实现完全本地化控制。

---

## 📱 Device Support Status / 支持设备列表

| Device / 型号 | Chip / 芯片 | Baseline / 原厂基线 | Target Firmware / 目标固件 | Status / 状态 | Guide / 文档 |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **ORVIBO CT30W** (欧瑞博) | ESP8266 | `CT30_XY` / CMCC v2.0.15 | ESPHome 2026.7.4 | ✅ Ready | [CT30W Guide](CT30W/README.md) |
| **X1S** (产品类型 `590384`) | BK7231N | 原厂 1.0.4 | OpenBeken 1.18.301 | ⏳ Planned | *Coming Soon* |

---

## 🚀 Quick Start / 快速开始

### 1. ORVIBO CT30W
适用于搭载 ESP8266 的 ORVIBO CT30W 智能插座（原厂基线 `CT30_XY`、CMCC v2.0.15），通过局域网 OOBE OTA -> eboot 迁移 -> 最终写入 ESPHome 原生固件。

详情请直接参阅：[👉 CT30W 详细免拆刷机指引](CT30W/README.md)

---

## 🛡️ Repository Verification / 本地自检

在对任何设备进行刷机操作前，可运行仓库内置的自检脚本，确认本地文件完整性、二进制哈希与工具链环境：

```bash
python3 verify.py
```

自检仅校验本地文件、构包逻辑与散列值，不会对真实局域网设备产生任何影响。

---

## ⚠️ Disclaimer / 免责声明与安全警告

1. **不可逆边界**：固件迁移包含引导区（bootloader）与存储分区的改写操作。请在操作前仔细阅读对应设备目录下的 `README.md`。
2. **严守检查点**：文档中凡是标注 **“不要继续”** 的地方，请务必停下排查原因，切勿通过重复断电、强推固件或跨版本混用来尝试绕过。
3. **风险自负**：本项目所提供的工具与固件均经过真机验证，但使用者需自行承担因操作失误、设备硬件批次差异或网络中断可能带来的设备变砖风险。

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
