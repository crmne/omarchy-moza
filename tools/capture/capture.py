#!/usr/bin/python3
"""Capture production QML with sample data, never connecting to real devices.

Run through gpu-lock. Requires the installed Omarchy shell, GTK dependencies,
Quickshell and an NVIDIA/OpenGL-capable display. Only screenshot-host copies
replace layer-shell window plumbing and disable the production backend Process.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def fixtures():
    from backend.bridge import Bridge, Gtk, Adw, GLib
    Gtk.init(); Adw.init()
    bridge = Bridge(True)
    context = GLib.MainContext.default()
    bridge.panels["Home"]._get_rotation_limit(450)
    while context.pending(): context.iteration(False)
    bridge.rev.status = dict(connected=True, game="Automobilista 2", rpm=6420,
                             redline=6800, mask=255, test=False, unavailableListeners=[])
    bridge.opened = True
    result = {}
    for name in ["Home", "Base", "Rev lights"]:
        bridge.focus = name
        doc = bridge.document()
        for page in doc["pages"]:
            for group in page["groups"]:
                if group["title"] == "Handbrake": group["visible"] = False
                for row in group["rows"]:
                    if row["title"] == "Steering position": row["value"] = "−18°"
                    if row["title"] == "E-Stop status": row["visible"] = False
                    if row["title"] == "Wheel Rotation Angle": row["value"] = 900
                    if row["title"] in ["Throttle input", "Brake input", "Clutch input"]:
                        row["value"] = int(row["max"] * {"Throttle input": .72, "Brake input": .26, "Clutch input": .08}[row["title"]])
        doc["panels"] = [dict(p, connected=p["name"] in ["Home", "Base", "Wheel", "Pedals", "Presets", "Generic Devices", "Other"]) for p in doc["panels"]]
        result[name] = doc
    return result


def wait_for(predicate, description, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate(): return
        time.sleep(.1)
    raise RuntimeError("Timed out: " + description)


def complete_png(path):
    if not path.exists(): return False
    with path.open("rb") as image:
        if path.stat().st_size < 12: return False
        image.seek(-12, 2)
        return image.read() == b'\x00\x00\x00\x00IEND\xaeB`\x82'


def main():
    samples = fixtures()
    output = ROOT / "screenshots"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="moza-capture-") as work_path:
        work = Path(work_path)
        home, shell, runtime = (work / name for name in ["home", "shell", "runtime"])
        runtime.mkdir(mode=0o700)
        shell.mkdir()
        theme = home / ".local/state/omarchy/current/next-theme"
        theme.mkdir(parents=True)
        shutil.copy("/usr/share/omarchy/themes/ristretto/colors.toml", theme / "colors.toml")
        env = dict(HOME=str(home), PATH="/usr/bin:/bin", LANG="C.UTF-8",
                   XDG_RUNTIME_DIR=str(runtime), OMARCHY_PATH="/usr/share/omarchy",
                   DISPLAY=os.environ.get("DISPLAY", ":0"))
        if "XAUTHORITY" in os.environ: env["XAUTHORITY"] = os.environ["XAUTHORITY"]
        subprocess.run(["omarchy-theme-set-templates"], env=env, check=True, stdout=subprocess.DEVNULL)
        shutil.copytree(theme, theme.with_name("theme"))
        fonts = home / ".config/fontconfig"
        fonts.mkdir(parents=True)
        (fonts / "fonts.conf").write_text('''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>
<match target="pattern"><test name="family"><string>monospace</string></test>
<edit name="family" mode="assign" binding="strong"><string>JetBrainsMono Nerd Font</string></edit></match>
</fontconfig>''')
        for name in ["Commons", "Ui"]:
            shutil.copytree(Path("/usr/share/omarchy/shell") / name, shell / name)
        subprocess.run([sys.executable, TOOLS / "offscreen_keyboardpanel.py",
                        shell / "Ui/KeyboardPanel.qml", shell / "Ui/KeyboardPanel.qml"], check=True)
        plugin = work / "plugin"
        plugin.mkdir()
        for name in ["MozaPanel.qml", "MozaService.qml"]: shutil.copy(ROOT / name, plugin / name)
        shutil.copytree(ROOT / "controls", plugin / "controls")
        service = plugin / "MozaService.qml"
        text = service.read_text()
        assert text.count("running: true") == 1
        service.write_text(text.replace("running: true", "running: false"))
        keyboard = shell / "Ui/KeyboardPanel.qml"
        keyboard.write_text(keyboard.read_text().replace("id: root", "id: root\n  property alias captureCard: card", 1))
        shutil.copy(TOOLS / "shell.qml", shell / "shell.qml")
        (work / "fixtures.json").write_text(json.dumps(samples))
        (work / "screen.json").write_text(json.dumps({"screens": [dict(name="CAPTURE", x=0, y=0, width=2800, height=1800, logicalDpi=96, logicalBaseDpi=96, dpr=1)]}))
        env.update(QT_QPA_PLATFORM=f"offscreen:configfile={work / 'screen.json'}",
                   QT_QUICK_BACKEND="rhi", QSG_RHI_BACKEND="opengl", QSG_INFO="1", QT_SCALE_FACTOR="2",
                   MOZA_PLUGIN=str(plugin), MOZA_FIXTURES=str(work / "fixtures.json"), MOZA_OUTPUT=str(output),
                   MOZA_WALLPAPER="/usr/share/omarchy/themes/ristretto/backgrounds/0-launch.png")
        log = work / "qs.log"
        def call(method, *args):
            result = subprocess.run(["qs", "ipc", "-p", str(shell), "call", "--", "capture", method, *map(str, args)], env=env, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                if method != "ready": print(result.stderr, file=sys.stderr, flush=True)
                return ""
            return result.stdout.strip()
        with log.open("w") as stream:
            proc = subprocess.Popen(["qs", "-p", str(shell)], env=env, stdout=stream, stderr=subprocess.STDOUT)
            try:
                wait_for(lambda: call("ready") == "true", "capture host")
                for page, filename in [("Home", "inputs.png"), ("Rev lights", "rev-lights.png"), ("Base", "base.png")]:
                    print(call("displayPage", page), file=sys.stderr, flush=True)
                    time.sleep(.7)
                    path = output / filename
                    path.unlink(missing_ok=True)
                    result = call("grab", str(path))
                    if result != "ok": raise RuntimeError(result)
                    wait_for(lambda: complete_png(path), filename)
                    print(path, file=sys.stderr, flush=True)
                hidden = json.loads(call("connection", "false"))
                shown = json.loads(call("connection", "true"))
                assert not hidden["visible"] and not hidden["open"] and hidden["ready"], hidden
                assert shown["visible"] and shown["ready"], shown
                call("preparePreview")
                time.sleep(.7)
                preview = ROOT / "preview.png"
                preview.unlink(missing_ok=True)
                call("grabPreview", str(preview))
                wait_for(lambda: complete_png(preview), "marketplace preview")
                print(preview, file=sys.stderr, flush=True)
            finally:
                proc.terminate()
                proc.wait(timeout=5)
                log_text = log.read_text()
                (output / "capture.log").write_text(log_text)
                for line in log_text.splitlines():
                    if "OpenGL VENDOR" in line or "WARN" in line or "ERROR" in line:
                        print(line, file=sys.stderr)
        if "NVIDIA" not in log_text or "llvmpipe" in log_text or "Software" in log_text:
            raise RuntimeError("Capture must use NVIDIA GPU rendering; inspect screenshots/capture.log")


if __name__ == "__main__": main()
