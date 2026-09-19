# X1S 免拆机刷机指引

通过局域网 OTA，将 X1S 原厂固件迁移到 OpenBeken，无需拆机或连接串口。

## 1. 适用设备与准备

本指引仅适用于以下组合，任一项不符都不要继续：

| 项目 | 版本 / 型号 |
| --- | --- |
| 设备 | X1S 智能插座 |
| 移动爱家产品类型 | `590384` |
| 芯片 | BK7231N |
| 原厂固件 | `1.0.4` |
| 目标固件 | OpenBeken `1.18.301` |

准备：

- 已接入家庭 2.4 GHz Wi-Fi、在原厂 App 中正常在线的 X1S。
- 一台同局域网的 Linux 电脑，具有 sudo/root 权限，使用 systemd，可转发设备流量到互联网。
- 能按设备 MAC 单独下发默认网关的 DHCP 服务器。下文使用 OpenWrt/dnsmasq。
- 刷机期间保持供电稳定，先拔掉插座上的负载。

**本流程没有已验证的免拆回刷原厂方案。** 接受迁移后无法按本指引恢复原厂固件，再开始操作。

在路由器租约和 App 中确认目标设备的型号、原厂版本、IP 和 MAC。以下 `<...>` 都要替换为自己的值：

| 占位符 | 含义 |
| --- | --- |
| `<X1S_STOCK_IP>` | X1S 原厂 DHCP 地址，刷机期间固定分配 |
| `<X1S_MAC>` | 这台 X1S 的 MAC |
| `<LINUX_ADAPTER_IP>` | Linux 电脑在家庭局域网中的固定地址 |
| `<LAN_INTERFACE>` | Linux 接收 X1S 流量的网卡 |
| `<UPLINK_INTERFACE>` | Linux 通往原路由器 / 互联网的网卡 |
| `<OPENWRT_IP>` | OpenWrt 路由器地址 |
| `<OPENBEKEN_IP>` | 刷机并重新配网后的设备地址 |

单网卡旁路网关的两个网卡字段可以相同。Linux 的 TCP 80、16443 端口需空闲，并允许目标 X1S 访问；只在可信局域网运行刷机服务。

## 2. 安装依赖并校验文件

将本仓库复制到 Linux 电脑，进入 `X1S` 目录。**后续 Linux 命令均在该目录执行。**

Debian/Ubuntu：

```bash
sudo apt-get update
sudo apt-get install -y python3 openssl nftables curl libc-bin openssh-client
python3 verify.py
```

自检只使用本机临时服务，不向插座发送升级。成功输出：

```text
X1S_PUBLIC_PASS firmware=locked one_shot=pass chunked=pass download=exact gpio=verified
```

本目录已包含所需固件，无需自行编译或修改：

```text
firmware/x1s-local-1.18.301.rbl
大小     521664 字节
SHA-256  0d0d0b63feb0723356c7c64fd2664e8b73f90f711e2cfbdeb926b53fb9799374
```

自检失败时不要继续，也不要替换成其他型号的固件。

## 3. 配置临时刷机网关

```bash
cp config.example.env config.env
```

编辑 `config.env`：

```bash
DEVICE_IP='<X1S_STOCK_IP>'
DEVICE_MAC='<X1S_MAC>'
ADAPTER_IP='<LINUX_ADAPTER_IP>'
LAN_IF='<LAN_INTERFACE>'
WAN_IF='<UPLINK_INTERFACE>'
FOTA_HOST='fota.komect.com'
```

启动：

```bash
sudo ./tools/setup_adapter.sh config.env
curl -kfsS https://127.0.0.1:16443/healthz
```

脚本应输出 `FIRMWARE_LOCK_PASS` 和 `ADAPTER_READY health=DISARMED ...`，状态查询应为 `DISARMED`（尚未允许升级）。

脚本会启用 IPv4 转发，为指定设备设置 NAT，并将它访问原厂 FOTA 地址的 HTTPS 请求转到本机刷机服务。若 Linux 防火墙默认禁止转发，需要放行目标设备的转发及返回流量后再继续。

## 4. 让目标 X1S 使用临时网关

在 Linux 上复制 DHCP 脚本：

```bash
scp tools/openwrt_dhcp_setup.sh root@<OPENWRT_IP>:/tmp/
```

登录 OpenWrt，在路由器上执行：

```bash
DEVICE_IP='<X1S_STOCK_IP>' \
DEVICE_MAC='<X1S_MAC>' \
ADAPTER_IP='<LINUX_ADAPTER_IP>' \
sh /tmp/openwrt_dhcp_setup.sh
```

脚本会备份 DHCP 配置，并为这个 MAC 设置固定地址和专用默认网关。如果路由器已为同一 MAC 配置静态租约，先确保没有重复或冲突的主机条目。

让目标 X1S 断电约 3 秒后重新上电，获取新的网关配置。此时先不要允许升级。

在 Linux 上检查：

```bash
sudo nft list table ip x1s_gateway
sudo nft list table ip x1s_fota
curl -kfsS https://127.0.0.1:16443/healthz
```

