# ORVIBO CT30W：原厂固件免拆迁移到 ESPHome

## 0. 这份教程适用于什么设备

只适用于下面这个组合：

- ORVIBO **CT30W**；
- ESP8266；
- 原厂运行时产品字段 **`CT30_XY`**；
- 已验证原厂基线 **CMCC v2.0.15**；
- 目标固件 **ESPHome 2026.7.4**。

成功路径不需要拆机、不需要串口：

```text
原厂 CT30_XY
  -> 原厂局域网 OOBE OTA
  -> ESPHome transition
  -> 无压缩 ESPHome OTA，把 eboot+transition 写到 staging
  -> migrate_eboot
  -> eboot 启动
  -> 写入已真机验证的最终 ESPHome
  -> CT30W-Open-Setup 配网
```

如果你的设备不是 CT30W、原厂版本不是这条基线，或者第 4 步读到的 `hw_ver` 不是 `CT30_XY`，**不要继续**。

## 1. 需要准备什么

一台与 CT30W 在同一局域网的 macOS 或 Linux 电脑，安装：

- Python **3.12–3.14**（ESPHome 2026.7.4 不支持 Python 3.11）；
- Go；
- 可访问 2.4 GHz 局域网；
- CT30W 已经通过原厂方式接入这个局域网，并且能正常在线。

先确认 Python：

```bash
python3 --version
```

必须是 3.12、3.13 或 3.14。若系统自带 Python 过旧，请先安装 3.12+；例如可用 `uv python install 3.13` 或发行版/Homebrew 的 Python 3.13。Debian/Ubuntu 还需要与该 Python 对应的 venv 支持。基础工具至少包括 Go、curl 和 nc。

本文使用占位符：

```text
<CT30W_IP>       CT30W 当前原厂 DHCP 地址
<THIS_PC_IP>     运行本教程电脑在同一局域网的 IPv4 地址
```

不要照抄占位符。

## 2. 本地自检

先用 Python 3.12–3.14 建立环境。若你的 `python3` 已符合版本要求：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

如果使用 `uv` 管理 Python：

```bash
uv python install 3.13
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

然后执行：

```bash
./verify.py
```

预期最后看到：

```text
CT30W_PUBLIC_PASS ...
```

固定的最终 ESPHome 文件必须是：

```text
firmware/CT30W_ESPHome_final_native.bin
size   441520
sha256 2a8fd3be52b4ecee66a4d274ea1966b4e76bac85b02c6274e4bda4a3b883e786
```

本目录**没有**公开携带历史 transition 二进制，因为 transition 必须包含你自己的 Wi-Fi 凭据；下面会从相同的已验证源码现场编译。

## 3. 填你自己的 Wi-Fi，并构建 transition

复制模板：

```bash
cp esphome/secrets.example.yaml esphome/secrets.yaml
```

编辑 `esphome/secrets.yaml`，填入你自己的 **2.4 GHz** Wi-Fi：

```yaml
wifi_ssid: "你的 2.4G SSID"
wifi_password: "你的 Wi-Fi 密码"
fallback_ap_password: "给 transition 临时热点设置一个强密码"
```

然后执行唯一的构建命令：

```bash
./tools/build_transition.sh
```

成功时会生成：

```text
build/CT30W_eboot_transition_native.bin
build/CT30W_eboot_transition_v2.bin
build/ct30w-recovery.bin
build/ct30w-stock-rollback.bin
build/transition-metadata.json
```

并出现：

```text
BUILD_OK .../build/ct30w-recovery.bin
```

再检查 wrapper：

```bash
.venv/bin/python tools/build_transition.py inspect build/ct30w-recovery.bin
```

必须同时满足：

```text
"accepted": true
"product": "CT30_XY"
"fin": 1
```

如果不是这三个结果，**不要继续**。

> 编译时间和你自己的 Wi-Fi 会进入 transition，因此它的 SHA-256 不要求等于历史真机文件。构包器会固定 ESP8266 v2、DOUT、40 MHz、2 MiB-c1、长度、CRC32、SDK CRC 和 `CT30_XY` 字段。

## 4. 确认你正在操作正确的实体设备

先设置两个变量，替换成真实地址：

```bash
export CT30W_IP='<CT30W_IP>'
export THIS_PC_IP='<THIS_PC_IP>'
```

先发状态查询，不发 OTA：

```bash
.venv/bin/python tools/ct30w_oobe.py status \
  --source "$THIS_PC_IP" \
  --target "$CT30W_IP" \
  --timeout 5 --poll-interval 0.5 --execute
