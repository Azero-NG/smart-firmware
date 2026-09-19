#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "ERROR: run with sudo" >&2; exit 2; fi
rm -f /run/x1s-fota-formal.arm
systemctl disable --now x1s-fota-formal.service 2>/dev/null || true
nft delete table ip x1s_fota 2>/dev/null || true
nft delete table ip x1s_gateway 2>/dev/null || true
rm -f /etc/sysctl.d/90-x1s-ota-gateway.conf
sysctl --system >/dev/null || true
echo "ADAPTER_CLEANED evidence_preserved=/opt/x1s-ota/evidence"
