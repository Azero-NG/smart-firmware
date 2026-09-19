#!/usr/bin/env python3
import argparse
import json
import pathlib
import re
import urllib.parse
import urllib.request


def fetch(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=8) as response:
        return response.status, response.read().decode(errors="replace")


def run_command(base_url: str, command: str, label: str) -> None:
    query = urllib.parse.urlencode({"cmnd": command})
    status, body = fetch(f"{base_url}/cm?{query}")
    compact = " ".join(body.split())
    print(f"COMMAND {label} status={status} result={compact}")


def build_pin_query(pins: dict) -> str:
    fields = []
    for pin, value in pins.items():
        fields.extend(
            (
                (pin, value["role"]),
                (f"r{pin}", value["channel"]),
                (f"e{pin}", value["channel2"]),
            )
        )
    return urllib.parse.urlencode(fields)


def parse_pin_page(text: str, pins: dict) -> dict:
    actual = {}
    for pin in pins:
        match = re.search(
            rf'f\("P{pin}[^\"]*",{pin},(\d+),\s*\d+,(null|\d+),(null|\d+),',
            text,
        )
        if not match:
            raise RuntimeError(f"P{pin} missing from verification page")
        role_text, channel_text, channel2_text = match.groups()
        role = int(role_text)
        channel = None if channel_text == "null" else int(channel_text)
        channel2 = None if channel2_text == "null" else int(channel2_text)
        actual[pin] = {
            "role": role,
            "channel": channel,
            "channel2": channel2,
        }
    return actual


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=pathlib.Path)
    parser.add_argument("--url")
    parser.add_argument("--snapshot", type=pathlib.Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    query = build_pin_query(config["pins"])

    if not args.url:
        print(query)
        return

    base_url = args.url.rstrip("/")
    run_command(base_url, config["pre_apply_command"], "pre_apply")
    status, body = fetch(f"{base_url}/cfg_pins?{query}")
    result = re.search(r"Pins update - [^<]+", body)
    print(f"CONFIG status={status} result={result.group(0) if result else 'missing'}")
    run_command(base_url, config["post_apply_command"], "post_apply")
    status, verify_body = fetch(f"{base_url}/cfg_pins")
    actual = parse_pin_page(verify_body, config["pins"])
    for pin, expected in config["pins"].items():
        observed = actual[pin]
        if observed["role"] != expected["role"]:
            raise RuntimeError(f"role verification failed P{pin} expected={expected} actual={observed}")
        for field in ("channel", "channel2"):
            if observed[field] is not None and observed[field] != expected[field]:
                raise RuntimeError(
                    f"{field} verification failed P{pin} expected={expected} actual={observed}"
                )
    if args.snapshot:
        args.snapshot.write_text(verify_body)
    rendered = ",".join(
        f"P{pin}={value['role']}/{value['channel']}/{value['channel2']}"
        for pin, value in actual.items()
    )
    print(f"VERIFY status={status} roles={rendered}")


if __name__ == "__main__":
    main()
