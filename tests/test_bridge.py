import os
import io
import json
import sys
import unittest
from unittest.mock import patch
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

    def test_live_inputs_do_not_rebuild_settings(self):
        bridge = self.bridge
        output = io.StringIO()
        with patch('backend.bridge.OUT', output):
            try:
                bridge.command(dict(op='focus', name='Home', opened=True))
                document = json.loads(output.getvalue().splitlines()[-1])
                rows = [r for p in document['pages'] for g in p['groups'] for r in g['rows']]
                steering = next(r for r in rows if r['title'] == 'Steering position')
                pedal = next(r for r in rows if r['title'] == 'Throttle input')
                self.assertTrue(steering['live'])
                self.assertNotIn('value', pedal)
                bridge.model.objects[steering['id']]._label.set_label('12.3°')
                bridge.model.objects[pedal['id']]._bar.set_value(32000)
                output.seek(0); output.truncate()
                with patch.object(bridge, 'document', side_effect=AssertionError('Fast samples must not scan settings')):
                    bridge.publish_live()
                    bridge.publish_live()  # Identical values produce no traffic.
                frames = output.getvalue().splitlines()
                self.assertEqual(len(frames), 1)
                self.assertEqual(set(json.loads(frames[0])), {'live'})
                live = json.loads(frames[0])['live']
                self.assertEqual(live[steering['id']], '12.3°')
                self.assertEqual(live[pedal['id']], 32000)
                # The slower scan must not resend settings just because inputs moved.
                bridge.publish(force=True)
                self.assertEqual(len(output.getvalue().splitlines()), 1)
            finally: bridge.command(dict(op='focus', name='Rev lights', opened=False))

    def test_live_sampling_tracks_page_changes_and_closing(self):
        bridge = self.bridge
        with patch('backend.bridge.OUT', io.StringIO()):
            try:
                bridge.command(dict(op='focus', name='Home', opened=True))
                home_ids = set(bridge.model.live_readers)
                self.assertTrue(home_ids)
                self.assertIsNotNone(bridge.live_timer)
                bridge.command(dict(op='focus', name='Wheel', opened=True))
                self.assertTrue(bridge.model.live_readers)
                self.assertTrue(home_ids.isdisjoint(bridge.model.live_readers))
                bridge.command(dict(op='focus', name='Wheel', opened=False))
                self.assertIsNone(bridge.live_timer)
                self.assertEqual(bridge.model.live_values(), {})
                self.assertEqual(bridge.last_live, {})
            finally: bridge.command(dict(op='focus', name='Rev lights', opened=False))


if __name__ == '__main__': unittest.main()
