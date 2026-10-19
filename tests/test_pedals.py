import time
import unittest
from unittest.mock import patch

from backend.bridge import Bridge
from backend.pedals import PedalRange
from gi.repository import Adw, GLib, Gtk


class Device:
    """Simulate output capped by an already shortened range."""

    def __init__(self, low=5, high=20, position=90):
        self.values = {"min": low, "max": high}
        self.position = position
        self.calls = []
        self.missing = set()
        self.ignore = None

    def get_setting(self, command):
        name = command.removeprefix("pedals-throttle-")
        self.calls.append(("read", name))
        if name in self.missing:
            return None
        if name == "output":
            return round(min(self.position, self.values["max"]) * 65535 / 100)
        return self.values[name]

    def set_setting(self, value, command, exclusive=False):
        name = command.removeprefix("pedals-throttle-")
        self.calls.append(("write", name, value))
        if name in self.values and (name, value) != self.ignore:
            self.values[name] = value


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gtk.init(); Adw.init()
        cls.bridge = Bridge(True)
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def test_calibration_and_range_lead_every_pedal_tab(self):
        pages = self.bridge.model.pages(self.bridge.panels["Pedals"])
        self.assertEqual([page["title"] for page in pages], ["Throttle", "Brake", "Clutch"])
        for page in pages:
            with self.subTest(pedal=page["title"]):
                groups = page["groups"]
                self.assertEqual([g["title"] for g in groups[:3]],
                                 ["Calibration and range", "Response curve", "Other settings"])
                self.assertEqual([r["title"] for r in groups[0]["rows"][:4]],
                                 [f"{page['title']} input", "Calibration", "Range Start", "Range End"])
                rows = [row for group in groups for row in group["rows"]]
                self.assertEqual(len({row["id"] for row in rows}), len(rows))
                self.assertEqual(len(rows), 8 if page["title"] == "Brake" else 7)
                self.assertEqual(groups[0]["rows"][1]["enabled"], page["title"] != "Brake")

    def test_pedal_tabs_receive_the_same_live_hid_input_as_home(self):
        bridge = self.bridge
        pages = bridge.model.pages(bridge.panels["Pedals"])
        bridge.model.track_live(pages)
        for page in pages:
            row = page["groups"][0]["rows"][0]
            self.assertTrue(row["live"])
            for value in (0, 32767, 65534):
                bridge.hid._dispatch(page["title"].lower(), value)
                while GLib.MainContext.default().pending():
                    GLib.MainContext.default().iteration(False)
                self.assertEqual(bridge.model.live_values()[row["id"]], value)
                home, _ = bridge.pedals.controls[page["title"].lower(), "range"]
                self.assertEqual(home.get_value(), value)

    def test_home_has_no_repeated_idle_instructions(self):
        for pedal in ("throttle", "brake", "clutch"):
            row, _ = self.bridge.pedals.controls[pedal, "range"]
            self.assertEqual(self.bridge.model.row(row)["subtitle"], "")