继续前确认：X1S 在原厂 App 中仍正常在线，`x1s_gateway` 的计数增长，其他设备网络正常，服务状态仍为 `DISARMED`。

## 5. 允许一次升级并触发刷机

在 Linux 上执行：

```bash
sudo ./tools/arm.sh config.env
curl -kfsS https://127.0.0.1:16443/healthz
```

必须看到 `ARMED`，表示下一次原厂升级检查可获取本目录的 OpenBeken 固件。

让**目标 X1S**断电约 3 秒后重新上电一次。原厂 1.0.4 通常在启动约 **6–7 分钟**后检查升级；此后保持供电，不要反复断电或再次执行 `arm.sh`。

查看刷机进度：

```bash
sudo tail -f /opt/x1s-ota/evidence/formal.jsonl
```

正常会依次出现：

```text
"event":"fota_check"
"response_mode":"armed_formal_candidate"
"event":"formal_download"
"length":521664
```

一次升级响应发出后，状态会自动回到 `DISARMED`。`formal_download` 表示服务收到了固件下载请求；**是否刷机成功，以后续 OpenBeken 启动和页面版本为准**。按 Ctrl+C 退出日志查看不会停止刷机服务。

## 6. 连接 OpenBeken 并配置 Wi-Fi

固件传输及安装后设备会重启，原厂 IP 离线是正常现象。等待约 30–120 秒后，在手机或电脑上扫描 2.4 GHz Wi-Fi：

```text
OpenBK7231N_XXXXXXXX
```

连接这个开放热点，打开 `http://192.168.4.1/`，确认页面显示 **version 1.18.301** 和 **Chipset BK7231N**。

1. 进入 **Config → Configure WiFi & Web**。
2. 填写家庭 **2.4 GHz** Wi-Fi 名称和密码并保存。
3. 等待设备重启，电脑 / 手机重新连接家庭网络。
4. 从路由器 DHCP 租约找到设备的新地址 `<OPENBEKEN_IP>`。
5. 打开 `http://<OPENBEKEN_IP>/`，再次核对版本和芯片。

## 7. 配置插座引脚

保持插座不接负载，在 Linux 的 `X1S` 目录执行：

```bash
python3 tools/apply_gpio.py postflash/x1s_gpio.json \
  --url 'http://<OPENBEKEN_IP>'
```

脚本在配置前后都将继电器通道设为关闭，并回读核对引脚配置。成功时输出 `VERIFY status=200 roles=...`。

| 引脚 | 功能 |
| --- | --- |
| P6 / P7 / P26 | BL0937CF / BL0937CF1 / BL0937SEL |
| P8 | 继电器，Channel 1 |
| P10 | 继电器状态灯，Channel 1 |
| P11 | Wi-Fi 状态灯 |
| P24 | 按键，Channel 1 |

配置完成后正常断电、上电一次，确认网页仍可访问，实体按键和网页开关能控制继电器，测试结束后保持关闭。此模板配置计量引脚，不代表已完成计量校准。

可选：若希望关闭两颗指示灯，执行：

```bash
python3 tools/apply_gpio.py postflash/x1s_led_off.json \
  --url 'http://<OPENBEKEN_IP>'
```

## 8. 清理临时刷机环境

在 Linux 上执行，移除路由器对目标设备的临时网关配置：

```bash
scp tools/openwrt_dhcp_cleanup.sh root@<OPENWRT_IP>:/tmp/
ssh root@<OPENWRT_IP> 'sh /tmp/openwrt_dhcp_cleanup.sh'
```

停止刷机服务并删除临时网络规则：

```bash
sudo ./tools/cleanup_adapter.sh
```

脚本保留 `/opt/x1s-ota/` 下的固件和日志，并移除本流程创建的 sysctl 配置文件；原有系统配置没有覆盖的运行时 sysctl 值不会自动还原，如需还原请按刷机前的设置处理。

让 X1S 重新联网以获取普通默认网关，确认网页和按键开关正常，即完成刷机。

## 9. 中止与异常处理

- **升级响应尚未发出**：先取消允许升级，再按第 8 步清理网络配置，可恢复原厂联网路径。

  ```bash
  sudo rm -f /run/x1s-fota-formal.arm
  curl -kfsS https://127.0.0.1:16443/healthz
  ```

  状态应为 `DISARMED`；单看这个状态不能判断是否已升级，因为一次升级响应发出后也会自动取消。

- **等待后仍为 `ARMED`**：保持供电，确认目标设备仍在线、DHCP 默认网关已生效，并刷新 FOTA 地址：`sudo ./tools/refresh_fota_ips.sh config.env`。不要反复断电。
- **出现升级响应但未启动 OpenBeken**：不要再次允许升级。先等待并刷新 2.4 GHz Wi-Fi 扫描；下载请求本身不代表安装完成。
- **已启动 OpenBeken**：不要上传原厂 full-flash 或其他 BK7231 变种来尝试回退，本指引不提供网络恢复原厂流程。
