#!/bin/sh
set -eu
: "${DEVICE_IP:?set DEVICE_IP}"
: "${DEVICE_MAC:?set DEVICE_MAC}"
: "${ADAPTER_IP:?set ADAPTER_IP}"
case "$DEVICE_IP$DEVICE_MAC$ADAPTER_IP" in *'<'*|*'>'*) echo "ERROR: replace placeholders" >&2; exit 2;; esac
backup="/root/dhcp.before-x1s-ota.$(date +%s)"
cp /etc/config/dhcp "$backup"
uci -q delete dhcp.x1s_ota_gateway || true
uci set dhcp.x1s_ota_gateway='tag'
uci add_list dhcp.x1s_ota_gateway.dhcp_option="3,$ADAPTER_IP"
uci -q delete dhcp.x1s_ota || true
uci set dhcp.x1s_ota='host'
uci set dhcp.x1s_ota.name='X1S'
uci set dhcp.x1s_ota.ip="$DEVICE_IP"
uci add_list dhcp.x1s_ota.mac="$DEVICE_MAC"
uci add_list dhcp.x1s_ota.tag='x1s_ota_gateway'
uci commit dhcp
dnsmasq --test
/etc/init.d/dnsmasq restart
echo "DHCP_READY backup=$backup target=$DEVICE_MAC ip=$DEVICE_IP gateway=$ADAPTER_IP"
