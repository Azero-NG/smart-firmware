#!/usr/bin/env bash
set -euo pipefail
CONFIG="${1:-config.env}"
if [[ ! -f "$CONFIG" ]]; then echo "ERROR: config file not found: $CONFIG" >&2; exit 2; fi
# shellcheck disable=SC1090
source "$CONFIG"
: "${FOTA_HOST:=fota.komect.com}"
if [[ $EUID -eq 0 ]]; then SUDO=(); else SUDO=(sudo); fi
if ! "${SUDO[@]}" nft list set ip x1s_fota fota_ipv4 >/dev/null 2>&1; then
  echo "ERROR: nft set x1s_fota/fota_ipv4 does not exist; run setup_adapter.sh first" >&2
  exit 2
fi
mapfile -t IPS < <(getent ahostsv4 "$FOTA_HOST" | awk '{print $1}' | sort -u)
if [[ ${#IPS[@]} -eq 0 ]]; then echo "ERROR: no IPv4 address resolved for $FOTA_HOST" >&2; exit 2; fi
"${SUDO[@]}" nft flush set ip x1s_fota fota_ipv4
for ip in "${IPS[@]}"; do
  "${SUDO[@]}" nft add element ip x1s_fota fota_ipv4 "{ $ip }"
done
echo "FOTA_IPS_REFRESHED host=$FOTA_HOST ips=${IPS[*]}"
"${SUDO[@]}" nft list set ip x1s_fota fota_ipv4
