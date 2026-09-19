#!/bin/sh
set -eu
uci -q delete dhcp.x1s_ota_gateway || true
uci -q delete dhcp.x1s_ota || true
uci commit dhcp
dnsmasq --test
/etc/init.d/dnsmasq restart
echo "DHCP_CLEANED target-specific Option-3 override removed"
