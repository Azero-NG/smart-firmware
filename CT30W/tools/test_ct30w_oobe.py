#!/usr/bin/env python3
import importlib.util
import json
import socket
import struct
import subprocess
import sys
import unittest
import zlib
from pathlib import Path

from Crypto.Cipher import AES

ROOT = Path(__file__).resolve().parent
IMPL = ROOT / "ct30w_oobe.py"
SPEC = importlib.util.spec_from_file_location("ct30w_oobe", IMPL)
ota = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ota)

SOURCE = "192.0.2.10"
TARGET = "192.0.2.20"
OTA_URL = "http://198.51.100.30:18081/ct30w.bin"
START_REPORT_HEX = "7285280045802bc7503d3ceec1cfe6e73c521a67d91c56c9e2e72742736d092324d615f2b0b77d3b"


def encode_nul_report():
    plain = b'{"cmd":"REPORT","download_progress":42}\x00'
    ciphertext = AES.new(ota.KEY, AES.MODE_ECB).encrypt(ota._pad_pkcs7(plain))
    return struct.pack("<HHI", ota.MAGIC, 8 + len(ciphertext), zlib.crc32(ciphertext) & 0xFFFFFFFF) + ciphertext


class FakeSocket:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def sendto(self, data, peer):
        self.sent.append((data, peer))
        return len(data)

    def settimeout(self, _value):
        pass

    def recvfrom(self, _size):
        if self.replies:
            return self.replies.pop(0)
        raise socket.timeout


class OOBECodecTests(unittest.TestCase):
    def test_start_report_fixed_vector(self):
        frame = ota.encode_oobe({"cmd": "START_REPORT"})
        self.assertEqual(frame.hex(), START_REPORT_HEX)
        self.assertEqual(ota.decode_oobe(frame), {"cmd": "START_REPORT"})

    def test_ota_roundtrip(self):
        payload = {"cmd": "OTA_UPGRADE", "url": OTA_URL}
        self.assertEqual(ota.decode_oobe(ota.encode_oobe(payload)), payload)

    def test_decode_nul_terminated_report(self):
        self.assertEqual(ota.decode_oobe(encode_nul_report()), {"cmd": "REPORT", "download_progress": 42})

    def test_rejects_crc_corruption(self):
        frame = bytearray.fromhex(START_REPORT_HEX)
        frame[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "CRC32"):
            ota.decode_oobe(bytes(frame))


class OrchestratorTests(unittest.TestCase):
    def test_poll_filters_target(self):
        reply = encode_nul_report()
        sock = FakeSocket([(reply, (TARGET, 5000))])
        reports = ota.poll_reports(sock, TARGET, timeout=0.01, poll_interval=0.005)
        self.assertGreaterEqual(len(sock.sent), 1)
        self.assertEqual(sock.sent[0][1], (TARGET, 5000))
        self.assertEqual(reports[0]["report"]["download_progress"], 42)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(IMPL), *args], capture_output=True, text=True, check=False)

    def test_status_is_dry_run_by_default(self):
        result = self.run_cli("status", "--source", SOURCE, "--target", TARGET)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertFalse(output["execute"])
        self.assertEqual(output["request"], {"cmd": "START_REPORT"})

    def test_trigger_is_dry_run_by_default(self):
        result = self.run_cli("trigger", "--source", SOURCE, "--target", TARGET, "--url", OTA_URL)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertFalse(output["execute"])
        self.assertEqual(output["request"], {"cmd": "OTA_UPGRADE", "url": OTA_URL})

    def test_trigger_rejects_https(self):
        result = self.run_cli(
            "trigger", "--source", SOURCE, "--target", TARGET, "--url", "https://198.51.100.30/ct30w.bin"
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("http://", json.loads(result.stderr)["error"])


if __name__ == "__main__":
    unittest.main()
