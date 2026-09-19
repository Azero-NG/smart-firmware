#!/usr/bin/env python3
"""One-shot X1S formal FOTA candidate server."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import ssl
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


EXPECTED_FIRMWARE_SHA256 = "0d0d0b63feb0723356c7c64fd2664e8b73f90f711e2cfbdeb926b53fb9799374"
EXPECTED_FIRMWARE_MD5 = "eaa68827e6537ce71521296c32fe0faf"
EXPECTED_FIRMWARE_SIZE = 521_664
FIRMWARE_NAME = "x1s-local-1.18.301.rbl"
PRODUCT_VERSION = "1.18.301"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def load_firmware(path: Path) -> bytes:
    body = path.read_bytes()
    if len(body) != EXPECTED_FIRMWARE_SIZE:
        raise SystemExit(
            f"firmware size mismatch: expected {EXPECTED_FIRMWARE_SIZE}, got {len(body)}"
        )
    digest = hashlib.sha256(body).hexdigest()
    if digest != EXPECTED_FIRMWARE_SHA256:
        raise SystemExit(
            f"firmware SHA-256 mismatch: expected {EXPECTED_FIRMWARE_SHA256}, got {digest}"
        )
    md5 = hashlib.md5(body).hexdigest()
    if md5 != EXPECTED_FIRMWARE_MD5:
        raise SystemExit(f"firmware MD5 mismatch: expected {EXPECTED_FIRMWARE_MD5}, got {md5}")
    return body


class State:
    def __init__(
        self,
        arm_file: Path,
        log_file: Path,
        download_url: str,
        firmware: bytes,
    ):
        self.arm_file = arm_file
        self.log_file = log_file
        self.download_url = download_url
        self.firmware = firmware
        self.lock = threading.Lock()
        log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **fields: object) -> None:
        row = {"utc": utc_now(), "event": event, **fields}
        with self.lock, self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")

    def consume_arm(self) -> bool:
        with self.lock:
            if not self.arm_file.exists():
                return False
            self.arm_file.unlink()
            return True


class Handler(BaseHTTPRequestHandler):
    state: State
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: object) -> None:
        return

    def body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def setup(self) -> None:
        super().setup()
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass

    def send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            chunk_size = 4096
            for offset in range(0, len(body), chunk_size):
                self.wfile.write(body[offset : offset + chunk_size])

    def send_chunked_json(self, body: bytes) -> None:
        headers = (
            "HTTP/1.1 200 \r\n"
            f"Date: {self.date_time_string()}\r\n"
            "Content-Type: application/json\r\n"
            "Transfer-Encoding: chunked\r\n"
            "Connection: keep-alive\r\n"
            "Vary: Accept-Encoding\r\n"
            "Server: fweb\r\n\r\n"
        ).encode()
        chunked = f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
        self.connection.sendall(headers + chunked)

    def do_POST(self) -> None:
        request = self.body()
        armed = self.path == "/fota/chkUpgrade" and self.state.consume_arm()
        if armed:
            result = {
                "upgradeAble": 1,
                "otaPolicyServer": "https://fota.komect.com/fota/chkUpgrade",
                "versionType": "1",
                "version": PRODUCT_VERSION,
                "fileName": FIRMWARE_NAME,
                "size": EXPECTED_FIRMWARE_SIZE,
                "md5": EXPECTED_FIRMWARE_MD5,
                "downloadUrl": self.state.download_url,
            }
            mode = "armed_formal_candidate"
        else:
            result = {
                "upgradeAble": 0,
                "otaPolicyServer": "https://fota.komect.com/fota/chkUpgrade",
                "versionType": None,
                "version": None,
                "fileName": None,
                "size": None,
                "md5": None,
                "downloadUrl": None,
            }
            mode = "disarmed_no_update"
        response = json.dumps(result, separators=(",", ":")).encode()
        self.state.log(
            "fota_check",
            client=self.client_address[0],
            request_sha256=hashlib.sha256(request).hexdigest(),
            response_mode=mode,
        )
        self.send_chunked_json(response)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            status = b"ARMED\n" if self.state.arm_file.exists() else b"DISARMED\n"
            self.send_bytes(200, "text/plain", status)
            return
        if self.path != f"/{FIRMWARE_NAME}":
            self.send_bytes(404, "text/plain", b"not found\n")
            return
        self.state.log(
            "formal_download",
            client=self.client_address[0],
            length=len(self.state.firmware),
            sha256=EXPECTED_FIRMWARE_SHA256,
            md5=EXPECTED_FIRMWARE_MD5,
            rbl_magic_valid=self.state.firmware.startswith(b"RBL\x00"),
        )
        self.send_bytes(200, "application/octet-stream", self.state.firmware)

    do_HEAD = do_GET


def serve(server: ThreadingHTTPServer) -> None:
    server.serve_forever(poll_interval=0.2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", default="0.0.0.0")
    parser.add_argument("--tls-port", type=int, default=16443)
    parser.add_argument("--http-port", type=int, default=80)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--firmware", required=True, type=Path)
    parser.add_argument("--arm-file", default="/run/x1s-fota-formal.arm")
    parser.add_argument("--log", default="/opt/x1s-ota/evidence/formal.jsonl")
    parser.add_argument("--download-url", required=True)
    args = parser.parse_args()

    firmware = load_firmware(args.firmware)
    state = State(Path(args.arm_file), Path(args.log), args.download_url, firmware)
    Handler.state = state
    tls_server = ThreadingHTTPServer((args.listen, args.tls_port), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    for ciphers in (
        "AES256-SHA256:AES128-SHA:@SECLEVEL=0",
        "AES256-SHA256:AES128-SHA",
        "DEFAULT",
    ):
        try:
            context.set_ciphers(ciphers)
            break
        except ssl.SSLError:
            continue
    context.load_cert_chain(args.cert, args.key)
    tls_server.socket = context.wrap_socket(tls_server.socket, server_side=True)
    http_server = ThreadingHTTPServer((args.listen, args.http_port), Handler)
    thread = threading.Thread(target=serve, args=(http_server,), daemon=True)
    thread.start()
    state.log(
        "formal_ready",
        tls_port=args.tls_port,
        http_port=args.http_port,
        firmware_sha256=EXPECTED_FIRMWARE_SHA256,
        firmware_md5=EXPECTED_FIRMWARE_MD5,
        firmware_size=EXPECTED_FIRMWARE_SIZE,
        product_version=PRODUCT_VERSION,
        download_url=args.download_url,
    )
    try:
        serve(tls_server)
    finally:
        http_server.shutdown()
        tls_server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
