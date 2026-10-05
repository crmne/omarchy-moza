import os
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.bridge import Bridge
from gi.repository import Gtk, Adw, GLib


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gtk.init(); Adw.init()
        cls.bridge = Bridge(True)
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)

    def rows(self, name):
        return [r for p in self.bridge.model.pages(self.bridge.panels[name]) for g in p['groups'] for r in g['rows']]

    def test_every_boxflat_page_has_a_renderer(self):
        rows = [r for name in self.bridge.panels for r in self.rows(name)]
        self.assertGreaterEqual(len(rows), 175)
        self.assertEqual(len(self.bridge.panels), 14)

    def test_rotation_uses_boxflat_half_angle_conversion(self):
        bridge = self.bridge
        row = next(r for r in self.rows('Base') if r['title'] == 'Wheel Rotation Angle')
        recorded = []
        original = bridge.cm._handle_setting
        bridge.cm._handle_setting = lambda value, name, device, rw: recorded.append((value, name, device))
        try: bridge.model.act(row['id'], 'set', 900)
        finally: bridge.cm._handle_setting = original
        self.assertIn((450, 'limit', 'base'), recorded)
        self.assertIn((450, 'max-angle', 'base'), recorded)

    def test_invalid_range_does_not_write_hardware(self):
        bridge = self.bridge
        row = next(r for r in self.rows('Base') if r['title'] == 'Wheel Rotation Angle')
        with self.assertRaises(ValueError): bridge.model.act(row['id'], 'set', 9000)
        with self.assertRaises(ValueError): bridge.model.act(row['id'], 'set', float('nan'))

    def test_preset_names_stay_in_preset_directory(self):
        row = next(r for r in self.rows('Presets') if r['kind'] == 'entry')
        for name in ['../other', '/tmp/file', '..', 'a\\b']:
            with self.assertRaises(ValueError): self.bridge.model.act(row['id'], 'set', name)

    def test_include_devices_exports_nested_switches(self):
        row = next(r for r in self.rows('Presets') if r['kind'] == 'group')
        self.assertEqual(len(row['rows']), 10)
        self.assertTrue(all(r['kind'] == 'switch' for r in row['rows']))

    def test_invalid_rev_configuration_is_rejected(self):
        for value in [{}, dict(start=97,full=80,leds=10,enabled=True), dict(start=80,full=97,leds=0,enabled=True), dict(start=80.5,full=97,leds=10,enabled=True)]:
            self.assertFalse(Bridge.valid_rev(value))
        self.assertTrue(Bridge.valid_rev(dict(start=80,full=97,leds=10,enabled=True)))

    def test_preset_dialog_is_native_model_not_a_window(self):
        from boxflat.widgets import BoxflatPresetDialog
        path = Path(self.bridge.settings.get_path()) / 'presets'
        path.mkdir(exist_ok=True)
        (path / 'Test.yml').write_text('BoxflatPresetVersion: "1"\nbase: {}\n')
        dialog = BoxflatPresetDialog(str(path), 'Test.yml')
        dialog.present(None)
        self.assertIs(self.bridge.dialog, dialog)
        doc = self.bridge.document()
        self.assertTrue(doc['dialog'])
        self.assertTrue(doc['pages'][0]['groups'])
        dialog.close()
        self.assertIsNone(self.bridge.dialog)

    def test_static_colours_also_update_external_telemetry_palette(self):
        bridge = self.bridge
        recorded = []
        original = bridge.cm._handle_setting
        bridge.cm._handle_setting = lambda value, name, device, rw: recorded.append((value, name, device))
        bridge.palette.clear()
        try:
            for i in range(10): bridge.sync_colour([i, 20, 30], i)
            self.assertEqual(len(recorded), 2)
            self.assertEqual(recorded[0][0], [v for i in range(5) for v in [i, i, 20, 30]])
            self.assertEqual(recorded[1][1:], ('telemetry-rpm-colors', 'wheel'))
            bridge.sync_colour([9, 20, 30], 9)
            self.assertEqual(len(recorded), 2)
        finally: bridge.cm._handle_setting = original


if __name__ == '__main__': unittest.main()
