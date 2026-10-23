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

    def test_static_white_reads_cannot_overwrite_live_rev_colors(self):
        bridge = self.bridge
        colors = list(bridge.rev_config['colors'])
        with patch.object(bridge.cm, '_handle_setting') as write, patch.object(bridge.rev, 'send') as send:
            for _ in range(3):
                for i in range(10): bridge.cm._dispatch(f'wheel-rpm-color{i+1}', [255, 255, 255])
                while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
            write.assert_not_called()
            send.assert_not_called()
        self.assertEqual(bridge.rev_config['colors'], colors)

    def test_default_rev_colors_use_saturated_led_channels(self):
        # Green and red must not mix in other channels, which made the
        # physical strip look white/pink despite the named color controls.
        self.assertEqual(self.bridge.document()['config']['colors'],
                         ['#00ff00', '#ffff00', '#ff0000'])

    def test_rev_color_changes_are_saved_and_sent_together(self):
        bridge = self.bridge
        original = dict(bridge.rev_config)
        config = dict(original, colors=['#123456', '#7e7e7e', '#ff0000'], brightness=42)
        try:
            with patch('backend.bridge.OUT', io.StringIO()), patch.object(bridge.rev, 'send') as send:
                bridge.command(dict(op='rev', config=config))
                self.assertEqual(bridge.error, '')
                self.assertEqual(bridge.settings.read_setting('rev'), config)
                send.assert_called_once_with(dict(op='configure', config=config))
                # Older callers still changing thresholds must preserve the palette.
                bridge.command(dict(op='rev', config=dict(start=70, full=95, leds=12, enabled=True)))
                self.assertEqual(bridge.rev_config['colors'], config['colors'])
                self.assertEqual(bridge.rev_config['brightness'], 42)
                self.assertEqual(bridge.rev_config['flash'], config['flash'])
                self.assertEqual(bridge.rev_config['flash_hz'], config['flash_hz'])
        finally:
            bridge.rev_config = original
            bridge.settings.write_setting(original, 'rev')

    def test_invalid_rev_colors_do_not_write_settings_or_hardware(self):
        bridge = self.bridge
        for change in [dict(colors=['#ffffff']), dict(colors=['red'] * 3), dict(colors=['#1234567'] * 3),
                       dict(colors=['#gggggg'] * 3), dict(brightness=-1), dict(brightness=101), dict(brightness=True)]:
            with self.subTest(change=change), patch('backend.bridge.OUT', io.StringIO()), patch.object(bridge.rev, 'send') as send, patch.object(bridge.settings, 'write_setting') as save:
                bridge.command(dict(op='rev', config=dict(bridge.rev_config, **change)))
                self.assertTrue(bridge.error)
                send.assert_not_called()
                save.assert_not_called()
        bridge.error = ''

    def test_flash_controls_validate_and_are_saved_independently(self):
        bridge = self.bridge
        original = dict(bridge.rev_config)
        try:
            for change in [dict(flash=0), dict(flash=101), dict(flash=True),
                           dict(flash_hz=0), dict(flash_hz=21), dict(flash_hz=4.5)]:
                with self.subTest(change=change), patch('backend.bridge.OUT', io.StringIO()), patch.object(bridge.rev, 'send') as send:
                    bridge.command(dict(op='rev', config=dict(original, **change)))
                    self.assertTrue(bridge.error)
                    send.assert_not_called()
            for change in [dict(flash=90), dict(flash=99), dict(flash_hz=7)]:
                config = dict(original, **change)
                with patch('backend.bridge.OUT', io.StringIO()), patch.object(bridge.rev, 'send') as send:
                    bridge.command(dict(op='rev', config=config))
                    self.assertEqual(bridge.error, '')
                    self.assertEqual(bridge.settings.read_setting('rev'), config)
                    self.assertEqual(bridge.rev_config['full'], original['full'])
                    send.assert_called_once_with(dict(op='configure', config=config))
        finally:
            bridge.rev_config = original
            bridge.settings.write_setting(original, 'rev')

    def test_vibration_edits_go_to_rust_whole_and_validated(self):
        bridge = self.bridge
        before = json.loads(json.dumps(bridge.rev.haptics))
        self.assertTrue(before['brake']['abs']['enabled'])
        with patch('backend.bridge.OUT', io.StringIO()), patch.object(bridge.rev, 'send') as send:
            bridge.command(dict(op='haptics', pedal='brake', effect='abs', key='intensity', value=60))
            sent = send.call_args.args[0]
            self.assertEqual(sent['op'], 'haptics')
            self.assertEqual(sent['config']['brake']['abs']['intensity'], 60)
            self.assertEqual(sent['config']['throttle'], before['throttle'])
            bridge.command(dict(op='haptics', value=False))
            self.assertFalse(send.call_args.args[0]['config']['enabled'])
            send.reset_mock()
            for bad in [dict(pedal='brake', effect='abs', key='intensity', value='60'),
                        dict(pedal='brake', effect='abs', key='intensity', value=True),
                        dict(pedal='feet', effect='abs', key='intensity', value=6),
                        dict(pedal='brake', effect='nitro', key='intensity', value=6),
                        dict(pedal='brake', effect='abs', key='colour', value=6),
                        dict(value=1)]:
                bridge.command(dict(op='haptics', **bad))
                self.assertIn('Unknown vibration', bridge.error)
            bridge.command(dict(op='haptic_test', pedal='brake', effect='nitro'))
            send.assert_not_called()
            bridge.command(dict(op='haptic_test', pedal='clutch', effect='bite'))
            send.assert_called_once_with(dict(op='haptic_test', pedal='clutch', effect='bite'))
        # Nothing reached Rust, so nothing changed.
        self.assertEqual(bridge.rev.haptics, before)

    def test_only_settings_rust_accepted_are_saved_and_shown(self):
        bridge = self.bridge
        accepted = json.loads(json.dumps(bridge.rev.haptics))
        accepted['clutch']['bite']['trigger'] = 64
        with patch.object(bridge.settings, 'write_setting') as write:
            bridge.save_haptics(accepted)
            write.assert_called_once_with(accepted, 'haptics')
        self.assertEqual(bridge.document()['haptics'], bridge.rev.haptics)
        with self.assertRaises(ValueError): Bridge.haptic_change(None, dict(value=True))

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

    def test_rev_preview_updates_without_scanning_settings(self):
        bridge = self.bridge
        original = bridge.rev.status
        output = io.StringIO()
        try:
            with patch('backend.bridge.OUT', output):
                bridge.command(dict(op='focus', name='Rev lights', opened=True))
                output.seek(0); output.truncate()
                with patch.object(bridge, 'document', side_effect=AssertionError('Preview must not scan settings')):
                    for mask in [1023, 0, 1023]:
                        bridge.rev.status = dict(original, mask=mask, rpm=6500)
                        bridge.publish_live()
                        bridge.publish_live()
                frames = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertEqual([f['rev']['mask'] for f in frames], [1023, 0, 1023])
                self.assertTrue(all(set(f) == {'rev'} for f in frames))
                bridge.command(dict(op='focus', name='Home', opened=True))
                output.seek(0); output.truncate()
                bridge.rev.status = dict(original, mask=0, rpm=6500)
                bridge.publish_live()
                self.assertEqual(output.getvalue(), '')
        finally:
            bridge.rev.status = original
            with patch('backend.bridge.OUT', io.StringIO()):
                bridge.command(dict(op='focus', name='Rev lights', opened=False))

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
