#!/usr/bin/env python3
"""Build/inspect the CT30W stock-compatible first-hop wrapper."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path

METADATA_SIZE = 0x24
STAGING_SIZE = 0xFA000
PRODUCT = b"CT30_XY\0"


def sdk_crc32(data: bytes) -> int:
    crc = zlib.crc32(data) & 0xFFFFFFFF
    return crc ^ 0xFFFFFFFF if crc & 0x80000000 else crc + 1


def inspect_v2(body: bytes) -> dict:
    if len(body) < 24 or body[0] != 0xEA:
        raise ValueError("not an ESP8266 v2 image")
    irom_length = struct.unpack_from("<I", body, 12)[0]
    nested = 16 + irom_length
    if nested + 8 > len(body) or body[nested] != 0xE9:
        raise ValueError("missing nested ESP8266 v1 image")
    count = body[nested + 1]
    if not 1 <= count <= 16:
        raise ValueError("invalid segment count")
    cursor = nested + 8
    checksum = 0xEF
    for _ in range(count):
        if cursor + 8 > len(body):
            raise ValueError("truncated segment header")
        _address, length = struct.unpack_from("<II", body, cursor)
        start, end = cursor + 8, cursor + 8 + length
        if end > len(body):
            raise ValueError("truncated segment")
        for value in body[start:end]:
            checksum ^= value
        cursor = end
    checksum_offset = ((cursor + 16) // 16) * 16 - 1
    exact_length = checksum_offset + 5
    if exact_length > len(body):
        raise ValueError("missing image checksum or SDK CRC footer")
    stored_sdk_crc = struct.unpack_from("<I", body, exact_length - 4)[0]
    return {
        "flash_mode": body[2],
        "flash_size_frequency": body[3],
        "checksum_valid": body[checksum_offset] == checksum,
        "sdk_crc32_valid": stored_sdk_crc == sdk_crc32(body[: exact_length - 4]),
        "exact_length": exact_length,
    }


def exact_v2_image(blob: bytes) -> bytes:
    parsed = inspect_v2(blob)
    body = blob[: parsed["exact_length"]]
    parsed = inspect_v2(body)
    if len(body) % 4:
        raise ValueError("ESP8266 v2 image length is not 4-byte aligned")
    if not parsed["checksum_valid"] or not parsed["sdk_crc32_valid"]:
        raise ValueError("ESP8266 image checksum/SDK CRC invalid")
    if parsed["flash_mode"] != 3 or parsed["flash_size_frequency"] != 0x50:
        raise ValueError("image must be ESP8266 v2 DOUT/40MHz/2MiB-c1")
    if len(body) > STAGING_SIZE:
        raise ValueError("image exceeds CT30W staging slot")
    return body


def build_wrapper(candidate: bytes) -> bytes:
    body = exact_v2_image(candidate)
    metadata = bytearray(METADATA_SIZE)
    struct.pack_into("<III", metadata, 0, len(body), zlib.crc32(body) & 0xFFFFFFFF, 1)
    metadata[12 : 12 + len(PRODUCT)] = PRODUCT
    return bytes(metadata) + body


def inspect_wrapper(wrapper: bytes) -> dict:
    if len(wrapper) < METADATA_SIZE:
        raise ValueError("wrapper shorter than metadata")
    body = wrapper[METADATA_SIZE:]
    size, crc, fin = struct.unpack_from("<III", wrapper)
    product = wrapper[12:METADATA_SIZE].split(b"\0", 1)[0]
    parsed = inspect_v2(body)
    accepted = (
        size == len(body)
        and crc == (zlib.crc32(body) & 0xFFFFFFFF)
        and fin == 1
        and product == b"CT30_XY"
        and parsed["exact_length"] == len(body)
        and parsed["checksum_valid"]
        and parsed["sdk_crc32_valid"]
        and parsed["flash_mode"] == 3
        and parsed["flash_size_frequency"] == 0x50
        and len(body) <= STAGING_SIZE
    )
    return {
        "accepted": accepted,
        "product": product.decode("ascii", "replace"),
        "body_size": len(body),
        "body_crc32": f"{zlib.crc32(body) & 0xFFFFFFFF:08x}",
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "wrapper_size": len(wrapper),
        "wrapper_sha256": hashlib.sha256(wrapper).hexdigest(),
        "fin": fin,
        "image": parsed,
    }


def file_info(path: Path) -> dict:
    body = path.read_bytes()
    return {"path": str(path), "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--candidate-v2", required=True, type=Path)
    build.add_argument("--native", required=True, type=Path)
    build.add_argument("--output", required=True, type=Path)
    build.add_argument("--metadata-output", required=True, type=Path)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("wrapper", type=Path)
    args = parser.parse_args()

    if args.command == "inspect":
        result = inspect_wrapper(args.wrapper.read_bytes())
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["accepted"] else 2

    native = args.native.read_bytes()
    wrapper = build_wrapper(args.candidate_v2.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(wrapper)
    result = {
        "stock_wrapper": inspect_wrapper(wrapper),
        "native": {
            **file_info(args.native),
            "crc32": f"{zlib.crc32(native) & 0xFFFFFFFF:08x}",
        },
        "candidate_v2": file_info(args.candidate_v2),
    }
    args.metadata_output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
