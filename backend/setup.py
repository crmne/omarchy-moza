#!/usr/bin/python3
"""Standard-library-only first-run setup and launcher."""
import importlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {"gi": "python-gobject", "cairo": "python-cairo", "serial": "python-pyserial",
            "yaml": "python-yaml", "evdev": "python-evdev", "psutil": "python-psutil"}
RULE_DIRS = (Path("/etc/udev/rules.d"), Path("/usr/lib/udev/rules.d"))


def probe():
    missing = []
    for module, package in PACKAGES.items():
        try:
            importlib.import_module(module)
        except (ImportError, OSError):
            missing.append(package)
    for namespace, version, package in (("Gtk", "4.0", "gtk4"), ("Adw", "1", "libadwaita")):
        try:
            gi = importlib.import_module("gi")
            gi.require_version(namespace, version)
            importlib.import_module("gi.repository." + namespace)
        except (ImportError, ValueError, OSError):
            missing.append(package)
    rules = not any((directory / "99-boxflat.rules").is_file() for directory in RULE_DIRS)
    binary = ROOT / "bin" / ("omarchy-moza" if os.uname().machine == "x86_64" else "omarchy-moza-" + os.uname().machine)
    return {"packages": missing, "rules": rules, "binary": not binary.is_file()}


def install():
    state = probe()
    if state["binary"]:
        raise SystemExit("Build the Rust backend on this architecture with make build first.")
    print("MOZA setup: install the missing Arch packages and Boxflat device-access rules.", flush=True)
    if state["packages"]:
        subprocess.run(["omarchy", "pkg", "add", *state["packages"]], check=True)
    if state["rules"]:
        # Never replace an existing administrator's rules. Re-check after the sudo prompt.
        subprocess.run(["sudo", "cp", "--update=none", "--preserve=mode",
                        str(ROOT / "vendor/boxflat/udev/99-boxflat.rules"),
                        "/etc/udev/rules.d/99-boxflat.rules"], check=True)
        subprocess.run(["sudo", "udevadm", "control", "--reload-rules"], check=True)
        print("Reconnect your MOZA wheelbase and peripherals to apply device access.", flush=True)
    print("Setup complete. The plugin will start automatically.", flush=True)


def serve():
    while True:
        # A fresh interpreter notices newly installed typelibs and extension modules.
        result = subprocess.run([sys.executable, "-B", "-I", __file__, "--probe"],
                                check=True, capture_output=True, text=True)
        state = json.loads(result.stdout)
        if not (state["packages"] or state["rules"] or state["binary"]):
            os.execv(sys.executable, [sys.executable, "-B", "-I", str(ROOT / "backend/bridge.py")])
        print(json.dumps({"setup": state}), flush=True)
        if select.select([sys.stdin], [], [], 2)[0]:
            line = sys.stdin.readline()
            if not line:
                return
            try:
                if json.loads(line).get("op") == "quit":
                    return
            except (ValueError, AttributeError):
                pass


if __name__ == "__main__":
    if sys.argv[1:] == ["--probe"]:
        print(json.dumps(probe()))
    elif sys.argv[1:] == ["--install"]:
        install()
    else:
        serve()
