#!/usr/bin/env python3
import logging
import socket
import sys
from pathlib import Path

from esphome import espota2

host = sys.argv[1]
firmware = Path(sys.argv[2])
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
espota2.CLIENT_FEATURE_SUPPORTS_COMPRESSION = 0
with socket.create_connection((host, 8266), timeout=20) as sock, firmware.open('rb') as handle:
    sock.settimeout(20)
    espota2.perform_ota(sock, None, handle, firmware)
print(f'UNCOMPRESSED_OTA_EXIT=0 size={firmware.stat().st_size}')
