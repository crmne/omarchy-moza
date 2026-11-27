#!/usr/bin/python3
"""Standard-library-only first-run setup and launcher."""
import importlib
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {"gi": "python-gobject", "cairo": "python-cairo", "serial": "python-pyserial",
            "yaml": "python-yaml", "evdev": "python-evdev", "psutil": "python-psutil"}
# In udev's order of precedence: a file in /etc overrides one of the same name.
RULE_DIRS = (Path("/etc/udev/rules.d"), Path("/usr/lib/udev/rules.d"))
RULES = "70-omarchy-moza.rules"
BOXFLAT_RULES = "99-boxflat.rules"
MODE = re.compile(r'\bMODE\s*:?=\s*"?([0-7]+)')


def boxflat_rules():
    """The Boxflat rule file udev uses, if any."""
    for directory in RULE_DIRS:
        path = directory / BOXFLAT_RULES
        if path.exists() or path.is_symlink():
            return path
    return None


def world_writable(path):
    """Whether a rule file sets a device mode that every local user can write."""
    try:
        lines = path.read_text(errors="replace").splitlines() if path else []
    except OSError:
        return False
    return any(int(mode, 8) & 0o002 for line in lines if not line.lstrip().startswith("#")
               for mode in MODE.findall(line))


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
    # Boxflat's own rule made MOZA serial devices writable by every user; it
    # is replaced, and access goes to the user at the seat instead.
    rules = not any((directory / RULES).is_file() for directory in RULE_DIRS) \
        or world_writable(boxflat_rules())
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
        # Never replace an administrator's own rules. Re-check after the sudo prompt.
        subprocess.run(["sudo", "cp", "--update=none", "--preserve=mode",
                        str(ROOT / "udev" / RULES), "/etc/udev/rules.d/" + RULES], check=True)
        if world_writable(boxflat_rules()):
            # A file in /etc also overrides a package's rule of the same name.
            subprocess.run(["sudo", "install", "-m", "0644", str(ROOT / "udev" / BOXFLAT_RULES),
                            "/etc/udev/rules.d/" + BOXFLAT_RULES], check=True)
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
