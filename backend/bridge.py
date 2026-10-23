#!/usr/bin/python3
"""Omarchy presentation bridge for the bundled Boxflat code (GPL-3.0).

GTK controls serve as the original Boxflat model; no GTK window is presented.
Rust owns the base serial connection and the entire rev-light hot path.
"""
import fcntl
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BOXFLAT = ROOT / "vendor/boxflat"
sys.path.insert(0, str(BOXFLAT))
os.environ["BOXFLAT_FLATPAK_EDITION"] = "false"
OUT = sys.stdout
sys.stdout = sys.stderr  # Boxflat diagnostic prints must not enter the JSON stream.
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib
from backend.model import Model
from backend.pedals import PedalControls
from boxflat.subscription import SimpleEventDispatcher
from boxflat import connection_manager
from boxflat.hid_handler import HidHandler
from boxflat.settings_handler import SettingsHandler
from boxflat.panels import *


HAPTIC_PEDALS = ("throttle", "brake", "clutch")
HAPTIC_EFFECTS = ("tc", "abs", "lockup", "brake_threshold", "engine", "bite", "gear_shift", "wheel_spin", "road")
HAPTIC_FIELDS = dict(enabled=bool, frequency=int, intensity=int, start=int, end=int, trigger=int, smoothness=int)


class Rev:
    def __init__(self, config, simulate=False, haptics=None, on_haptics=None):
        self.status = dict(connected=False, rpm=0, redline=0, mask=0)
        self.handler = None
        self.config = config
        # Rust owns the vibration defaults and validation. It echoes the
        # settings it accepted, and only those are shown and saved.
        self.haptics = None
        self.on_haptics = on_haptics or (lambda config: None)
        self.lock = threading.Lock()
        self.process = None
        self.buffer = bytearray()
        self.simulate = simulate
        if simulate:
            # Demo mode has no Rust process; use its defaults, kept in sync by a Rust test.
            self.haptics = json.loads((ROOT / "backend/haptics-defaults.json").read_text())
            return
        binary = ROOT / "bin" / ("omarchy-moza" if os.uname().machine == "x86_64" else "omarchy-moza-" + os.uname().machine)
        if not binary.exists():
            self.status["error"] = "Rev backend is missing. Run make build in the plugin repository."
            return
        self.process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.send(dict(op="configure", config=config))
        self.saved_haptics = haptics or {}
        self.send(dict(op="haptics", config=self.saved_haptics))
        threading.Thread(target=self.read, daemon=True).start()

    def send(self, message):
        if self.simulate and message.get("op") == "haptics" and message["config"]:
            self.haptics = message["config"]
        if not self.process or self.process.poll() is not None: return
        with self.lock:
            try:
                self.process.stdin.write(json.dumps(message) + "\n")
                self.process.stdin.flush()
            except (BrokenPipeError, OSError): pass

    def read(self):
        for line in self.process.stdout:
            try: message = json.loads(line)
            except ValueError: continue
            if "status" in message:
                self.status = message["status"]
            if "haptics" in message:
                self.haptics = message["haptics"]
                self.on_haptics(self.haptics)
            if "error" in message and self.haptics is None and self.saved_haptics:
                # A hand-edited or outdated file: fall back to the defaults.
                self.saved_haptics = {}
                self.send(dict(op="haptics", config={}))
            if "serial" in message:
                self.buffer.extend(message["serial"])
                # Match Boxflat's receive framing, retaining partial reads.
                while len(self.buffer) >= 2:
                    if self.buffer[0] != 0x7e:
                        del self.buffer[0]; continue
                    n = self.buffer[1]
                    if not 1 <= n <= 64:
                        del self.buffer[0]; continue
                    if len(self.buffer) < n + 5: break
                    frame = bytes(self.buffer[2:n+4])
                    checksum = (13 + sum(self.buffer[:n+4])) & 255
                    if checksum == self.buffer[n+4] and self.handler:
                        self.handler._dispatch(frame)
                    del self.buffer[:n+5]
        self.status = dict(connected=False, error="Rev backend stopped. Re-enable the plugin.")

    def close(self):
        self.send(dict(op="quit"))
        if self.process:
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired: self.process.terminate(); self.process.wait(timeout=3)


