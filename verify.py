#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import py_compile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

EXPECTED_FILES = (
    "README.md",
    "LICENSE",
    "MANIFEST.sha256",
    "CT30W/README.md",
    "CT30W/requirements.txt",
    "CT30W/verify.py",
    "CT30W/firmware/CT30W_ESPHome_final_native.bin",
    "CT30W/firmware/ORVIBO_CT30W_v2.0.15_stock_rollback.bin",
    "CT30W/esphome/transition.yaml",
    "CT30W/esphome/final.yaml",
    "CT30W/esphome/boot_compat.h",
    "CT30W/esphome/eboot_sector.h",
    "CT30W/esphome/eboot_migration.h",
    "CT30W/esphome/secrets.example.yaml",
    "CT30W/esphome/components/ct30w_stock_ota/__init__.py",
    "CT30W/esphome/components/ct30w_stock_ota/ct30w_stock_ota.h",
    "CT30W/tools/build_transition.py",
    "CT30W/tools/build_transition.sh",
    "CT30W/tools/ct30w_oobe.py",
    "CT30W/tools/test_ct30w_oobe.py",
    "CT30W/tools/paced_server.go",
    "CT30W/tools/paced_server_test.go",
    "CT30W/tools/upload_uncompressed.py",
    "CT30W/tools/invoke_service.py",
    "X1S/README.md",
    "X1S/verify.py",
    "X1S/config.example.env",
    "X1S/firmware/x1s-local-1.18.301.rbl",
    "X1S/postflash/x1s_gpio.json",
    "X1S/postflash/x1s_led_off.json",
    "X1S/tools/formal_server.py",
    "X1S/tools/apply_gpio.py",
    "X1S/tools/setup_adapter.sh",
    "X1S/tools/cleanup_adapter.sh",
    "X1S/tools/openwrt_dhcp_setup.sh",
    "X1S/tools/openwrt_dhcp_cleanup.sh",
    "X1S/tools/arm.sh",
    "X1S/tools/refresh_fota_ips.sh",
)

EXPECTED_BINARIES = {
    "X1S/firmware/x1s-local-1.18.301.rbl": (
        521_664,
        "0d0d0b63feb0723356c7c64fd2664e8b73f90f711e2cfbdeb926b53fb9799374",
    ),
    "CT30W/firmware/CT30W_ESPHome_final_native.bin": (
        441_520,
        "2a8fd3be52b4ecee66a4d274ea1966b4e76bac85b02c6274e4bda4a3b883e786",
    ),
    "CT30W/firmware/ORVIBO_CT30W_v2.0.15_stock_rollback.bin": (
        561_384,
        "5029cddcb04249535c4e6eb11eea65d118f57725df7a75dbc6303a9596622d8e",
    ),
}

FORBIDDEN_TEXT = (
    "/Users/azero",
    "192.168.50.",
    "192.168.52.",
    "bc:ff:4d:",
    "BC:FF:4D:",
    "c8:47:8c:",
    "C8:47:8C:",
    "deliverables/",
    "work/",
)

TEXT_SUFFIXES = {".md", ".txt", ".py", ".sh", ".go", ".yaml", ".yml", ".json", ".env"}
SKIP_PARTS = {".venv", "venv", "build", ".esphome", "__pycache__", ".git"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    raise AssertionError(message)


def check_required_files() -> None:
    missing = [name for name in EXPECTED_FILES if not (ROOT / name).is_file()]
    if missing:
        fail("missing required files: " + ", ".join(missing))


def check_binaries() -> None:
    for name, (expected_size, expected_sha) in EXPECTED_BINARIES.items():
        path = ROOT / name
        actual_size = path.stat().st_size
        actual_sha = sha256(path)
        if actual_size != expected_size or actual_sha != expected_sha:
            fail(
                f"binary mismatch {name}: size={actual_size}/{expected_size} "
                f"sha256={actual_sha}/{expected_sha}"
            )


def is_generated(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts)


def check_manifest() -> None:
    manifest = {}
    for line in (ROOT / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            manifest[parts[1].strip()] = parts[0].strip()
    expected = {name: digest for name, (_size, digest) in EXPECTED_BINARIES.items()}
    if manifest != expected:
        fail(f"manifest mismatch: {manifest!r} != {expected!r}")


def iter_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.name == Path(__file__).name or is_generated(path):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"requirements.txt", "LICENSE"}:
            yield path


def check_sanitized_and_self_contained() -> None:
    for path in iter_text_files():
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_TEXT:
            if forbidden in text:
                fail(f"forbidden reference {forbidden!r} in {path.relative_to(ROOT)}")
    for guide in (ROOT / "CT30W/README.md", ROOT / "X1S/README.md"):
        text = guide.read_text(encoding="utf-8")
        if "<" not in text or ">" not in text:
            fail(f"guide lacks explicit placeholders: {guide}")


def check_guides() -> None:
    ct = (ROOT / "CT30W/README.md").read_text(encoding="utf-8")
    for needle in (
        "CT30_XY",
        "v2.0.15",
        "ESPHome 2026.7.4",
        "CT30W-Open-Setup",
        "migrate_eboot",
        "stock_boot_rollback",
        "不要继续",
    ):
        if needle not in ct:
            fail(f"CT30W guide missing {needle!r}")


def check_python() -> None:
    for path in ROOT.rglob("*.py"):
        if is_generated(path):
            continue
        py_compile.compile(str(path), doraise=True)


def check_shell() -> None:
    for path in ROOT.rglob("*.sh"):
        if is_generated(path):
            continue
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        if result.returncode:
            fail(f"bash -n failed for {path.relative_to(ROOT)}: {result.stderr}")


def check_executable_bits() -> None:
    shell_paths = [path for path in ROOT.rglob("*.sh") if not is_generated(path)]
    for path in shell_paths + [ROOT / "verify.py", ROOT / "CT30W/verify.py", ROOT / "X1S/verify.py"]:
        if not os.access(path, os.X_OK):
            fail(f"expected executable bit: {path.relative_to(ROOT)}")


def main() -> int:
    checks = [
        check_required_files,
        check_binaries,
        check_manifest,
        check_sanitized_and_self_contained,
        check_guides,
        check_python,
        check_shell,
        check_executable_bits,
    ]
    for check in checks:
        check()
    print(f"VERIFY_PASS: checks={len(checks)} files={len(EXPECTED_FILES)} binaries={len(EXPECTED_BINARIES)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"VERIFY_FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