```

必须看到至少一个 `event=report` 的 JSON，并核对：

- `report.cmd` 是 `REPORT`；
- `report.hw_ver` 是 **`CT30_XY`**；
- `download_progress` 为 0；
- 报告里的设备标识与你刚刚通过断电/上电或路由器 DHCP 确认的那一只 CT30W 对得上。

没有 REPORT、`hw_ver` 不同、IP 对不上，或者你不能确认实体设备时，**不要继续**。

## 5. 启动原厂 OTA 文件服务

第一个终端运行：

```bash
go run ./tools/paced_server.go \
  -listen "$THIS_PC_IP:18081" \
  -root ./build \
  -log ./build/paced-server.log \
  -chunk-size 512 \
  -metadata-pause 250ms \
  -sector-pause 250ms \
  -chunk-delay 40ms
```

这个服务只允许两个文件名：

```text
/ct30w-recovery.bin
/ct30w-stock-rollback.bin
```

另开终端先确认 HTTP 可达：

```bash
curl -fsS "http://$THIS_PC_IP:18081/ct30w-recovery.bin" -o /tmp/ct30w-recovery.bin
cmp /tmp/ct30w-recovery.bin build/ct30w-recovery.bin
```

`cmp` 必须没有输出并退出 0。

## 6. 只触发一次原厂 OTA

先做 dry-run，检查最终 URL：

```bash
.venv/bin/python tools/ct30w_oobe.py trigger \
  --source "$THIS_PC_IP" \
  --target "$CT30W_IP" \
  --url "http://$THIS_PC_IP:18081/ct30w-recovery.bin"
```

确认 `execute=false`、目标 IP 和 URL 完全正确后，才执行真实触发：

```bash
.venv/bin/python tools/ct30w_oobe.py trigger \
  --source "$THIS_PC_IP" \
  --target "$CT30W_IP" \
  --url "http://$THIS_PC_IP:18081/ct30w-recovery.bin" \
  --timeout 90 --poll-interval 1 --execute \
  | tee build/oobe-trigger.jsonl
```

正确现象依次是：

1. 命令出现 `event=sent`；
2. `build/paced-server.log` 出现目标设备的 `/ct30w-recovery.bin` GET；
3. OOBE `REPORT.download_progress` 持续上升；
4. 服务日志出现 `result=complete`，并且 `payload_bytes` 等于 `written`；
5. 下载后原厂约等待数秒再重启；
6. `ct30w-open` 使用同一份 transition Wi-Fi 凭据重新进入网络。

**一旦已经看到 HTTP GET 或进度上升，不要再次发送 OTA。** 如果 HTTP 没有完整传输、设备反复重启或下载后仍长期保持原厂身份，**不要继续到 eboot 迁移**。

## 7. 确认 transition 已经启动

从 DHCP 租约找到 `ct30w-open` 的新地址，记为：

```bash
export CT30W_TRANSITION_IP='<CT30W_TRANSITION_IP>'
```

先检查 TCP：

```bash
nc -vz "$CT30W_TRANSITION_IP" 6053
nc -vz "$CT30W_TRANSITION_IP" 8266
```

再用 API 列服务：

```bash
.venv/bin/python tools/invoke_service.py --host "$CT30W_TRANSITION_IP"
```

必须能看到：

```text
stock_boot_rollback
migrate_eboot
```

看不到这两个服务时，**不要继续**。

## 8. 把 eboot+transition 写入 staging

这一步仍不会立即替换 bootloader。它先通过 ESPHome OTA 把刚才构建的 native 镜像完整写入 staging：

```bash
.venv/bin/python tools/upload_uncompressed.py \
  "$CT30W_TRANSITION_IP" \
  build/CT30W_eboot_transition_native.bin
```

必须看到：

```text
UNCOMPRESSED_OTA_EXIT=0
```

然后读取构建时自动计算的确认值：

```bash
cat build/transition-metadata.json
```

找到 `native.size` 和 `native.crc32`。为了避免手抄错误，可以直接执行：

```bash
read EXPECTED_SIZE EXPECTED_CRC < <(
  .venv/bin/python - <<'PY'
import json
m=json.load(open('build/transition-metadata.json'))
print(m['native']['size'], m['native']['crc32'])
PY
)
echo "size=$EXPECTED_SIZE crc=$EXPECTED_CRC"
```

## 9. 迁移到 eboot

这是 CT30W 路径的关键写入点。确认上一节无报错后执行：

```bash
.venv/bin/python tools/invoke_service.py \
  --host "$CT30W_TRANSITION_IP" \
  --service migrate_eboot \
  --data "{\"expected_size\":$EXPECTED_SIZE,\"expected_crc\":\"$EXPECTED_CRC\"}"