class Bridge:
    def __init__(self, demo=False):
        self.demo = demo
        self.model = Model()
        self.dialog = None
        self.focus = "Rev lights"
        self.opened = False
        self.error = ""
        self.message = ""
        self.last_document = ""
        self.last_live = {}
        self.live_timer = None
        self.last_publish = 0.0
        self.rev_config = dict(start=80, full=97, flash=95, flash_hz=10, leds=10, enabled=True,
                               colors=["#00ff00", "#ffff00", "#ff0000"], brightness=100)
        config_path = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home()/".config"))) / "omarchy-moza"
        if demo:
            import tempfile
            self.temporary = tempfile.TemporaryDirectory(prefix="omarchy-moza-demo-")
            config_path = Path(self.temporary.name)
        self.settings = SettingsHandler(str(config_path))
        saved = self.settings.read_setting("rev")
        if self.valid_rev(saved): self.rev_config.update(saved)
        saved_haptics = self.settings.read_setting("haptics")
        self.rev = Rev(self.rev_config, demo, saved_haptics if isinstance(saved_haptics, dict) else None,
                       lambda config: GLib.idle_add(self.save_haptics, config))
        self.last_rev = dict(self.rev.status)
        self.cm = connection_manager.MozaConnectionManager(str(BOXFLAT/"data/serial.yml"), demo)
        self.hid = HidHandler()
        self.hid.set_detection_fix_enabled(self.settings.read_setting("moza-detection-fix-enabled") or 0)
        self.cm.subscribe("hid-device-connected", self.hid.add_device)
        self.cm.subscribe("hid-device-disconnected", self.hid.remove_device)
        original_handler = connection_manager.SerialHandler
        rev = self.rev
        class BaseProxy(SimpleEventDispatcher):
            def __init__(self, *args): super().__init__(); rev.handler = self
            def write_bytes(self, message):
                if message: rev.send(dict(op="write", frame=list(message)))
            def stop(self): rev.handler = None
        connection_manager.SerialHandler = lambda path, start, name: BaseProxy() if name == "base" else original_handler(path, start, name)
        # Plugin lifecycle replaces the standalone app's desktop autostart.
        OtherSettings._handle_autostart = lambda *_: None
        Adw.Dialog.present = lambda dialog, *_: self.present(dialog)
        Adw.Dialog.close = lambda dialog: self.close_dialog()
        SettingsPanel.show_toast = lambda panel, title, *_: self.notice(title)
        HomeSettings._show_about_dialog = lambda *_: self.notice("Boxflat by Tomasz Pakuła. Omarchy interface by Carmine Paolino. GPL-3.0. Rev telemetry uses moza-rev by Francis De Brabandere (MIT).")
        noop = lambda *_: None
        self.panels = {
            "Home": HomeSettings(noop, demo, self.cm, self.hid, "Omarchy"),
            "Base": BaseSettings(noop, self.cm, self.hid),
            "Wheel": WheelSettings(noop, self.cm, self.hid, self.settings),
            "Wheel Old": OldWheelSettings(noop, self.cm, self.hid, self.settings),
            "Pedals": PedalsSettings(noop, self.cm, self.hid),
            "Dash": DashSettings(noop, self.cm, self.hid, self.settings),
            "H-Pattern Shifter": HPatternSettings(noop, self.cm, self.settings, self.hid),
            "Sequential Shifter": SequentialSettings(noop, self.cm, self.hid),
            "Handbrake": HandbrakeSettings(noop, self.cm, self.hid),
            "Multifunction Stalks": StalksSettings(noop, self.cm, self.hid, self.settings),
            "Universal Hub": HubSettings(noop, self.cm),
        }
        p = self.panels
        # Let Boxflat's existing wheel/button test own the LEDs until it
        # finishes. Its settings I/O continues through Rust during this pause.
        for name in ["Wheel", "Wheel Old"]:
            original_test = p[name]._wheel_rpm_test
            def guarded_test(*args, original=original_test):
                self.rev.send(dict(op="pause", milliseconds=30000))
                try: original(*args)
                finally: self.rev.send(dict(op="pause", milliseconds=0))
            p[name]._wheel_rpm_test = guarded_test
        p["Presets"] = PresetSettings(noop, self.cm, self.settings, p["H-Pattern Shifter"], p["Multifunction Stalks"])
        p["Presets"].set_application(self)
        p["Generic Devices"] = GenericSettings(noop, self.settings)
        p["Other"] = OtherSettings(noop, self.cm, self.hid, self.settings, "Omarchy", self, str(BOXFLAT/"data"))
        p["Other"].subscribe("brake-calibration-enabled", p["Pedals"].set_brake_calibration_active)
        p["Pedals"].set_brake_calibration_active(p["Other"].get_brake_valibration_enabled())
        self.pedals = PedalControls(self.model, p, self.cm, self.hid, self.notice)
        for name, panel in p.items():
            panel.active(1 if demo or name in ["Home", "Presets", "Generic Devices", "Other"] else -2)
        self.cm.subscribe("estop-receive-status", self.cm.set_setting, "base-ffb-disable")
        if not demo: self.cm.set_write_active()
        self.loop = GLib.MainLoop()

    @staticmethod
    def valid_rev(c):
        required = {"start", "full", "leds", "enabled"}
        return (isinstance(c, dict) and required <= set(c) <= required | {"colors", "brightness", "flash", "flash_hz"}
                and all(type(c[k]) is int for k in ["start", "full", "leds"])
                and type(c["enabled"]) is bool and 0 <= c["start"] < c["full"] <= 100
                and 1 <= c["leds"] <= 32
                and type(c.get("flash", 95)) is int and 1 <= c.get("flash", 95) <= 100
                and type(c.get("flash_hz", 10)) is int and 1 <= c.get("flash_hz", 10) <= 20
                and type(c.get("brightness", 100)) is int and 0 <= c.get("brightness", 100) <= 100
                and isinstance(c.get("colors", []), list)
                and ("colors" not in c or len(c["colors"]) == 3 and all(
                    isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color) for color in c["colors"])))

    def save_haptics(self, config):
        self.settings.write_setting(config, "haptics")
        return False

    @staticmethod
    def haptic_change(current, request):
        """The full settings after one edit from the panel."""
        if current is None: raise ValueError("The vibration module settings are still loading.")
        config = json.loads(json.dumps(current))
        if "pedal" not in request:
            if type(request.get("value")) is not bool: raise ValueError("Unknown vibration setting")
            config["enabled"] = request["value"]
            return config
        pedal, effect, key, value = (request.get(k) for k in ("pedal", "effect", "key", "value"))
        if pedal not in HAPTIC_PEDALS or effect not in HAPTIC_EFFECTS or key not in HAPTIC_FIELDS \
                or type(value) is not HAPTIC_FIELDS[key]:
            raise ValueError("Unknown vibration setting")
        config[pedal][effect][key] = value
        return config

    def hold(self): pass
    def release(self): pass
    def send_notification(self, key, notification): self.notice("Applied automatic Boxflat preset")
    def withdraw_notification(self, key): pass
    def notice(self, text, previous=None):
        if previous is None or self.message == previous:
            self.message = text
    def present(self, dialog): self.dialog = dialog
    def close_dialog(self): self.dialog = None; return True

    def document(self):
        pages = []
        if self.dialog:
            child = self.dialog.get_child()
            pages = [dict(title=self.dialog.get_title(), groups=self.model.groups(child))]
        elif self.opened and self.focus in self.panels:
            pages = self.model.pages(self.panels[self.focus])
            if self.focus == "Other":
                for page in pages: page["groups"] = [g for g in page["groups"] if g["title"] != "Background settings"]
        return dict(panels=[dict(name=name, connected=panel._active) for name,panel in self.panels.items()],
                    pages=pages, dialog=bool(self.dialog), rev=self.rev.status,
                    config=self.rev_config, haptics=self.rev.haptics,
                    error=self.error, message=self.message, demo=self.demo)

    def publish_live(self):
        try:
            values = self.model.live_values()
            update = {}
            if values != self.last_live:
                update["live"] = values
                self.last_live = values
            status = self.rev.status
            if self.focus in ("Rev lights", "Vibration module") and status != self.last_rev:
                update["rev"] = status
                self.last_rev = dict(status)
            if update:
                OUT.write(json.dumps(update, separators=(",", ":")) + "\n")
                OUT.flush()
        except BrokenPipeError: self.loop.quit(); return False
        return True

    def update_live_timer(self):
        # Boxflat already samples HID inputs at 120 Hz. Only read the active
        # page's cached getters here, leaving GTK traversal/settings at 10 Hz.
        if self.opened and self.live_timer is None:
            self.live_timer = GLib.timeout_add(8, self.publish_live)
        elif not self.opened and self.live_timer is not None:
            GLib.source_remove(self.live_timer)
            self.live_timer = None

    def publish(self, force=False):
        now = time.monotonic()
        if not force and not self.opened and now - self.last_publish < 1: return True
        self.last_publish = now
        try:
            doc = self.document()
            live = self.model.track_live(doc["pages"])
            text = json.dumps(doc, separators=(",", ":"))
            if text != self.last_document:
                OUT.write(json.dumps(dict(doc, live=live), separators=(",", ":")) + "\n")
                OUT.flush()
                self.last_document = text
                self.last_live = live
                self.last_rev = dict(doc["rev"])
            else:
                self.publish_live()
        except BrokenPipeError: self.loop.quit(); return False
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error = str(e)
        return True

    def command(self, request):
        try:
            self.error = ""
            op = request.get("op")
            if op == "focus": self.focus = request["name"]; self.opened = request.get("opened", True)
            elif op == "act": self.model.act(request["id"], request["action"], request.get("value"), request.get("index", 0))
            elif op == "rev":
                config = request["config"]
                if not self.valid_rev(config): raise ValueError("Use first < full (0–100%), flash 1–100%, 1–20 flashes/second, 1–32 LEDs, three #RRGGBB colors and brightness 0–100%.")
                config = dict(self.rev_config, **config)
                self.settings.write_setting(config, "rev")
                self.rev_config = config
                self.rev.send(dict(op="configure", config=config))
            elif op == "test": self.rev.send(dict(op="test"))
            elif op == "haptics": self.rev.send(dict(op="haptics", config=self.haptic_change(self.rev.haptics, request)))
            elif op == "haptic_test":
                if request.get("pedal") not in HAPTIC_PEDALS or request.get("effect") not in HAPTIC_EFFECTS:
                    raise ValueError("Unknown vibration effect")
                self.rev.send(dict(op="haptic_test", pedal=request["pedal"], effect=request["effect"]))
            elif op == "back":
                if self.dialog:
                    nav = self.dialog.get_child()
                    if isinstance(nav, Adw.NavigationView) and nav.get_navigation_stack().get_n_items() > 1: nav.pop()
                    else: self.close_dialog()
            elif op == "dismiss": self.error = ""; self.message = ""
            elif op == "quit": self.loop.quit()
            else: raise ValueError("Unknown request")
        except Exception as e: self.error = str(e)
        self.publish(force=True)
        self.update_live_timer()
        return False

    def run(self):
        def read():
            while True:
                line = sys.stdin.readline(65537)
                if not line or len(line) > 65536: break
                try: request = json.loads(line)
                except ValueError: continue
                if isinstance(request, dict): GLib.idle_add(self.command, request)
            GLib.idle_add(self.loop.quit)
        threading.Thread(target=read, daemon=True).start()
        GLib.timeout_add(100, self.publish)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: self.loop.quit())
        self.publish()
        try: self.loop.run()
        finally:
            if self.live_timer is not None: GLib.source_remove(self.live_timer)
            self.pedals.shutdown()
            self.cm.shutdown()
            for device in list(self.cm._serial_devices.values()): device.serial_handler.stop()
            for panel in self.panels.values(): panel.shutdown()
            self.rev.close()


if __name__ == "__main__":
    demo = "--demo" in sys.argv
    if not demo:
        lock_path = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / f"omarchy-moza-{os.getuid()}.lock"
        lock = lock_path.open("w")
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit("Omarchy MOZA is already running")
    Gtk.init(); Adw.init()
    Bridge(demo).run()
