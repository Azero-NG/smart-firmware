#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${1:-$ROOT/config.env}"
if [[ $EUID -ne 0 ]]; then echo "ERROR: run with sudo" >&2; exit 2; fi
if [[ ! -f "$CONFIG" ]]; then echo "ERROR: config file not found: $CONFIG" >&2; exit 2; fi
# shellcheck disable=SC1090
source "$CONFIG"
for name in DEVICE_IP DEVICE_MAC ADAPTER_IP LAN_IF WAN_IF; do
  value="${!name:-}"
  if [[ -z "$value" || "$value" == *'<'* || "$value" == *'>'* ]]; then
    echo "ERROR: fill $name in $CONFIG" >&2; exit 2
  fi
done
: "${FOTA_HOST:=fota.komect.com}"
python3 - "$DEVICE_IP" "$ADAPTER_IP" <<'PY'
import ipaddress, sys
for value in sys.argv[1:]: ipaddress.ip_address(value)
PY
if [[ ! "$DEVICE_MAC" =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]]; then
  echo "ERROR: invalid DEVICE_MAC" >&2; exit 2
fi
for cmd in python3 openssl nft getent systemctl curl; do
  command -v "$cmd" >/dev/null || { echo "ERROR: missing command: $cmd" >&2; exit 2; }
done

install -d -m 0755 /opt/x1s-ota/formal /opt/x1s-ota/tls /opt/x1s-ota/evidence
install -m 0555 "$ROOT/tools/formal_server.py" /opt/x1s-ota/formal/formal_server.py
install -m 0444 "$ROOT/firmware/x1s-local-1.18.301.rbl" /opt/x1s-ota/formal/x1s-local-1.18.301.rbl
python3 - <<'PY'
from pathlib import Path
import hashlib
p=Path('/opt/x1s-ota/formal/x1s-local-1.18.301.rbl')
b=p.read_bytes()
assert len(b)==521664
assert hashlib.sha256(b).hexdigest()=='0d0d0b63feb0723356c7c64fd2664e8b73f90f711e2cfbdeb926b53fb9799374'
assert hashlib.md5(b).hexdigest()=='eaa68827e6537ce71521296c32fe0faf'
print('FIRMWARE_LOCK_PASS')
PY

if [[ ! -s /opt/x1s-ota/tls/fota.crt || ! -s /opt/x1s-ota/tls/fota.key ]]; then
  openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 3650 \
    -subj '/CN=cgw.komect.com' \
    -addext 'subjectAltName=DNS:cgw.komect.com' \
    -keyout /opt/x1s-ota/tls/fota.key \
    -out /opt/x1s-ota/tls/fota.crt >/dev/null 2>&1
fi
chmod 600 /opt/x1s-ota/tls/fota.key
chmod 644 /opt/x1s-ota/tls/fota.crt

cat >/etc/sysctl.d/90-x1s-ota-gateway.conf <<'EOF'
net.ipv4.ip_forward=1
net.ipv4.conf.all.send_redirects=0
net.ipv4.conf.default.send_redirects=0
EOF
sysctl -p /etc/sysctl.d/90-x1s-ota-gateway.conf >/dev/null || sysctl --system >/dev/null || true

nft delete table ip x1s_gateway 2>/dev/null || true
nft add table ip x1s_gateway
nft 'add chain ip x1s_gateway postrouting { type nat hook postrouting priority srcnat; policy accept; }'
nft "add rule ip x1s_gateway postrouting ip saddr \"$DEVICE_IP\" oifname \"$WAN_IF\" counter masquerade comment \"X1S routed via adapter\""

nft delete table ip x1s_fota 2>/dev/null || true
nft add table ip x1s_fota
nft 'add set ip x1s_fota fota_ipv4 { type ipv4_addr; }'
nft 'add chain ip x1s_fota prerouting { type nat hook prerouting priority dstnat; policy accept; }'
nft "add rule ip x1s_fota prerouting ip saddr \"$DEVICE_IP\" ip daddr @fota_ipv4 tcp dport 443 counter redirect to :16443 comment \"X1S FOTA one-shot\""

"$ROOT/tools/refresh_fota_ips.sh" "$CONFIG" >/dev/null
rm -f /run/x1s-fota-formal.arm
cat >/etc/systemd/system/x1s-fota-formal.service <<EOF
[Unit]
Description=X1S one-shot formal FOTA candidate
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -u /opt/x1s-ota/formal/formal_server.py --cert /opt/x1s-ota/tls/fota.crt --key /opt/x1s-ota/tls/fota.key --firmware /opt/x1s-ota/formal/x1s-local-1.18.301.rbl --arm-file /run/x1s-fota-formal.arm --log /opt/x1s-ota/evidence/formal.jsonl --download-url http://${ADAPTER_IP}/x1s-local-1.18.301.rbl
Restart=on-failure
RestartSec=2
User=root

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now x1s-fota-formal.service
sleep 1
health="$(curl -kfsS https://127.0.0.1:16443/healthz)"
[[ "$health" == "DISARMED" ]] || { echo "ERROR: expected DISARMED, got $health" >&2; exit 2; }
echo "ADAPTER_READY health=DISARMED device=$DEVICE_IP adapter=$ADAPTER_IP"
echo "IMPORTANT: configure DHCP Option 3 for only $DEVICE_MAC before arming."
