#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${1:-$ROOT/config.env}"
if [[ $EUID -ne 0 ]]; then echo "ERROR: run with sudo" >&2; exit 2; fi
if [[ ! -f "$CONFIG" ]]; then echo "ERROR: config file not found: $CONFIG" >&2; exit 2; fi
# shellcheck disable=SC1090
source "$CONFIG"
for name in DEVICE_IP DEVICE_MAC ADAPTER_IP; do
  value="${!name:-}"
  if [[ -z "$value" || "$value" == *'<'* || "$value" == *'>'* ]]; then echo "ERROR: fill $name" >&2; exit 2; fi
done
systemctl is-active --quiet x1s-fota-formal.service || { echo "ERROR: formal service is not active" >&2; exit 2; }
"$ROOT/tools/refresh_fota_ips.sh" "$CONFIG" >/dev/null
health="$(curl -kfsS https://127.0.0.1:16443/healthz)"
[[ "$health" == "DISARMED" ]] || { echo "ERROR: expected DISARMED before arm, got $health" >&2; exit 2; }
python3 - <<'PY'
from pathlib import Path
import hashlib
p=Path('/opt/x1s-ota/formal/x1s-local-1.18.301.rbl')
b=p.read_bytes()
assert len(b)==521664
assert hashlib.sha256(b).hexdigest()=='0d0d0b63feb0723356c7c64fd2664e8b73f90f711e2cfbdeb926b53fb9799374'
assert hashlib.md5(b).hexdigest()=='eaa68827e6537ce71521296c32fe0faf'
PY
rm -f /run/x1s-fota-formal.arm
touch /run/x1s-fota-formal.arm
health="$(curl -kfsS https://127.0.0.1:16443/healthz)"
[[ "$health" == "ARMED" ]] || { echo "ERROR: arm failed: $health" >&2; exit 2; }
echo "ARMED device=$DEVICE_IP"
echo "Power-cycle ONLY the target X1S once, then wait 6-7 minutes without interrupting power."
echo "Observe: tail -f /opt/x1s-ota/evidence/formal.jsonl"
