#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import http.client
import json
import socket
import ssl
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIRMWARE = ROOT / "firmware/x1s-local-1.18.301.rbl"
SHA256 = "0d0d0b63feb0723356c7c64fd2664e8b73f90f711e2cfbdeb926b53fb9799374"
MD5 = "eaa68827e6537ce71521296c32fe0faf"
SIZE = 521_664


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def post(port: int, context: ssl.SSLContext):
    conn = http.client.HTTPSConnection("127.0.0.1", port, timeout=2, context=context)
    conn.request(
        "POST",
        "/fota/chkUpgrade",
        body=b'{"firmwareVersion":"1.0.4"}',
        headers={"Content-Type": "application/json"},
    )
    response = conn.getresponse()
    data = json.loads(response.read())
    transfer = response.getheader("Transfer-Encoding")
    status = response.status
    conn.close()
    return status, transfer, data


def health(port: int, context: ssl.SSLContext) -> str:
    conn = http.client.HTTPSConnection("127.0.0.1", port, timeout=1, context=context)
    conn.request("GET", "/healthz")
    result = conn.getresponse().read().decode().strip()
    conn.close()
    return result


def main() -> int:
    body = FIRMWARE.read_bytes()
    assert len(body) == SIZE
    assert hashlib.sha256(body).hexdigest() == SHA256
    assert hashlib.md5(body).hexdigest() == MD5
    assert body.startswith(b"RBL\x00")
    gpio = json.loads((ROOT / "postflash/x1s_gpio.json").read_text())
    expected_roles = {"6": 18, "7": 19, "8": 1, "10": 6, "11": 9, "24": 3, "26": 17}
    assert {pin: value["role"] for pin, value in gpio["pins"].items()} == expected_roles

    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        cert = work / "cert.pem"
        key = work / "key.pem"
        log = work / "formal.jsonl"
        arm = work / "formal.arm"
        arm.touch()
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes", "-days", "1",
                "-subj", "/CN=cgw.komect.com", "-keyout", str(key), "-out", str(cert),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        tls_port, http_port = free_port(), free_port()
        command = [
            "python3", "-u", str(ROOT / "tools/formal_server.py"),
            "--listen", "127.0.0.1", "--tls-port", str(tls_port), "--http-port", str(http_port),
            "--cert", str(cert), "--key", str(key), "--firmware", str(FIRMWARE),
            "--arm-file", str(arm), "--log", str(log),
            "--download-url", "http://198.51.100.30/x1s-local-1.18.301.rbl",
        ]
        proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        context = ssl._create_unverified_context()
        try:
            for _ in range(80):
                try:
                    if health(tls_port, context) == "ARMED":
                        break
                except Exception:
                    time.sleep(0.05)
            else:
                raise AssertionError("formal server did not start")

            status, transfer, first = post(tls_port, context)
            assert status == 200 and transfer == "chunked"
            assert first == {
                "upgradeAble": 1,
                "otaPolicyServer": "https://fota.komect.com/fota/chkUpgrade",
                "versionType": "1",
                "version": "1.18.301",
                "fileName": "x1s-local-1.18.301.rbl",
                "size": SIZE,
                "md5": MD5,
                "downloadUrl": "http://198.51.100.30/x1s-local-1.18.301.rbl",
            }
            assert not arm.exists()
            assert health(tls_port, context) == "DISARMED"

            download = http.client.HTTPConnection("127.0.0.1", http_port, timeout=3)
            download.request("GET", "/x1s-local-1.18.301.rbl")
            response = download.getresponse()
            downloaded = response.read()
            download.close()
            assert response.status == 200 and downloaded == body

            _, _, second = post(tls_port, context)
            assert second["upgradeAble"] == 0
            rows = [json.loads(line) for line in log.read_text().splitlines()]
            assert [row["event"] for row in rows].count("formal_download") == 1
            modes = [row.get("response_mode") for row in rows if row["event"] == "fota_check"]
            assert modes == ["armed_formal_candidate", "disarmed_no_update"]
        finally:
            proc.terminate()
            proc.wait(timeout=3)
    print("X1S_PUBLIC_PASS firmware=locked one_shot=pass chunked=pass download=exact gpio=verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