class RangeTests(unittest.TestCase):
    def test_can_increase_previous_low_max_and_repeat(self):
        device = Device()
        for position in (90, 100, 30, 85):
            device.position = position
            session = PedalRange(device, "throttle")
            session.prepare()
            saved = session.save("max")
            self.assertLessEqual(abs(saved - position), 1)
            self.assertEqual(device.values, {"min": 5, "max": saved})
            session.restore()
            self.assertEqual(device.values["max"], saved)
        self.assertLess(device.calls.index(("write", "max", 100)), device.calls.index(("read", "output")))

    def test_min_preserves_existing_max_and_can_capture_zero(self):
        device = Device(position=0)
        session = PedalRange(device, "throttle")
        session.prepare()
        self.assertEqual(session.save("min"), 0)
        self.assertEqual(device.values, {"min": 0, "max": 20})

    def test_cancel_restores_both_limits(self):
        device = Device()
        session = PedalRange(device, "throttle")
        session.prepare()
        self.assertEqual(device.values, {"min": 0, "max": 100})
        session.restore()
        self.assertEqual(device.values, {"min": 5, "max": 20})

    def test_missing_initial_read_does_not_write(self):
        device = Device()
        device.missing.add("max")
        session = PedalRange(device, "throttle")
        with self.assertRaisesRegex(ValueError, "did not respond"):
            session.prepare()
        session.restore()
        self.assertFalse(any(call[0] == "write" for call in device.calls))

    def test_missing_output_restores_limits_without_saving_zero(self):
        device = Device()
        session = PedalRange(device, "throttle")
        session.prepare()
        device.missing.add("output")
        with self.assertRaisesRegex(ValueError, "did not respond"):
            session.save("max")
        session.restore()
        self.assertEqual(device.values, {"min": 5, "max": 20})
        self.assertNotIn(("write", "max", 0), device.calls)

    def test_unconfirmed_widening_aborts_and_can_restore(self):
        device = Device()
        device.ignore = "max", 100
        session = PedalRange(device, "throttle")
        with patch("backend.pedals.time.sleep"), self.assertRaisesRegex(ValueError, "did not confirm"):
            session.prepare()
        session.restore()
        self.assertEqual(device.values, {"min": 5, "max": 20})
        self.assertNotIn(("read", "output"), device.calls)

    def test_crossed_limits_rejected_and_restored(self):
        for endpoint, position in (("min", 90), ("max", 0)):
            with self.subTest(endpoint=endpoint):
                device = Device(position=position)
                session = PedalRange(device, "throttle")
                session.prepare()
                with self.assertRaisesRegex(ValueError, "no pedal travel"):
                    session.save(endpoint)
                session.restore()
                self.assertEqual(device.values, {"min": 5, "max": 20})


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gtk.init(); Adw.init()
        cls.bridge = Bridge(True)
        cls.drain()

    def setUp(self):
        self.controls = self.bridge.pedals
        self.device = Device()
        self.controls.cm = self.device
        self.controls.closed = False
        self.controls.active = None
        self.controls.request.clear()
        self.controls.inputs.clear()
        self.drain()

    def tearDown(self):
        self.controls.clear_results()

    @staticmethod
    def drain():
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def run_workflow(self, mode, countdown):
        self.controls.active = "throttle", mode
        with patch.object(self.controls, "countdown", side_effect=countdown):
            self.controls.run("throttle", mode)
        self.drain()

    def test_recording_instructions_precede_stop_and_result_is_shown(self):
        def countdown(seconds, phase, instruction, pedal, samples=None):
            if phase == "preparing":
                self.assertIn("released", instruction)
                self.assertEqual(seconds, 3)
                self.assertNotIn(("write", "calibration-start", 1), self.device.calls)
            else:
                self.assertEqual(seconds, 7)
                self.assertIn("release NOW", instruction)
                self.assertIn(("write", "calibration-start", 1), self.device.calls)
                self.assertNotIn(("write", "calibration-stop", 0), self.device.calls)
                samples.extend((0, 65000, 0))
            return True
        self.run_workflow("calibration", countdown)
        self.assertEqual(self.device.values, {"min": 0, "max": 100})
        self.assertEqual(self.device.calls.count(("write", "calibration-stop", 0)), 1)
        row, buttons = self.controls.controls["throttle", "calibration"]
        self.assertIn("Calibration finished", row.get_subtitle())
        self.assertIn("0%", row.get_subtitle())
        self.assertEqual(buttons["calibration"].get_label(), "Calibrate again")
        self.assertIsNone(self.controls.active)

    def test_success_expires_after_eight_seconds(self):
        self.controls.active = "throttle", "calibration"
        with patch("backend.pedals.GLib.timeout_add", return_value=123) as timer:
            self.controls.finish("Calibration finished.", True)
        timer.assert_called_once_with(8000, self.controls.expire_result, ("throttle", "calibration"))
        self.controls.expire_result(("throttle", "calibration"))
        row, buttons = self.controls.controls["throttle", "calibration"]
        self.assertEqual(row.get_subtitle(), self.controls.idle_subtitle("calibration"))
        self.assertEqual(buttons["calibration"].get_label(), "Calibrate")
        self.assertEqual(self.bridge.message, "")

    def test_success_expiry_preserves_newer_notifications_and_errors(self):
        self.controls.active = "throttle", "calibration"
        with patch("backend.pedals.GLib.timeout_add", return_value=123):
            self.controls.finish("Calibration finished.", True)
        self.bridge.notice("Applied a preset")
        self.controls.expire_result(("throttle", "calibration"))
        self.assertEqual(self.bridge.message, "Applied a preset")
        self.controls.active = "throttle", "calibration"
        with patch("backend.pedals.GLib.timeout_add") as timer:
            self.controls.finish("Pedal did not respond.", False)
        timer.assert_not_called()
        self.assertIn("did not respond", self.bridge.message)

    def test_no_motion_does_not_report_success(self):
        self.run_workflow("calibration", lambda *args: True)
        self.assertEqual(self.device.values, {"min": 5, "max": 20})
        self.assertIn("no pedal movement", self.bridge.message)
        self.assertNotIn("Calibration finished", self.bridge.message)

    def test_cancel_during_recording_stops_device_and_restores(self):
        self.run_workflow("calibration", lambda seconds, phase, *args: phase == "preparing")
        self.assertEqual(self.device.calls.count(("write", "calibration-stop", 0)), 1)
        self.assertEqual(self.device.values, {"min": 5, "max": 20})
        self.assertIn("Run calibration again", self.bridge.message)

    def test_cancel_before_recording_never_starts_device(self):
        self.run_workflow("calibration", lambda *args: False)
        self.assertNotIn(("write", "calibration-start", 1), self.device.calls)
        self.assertEqual(self.device.values, {"min": 5, "max": 20})

    def test_timed_out_capture_restores_without_sampling(self):
        self.run_workflow("max", lambda *args: True)
        self.assertEqual(self.device.values, {"min": 5, "max": 20})
        self.assertNotIn(("read", "output"), self.device.calls)

    def test_recording_exception_still_stops_device(self):
        def countdown(seconds, phase, *args):
            if phase == "recording":
                raise RuntimeError("Disconnected")
            return True
        self.run_workflow("calibration", countdown)
        self.assertEqual(self.device.calls.count(("write", "calibration-stop", 0)), 1)
        self.assertEqual(self.device.values, {"min": 5, "max": 20})
        self.assertIn("Disconnected", self.bridge.message)

    def test_home_buttons_work_at_zero_and_full_output(self):
        row, buttons = self.controls.controls["throttle", "range"]
        for value in (0, 65534, 0):
            row._bar.set_value(value)
            self.drain()
            data = self.bridge.model.row(row)
            self.assertEqual([b["label"] for b in data["buttons"]], ["Set min", "Set max"])
            self.assertTrue(all(b["enabled"] for b in data["buttons"]))

    def test_real_button_flow_is_async_guards_edits_and_saves(self):
        row, buttons = self.controls.controls["throttle", "range"]
        self.bridge.model.act(self.bridge.model.key(buttons["max"]), "click")
        deadline = time.monotonic() + 3
        while self.controls.phase != "capture" and time.monotonic() < deadline:
            self.drain()
            time.sleep(.01)
        self.assertEqual(self.controls.phase, "capture")
        self.assertEqual(self.device.values, {"min": 0, "max": 100})
        other = self.controls.controls["clutch", "range"][1]["max"]
        with self.assertRaisesRegex(ValueError, "Finish or cancel"):
            self.bridge.model.act(self.bridge.model.key(other), "click")
        self.bridge.model.act(self.bridge.model.key(buttons["max"]), "click")
        self.controls.worker.join(timeout=3)
        self.assertFalse(self.controls.worker.is_alive())
        self.drain()
        self.assertGreater(self.device.values["max"], 20)
        self.assertIn("saved at", row.get_subtitle())

    def test_shutdown_restores_an_open_capture(self):
        self.controls.start("throttle", "min")
        self.controls.shutdown()
        self.drain()
        self.assertEqual(self.device.values, {"min": 5, "max": 20})

    def test_brake_calibration_opt_in_is_preserved(self):
        row, buttons = self.controls.controls["brake", "calibration"]
        self.assertFalse(row.is_sensitive())
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.bridge.model.act(self.bridge.model.key(buttons["calibration"]), "click")


if __name__ == "__main__":
    unittest.main()
