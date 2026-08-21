#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPECTED = {
    "firmware/CT30W_ESPHome_final_native.bin": (441_520, "2a8fd3be52b4ecee66a4d274ea1966b4e76bac85b02c6274e4bda4a3b883e786"),
    "firmware/ORVIBO_CT30W_v2.0.15_stock_rollback.bin": (561_384, "5029cddcb04249535c4e6eb11eea65d118f57725df7a75dbc6303a9596622d8e"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, cwd=None, env=None):
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)
    if result.returncode:
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def main() -> int:
    for name, (size, digest) in EXPECTED.items():
        path = ROOT / name
        assert path.stat().st_size == size, name
        assert sha(path) == digest, name
    transition = (ROOT / "esphome/transition.yaml").read_text()
    final = (ROOT / "esphome/final.yaml").read_text()
    assert "migrate_eboot" in transition and "stock_boot_rollback" in transition
    assert "CT30W-Open-Setup" in transition and "!secret wifi_ssid" in transition
    assert "CT30W-Open-Setup" in final and "password:" not in final
    venv_python = ROOT / ".venv/bin/python"
    if not venv_python.is_file():
        print("CT30W_PUBLIC_FAIL create .venv with Python 3.12-3.14 and install requirements.txt", file=sys.stderr)
        return 2
    run([str(venv_python), str(ROOT / "tools/test_ct30w_oobe.py")])
    if subprocess.run(["sh", "-c", "command -v go >/dev/null"], check=False).returncode == 0:
        env = dict(os.environ)
        env["GO111MODULE"] = "off"
        run(["go", "test", "-v"], cwd=ROOT / "tools", env=env)
        go = "pass"
    else:
        go = "skipped(no-go)"
    print(f"CT30W_PUBLIC_PASS binaries=2 oobe=pass paced_server={go}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
