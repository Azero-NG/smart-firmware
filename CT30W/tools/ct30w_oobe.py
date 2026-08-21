#!/usr/bin/env python3
"""Minimal CT30W OOBE status/OTA orchestrator.

Dry-run is the default. UDP traffic is emitted only with ``--execute``.
"""

import argparse
import ipaddress
import json
import socket
import struct
import sys
import time
import zlib
from urllib.parse import urlsplit

from Crypto.Cipher import AES

KEY = b"e8#M9bUq@z)H^S$l"
MAGIC = 0x8572
OOBE_PORT = 5000


def _pad_pkcs7(data):
    amount = AES.block_size - (len(data) % AES.block_size)
    return data + bytes([amount]) * amount


def _unpad_pkcs7(data):
    if not data:
        raise ValueError("empty plaintext")
    amount = data[-1]
    if amount < 1 or amount > AES.block_size:
        raise ValueError("bad PKCS#7 padding")
    if data[-amount:] != bytes([amount]) * amount:
        raise ValueError("bad PKCS#7 padding")
    return data[:-amount]


def encode_oobe(payload):
    if not isinstance(payload, dict):
        raise TypeError("OOBE payload must be a JSON object")
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = AES.new(KEY, AES.MODE_ECB).encrypt(_pad_pkcs7(plaintext))
    total_length = 8 + len(ciphertext)
    if total_length > 0xFFFF:
        raise ValueError("OOBE frame exceeds u16 length")
    crc = zlib.crc32(ciphertext) & 0xFFFFFFFF
    return struct.pack("<HHI", MAGIC, total_length, crc) + ciphertext