```

设备会验证 staging 的大小和 CRC、写入并读回 eboot sector，然后自行重启。等待它重新出现在网络中，再次确认 6053 可连接。

如果服务返回拒绝、设备没有正常重启，**不要重复执行 migrate_eboot**；保留 `build/transition-metadata.json` 和日志定位原因。

## 10. 写入最终 ESPHome

重新找到 `ct30w-open` 的地址后执行：

```bash
export CT30W_EBOOT_IP='<CT30W_EBOOT_IP>'
.venv/bin/esphome upload esphome/final.yaml \
  --device "$CT30W_EBOOT_IP" \
  --file firmware/CT30W_ESPHome_final_native.bin
```

这是仓库保存的**精确真机验收字节序列**。上传完成后设备重启，最终固件没有预置你的家庭 Wi-Fi，因此会出现开放热点：

```text
CT30W-Open-Setup
```

连接这个热点，打开系统弹出的 captive portal；若没有自动弹出，浏览器访问：

```text
http://192.168.4.1/
```

选择你的 2.4 GHz Wi-Fi 并保存。设备重启并重新获取家庭 LAN 地址。

## 11. 最终验收

找到最终地址：

```bash
export CT30W_FINAL_IP='<CT30W_FINAL_IP>'
nc -vz "$CT30W_FINAL_IP" 6053
.venv/bin/python tools/invoke_service.py --host "$CT30W_FINAL_IP"
```

通过标准：

- 输出中的 `name` 是 `ct30w-open`；
- 输出中的 `esphome_version` 是 `2026.7.4`；
- API 可连接；
- 最终固件暴露 `run_sweep`；
- 机身 GPIO4 短按会重启；持续按住约 3 秒会执行恢复出厂；
- 恢复出厂后重新出现 `CT30W-Open-Setup`。

到这里，免拆迁移完成。

## 12. 什么时候可以回退，什么时候不能乱试

### 还在 transition、尚未执行 `migrate_eboot`

transition 暴露 `stock_boot_rollback(url)`。保持第 5 步的 paced server 在运行，可请求：

```bash
.venv/bin/python tools/invoke_service.py \
  --host "$CT30W_TRANSITION_IP" \
  --service stock_boot_rollback \
  --data "{\"url\":\"http://$THIS_PC_IP:18081/ct30w-stock-rollback.bin\"}"
```

本目录保存的 rollback wrapper 固定为原厂 v2.0.15 PRIMARY，SHA-256：

```text
5029cddcb04249535c4e6eb11eea65d118f57725df7a75dbc6303a9596622d8e
```

这条网络回退入口和包已通过发布校验，但成功迁移的最终验收过程没有再额外执行一次真机网络回退。因此把它当作 transition 阶段的恢复入口，而不是“已经证明任何失败都能自动回滚”的承诺。

### 已执行 `migrate_eboot` 之后

不要再假设原厂 boot/copy 回退仍然成立。优先完成第 10 步进入正常 ESPHome。若设备在这里失联，停止写入；不要重复发送原厂 OTA、不要用其他 ESP8266 固件碰运气。

## 13. 最常见的失败点

| 现象 | 处理 |
|---|---|
| OOBE 没有 REPORT | 确认 CT30W 已在 Station 模式、IP 正确、电脑和设备可双向到达 UDP/5000 |
| `hw_ver` 不是 `CT30_XY` | **不要继续**；当前 wrapper 不适用 |
| HTTP 没 GET | 检查 `$THIS_PC_IP:18081` 是否从 CT30W 可达；确认 URL 是 `http://` |
| HTTP 404 | 文件名必须是 `/ct30w-recovery.bin` |
| 进度上升但不重启 | **不要重发**；保存日志，检查 wrapper 是否 accepted/product CT30_XY |
| transition 上线但没有 `migrate_eboot` | **不要继续**；说明启动的不是这份 transition |
| uncompressed OTA 失败 | 不执行 `migrate_eboot`；先恢复网络和 OTA 8266 |
| 最终上传后旧 IP 消失 | 正常；扫描 `CT30W-Open-Setup`，最终固件需要重新配 Wi-Fi |