def decode_oobe(frame):
    if len(frame) < 8:
        raise ValueError("short OOBE frame")
    magic, total_length, expected_crc = struct.unpack_from("<HHI", frame)
    if magic != MAGIC:
        raise ValueError("bad OOBE magic 0x%04x" % magic)
    if total_length != len(frame):
        raise ValueError("OOBE length mismatch: header=%d actual=%d" % (total_length, len(frame)))
    ciphertext = frame[8:]
    actual_crc = zlib.crc32(ciphertext) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise ValueError(
            "bad OOBE CRC32: expected=0x%08x actual=0x%08x" % (expected_crc, actual_crc)
        )
    if not ciphertext or len(ciphertext) % AES.block_size:
        raise ValueError("OOBE ciphertext is not AES-block aligned")
    plaintext = AES.new(KEY, AES.MODE_ECB).decrypt(ciphertext)
    plaintext = _unpad_pkcs7(plaintext)
    json_bytes = plaintext.split(b"\x00", 1)[0]
    try:
        payload = json.loads(json_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid OOBE JSON: %s" % exc) from exc
    if not isinstance(payload, dict):
        raise ValueError("OOBE JSON is not an object")
    return payload


def validate_http_url(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid OTA URL: %s" % exc) from exc
    if parsed.scheme != "http":
        raise ValueError("stock OTA URL must use http://")
    if not parsed.hostname:
        raise ValueError("stock OTA URL must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("stock OTA URL must not include user information")
    if parsed.fragment:
        raise ValueError("stock OTA URL must not include a fragment")
    if port is not None and not (1 <= port <= 65535):
        raise ValueError("stock OTA URL port is out of range")
    return value


def validate_ipv4(value, field):
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("%s must be an IPv4 address" % field) from exc
    if address.version != 4:
        raise ValueError("%s must be an IPv4 address" % field)
    return str(address)


def poll_reports(sock, target, timeout, poll_interval):
    request = encode_oobe({"cmd": "START_REPORT"})
    destination = (target, OOBE_PORT)
    deadline = time.monotonic() + max(0.0, timeout)
    next_poll = 0.0
    reports = []
    seen = set()
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_poll:
            sock.sendto(request, destination)
            next_poll = now + max(0.001, poll_interval)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sock.settimeout(min(0.25, max(0.001, remaining)))
        try:
            frame, peer = sock.recvfrom(4096)
        except socket.timeout:
            continue
        if peer[0] != target:
            continue
        try:
            payload = decode_oobe(frame)
        except ValueError:
            continue
        if payload.get("cmd") != "REPORT":
            continue
        record = {"peer": "%s:%d" % (peer[0], peer[1]), "report": payload}
        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if canonical not in seen:
            seen.add(canonical)
            reports.append(record)
    return reports


def emit(payload, stream=sys.stdout):
    stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    stream.flush()


def make_socket(source, source_port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((source, source_port))
    return sock


def request_for_args(args):
    if args.action == "status":
        return {"cmd": "START_REPORT"}
    return {"cmd": "OTA_UPGRADE", "url": validate_http_url(args.url)}


def dry_run_record(args, request, frame):
    return {
        "action": args.action,
        "destination": "%s:%d" % (args.target, OOBE_PORT),
        "event": "dry_run",
        "execute": False,
        "frame_hex": frame.hex(),
        "frame_size": len(frame),
        "request": request,
        "source": "%s:%d" % (args.source, args.source_port),
    }


def run_status(args, request, frame):
    if not args.execute:
        emit(dry_run_record(args, request, frame))
        return 0
    sock = make_socket(args.source, args.source_port)
    try:
        reports = poll_reports(sock, args.target, args.timeout, args.poll_interval)
    finally:
        sock.close()
    for record in reports:
        emit({"action": "status", "event": "report", **record})
    emit({"action": "status", "event": "done", "reports": len(reports), "target": args.target})
    return 0 if reports else 3


def run_trigger(args, request, frame):
    if not args.execute:
        emit(dry_run_record(args, request, frame))
        return 0
    sock = make_socket(args.source, args.source_port)
    try:
        sent = sock.sendto(frame, (args.target, OOBE_PORT))
        emit(
            {
                "action": "trigger",
                "bytes": sent,
                "destination": "%s:%d" % (args.target, OOBE_PORT),
                "event": "sent",
                "url": args.url,
            }
        )
        reports = poll_reports(sock, args.target, args.timeout, args.poll_interval)
    finally:
        sock.close()
    for record in reports:
        emit({"action": "trigger", "event": "report", **record})
    emit(
        {
            "action": "trigger",
            "event": "done",
            "reports": len(reports),
            "target": args.target,
            "url": args.url,
        }
    )
    return 0


def add_common_arguments(parser):
    parser.add_argument("--source", required=True, help="local IPv4 bind address")
    parser.add_argument("--source-port", type=int, default=OOBE_PORT)
    parser.add_argument("--target", required=True, help="CT30W IPv4 address")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--execute", action="store_true", help="emit UDP packets; omitted means deterministic dry-run")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    status = subparsers.add_parser("status", help="poll OOBE REPORT")
    add_common_arguments(status)
    trigger = subparsers.add_parser("trigger", help="send OTA_UPGRADE then poll REPORT")
    add_common_arguments(trigger)
    trigger.add_argument("--url", required=True, help="stock OTA package HTTP URL")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.source = validate_ipv4(args.source, "source")
        args.target = validate_ipv4(args.target, "target")
        if not (0 <= args.source_port <= 65535):
            raise ValueError("source-port is out of range")
        if args.timeout < 0:
            raise ValueError("timeout must be non-negative")
        if args.poll_interval <= 0:
            raise ValueError("poll-interval must be positive")
        request = request_for_args(args)
        frame = encode_oobe(request)
    except ValueError as exc:
        emit({"error": str(exc), "event": "argument_error"}, stream=sys.stderr)
        return 2
    try:
        if args.action == "status":
            return run_status(args, request, frame)
        return run_trigger(args, request, frame)
    except OSError as exc:
        emit({"error": str(exc), "event": "runtime_error", "action": args.action}, stream=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
