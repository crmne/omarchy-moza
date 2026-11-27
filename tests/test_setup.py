import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("moza_setup", Path(__file__).resolve().parents[1] / "backend/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def test_clean_machine_reports_packages_rules_and_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(setup, "ROOT", Path(directory)), patch.object(setup, "RULE_DIRS", [Path(directory)]), patch.object(setup.importlib, "import_module", side_effect=ImportError):
                state = setup.probe()
        self.assertEqual(set(state["packages"]), set(setup.PACKAGES.values()) | {"gtk4", "libadwaita"})
        self.assertTrue(state["rules"])
        self.assertTrue(state["binary"])

    def test_existing_rules_and_dependencies_need_no_install(self):
        state = dict(packages=[], rules=False, binary=False)
        with patch.object(setup, "probe", return_value=state), patch.object(setup.subprocess, "run") as run:
            setup.install()
        run.assert_not_called()

    def test_installer_uses_only_missing_packages_and_preserves_rules(self):
        state = dict(packages=["python-yaml"], rules=True, binary=False)
        with tempfile.TemporaryDirectory() as directory, patch.object(setup, "RULE_DIRS", [Path(directory)]), \
                patch.object(setup, "probe", return_value=state), patch.object(setup.subprocess, "run") as run:
            setup.install()
        self.assertEqual(run.call_args_list[0].args[0], ["omarchy", "pkg", "add", "python-yaml"])
        self.assertEqual(run.call_args_list[1].args[0], ["sudo", "cp", "--update=none", "--preserve=mode",
                         str(setup.ROOT / "udev/70-omarchy-moza.rules"), "/etc/udev/rules.d/70-omarchy-moza.rules"])
        self.assertEqual(run.call_count, 3)

    def test_shipped_rules_grant_the_seat_user_and_never_every_user(self):
        seat = (setup.ROOT / "udev/70-omarchy-moza.rules").read_text()
        rules = [line for line in seat.splitlines() if line and not line.startswith("#")]
        self.assertTrue(rules)
        self.assertTrue(all('TAG+="uaccess"' in line and "MODE" not in line for line in rules))
        self.assertIn('ATTRS{idVendor}=="346e"', seat)
        # systemd applies uaccess in 73-seat-late.rules; later files are too late.
        self.assertLess(setup.RULES, "73-seat-late.rules")
        for name in ("70-omarchy-moza.rules", "99-boxflat.rules"):
            self.assertFalse(setup.world_writable(setup.ROOT / "udev" / name), name)
        self.assertTrue(setup.world_writable(setup.ROOT / "vendor/boxflat/udev/99-boxflat.rules"))

    def test_world_writable_boxflat_rule_is_replaced_on_existing_installs(self):
        old = (setup.ROOT / "vendor/boxflat/udev/99-boxflat.rules").read_text()
        with tempfile.TemporaryDirectory() as etc, tempfile.TemporaryDirectory() as lib:
            dirs = [Path(etc), Path(lib)]
            (dirs[0] / "70-omarchy-moza.rules").write_text("")
            with patch.object(setup, "RULE_DIRS", dirs), patch.object(setup.importlib, "import_module"):
                self.assertFalse(setup.probe()["rules"])
                # A package's world-writable rule in /usr/lib needs an override in /etc.
                (dirs[1] / "99-boxflat.rules").write_text(old)
                self.assertTrue(setup.probe()["rules"])
                # The rule an earlier version installed in /etc.
                (dirs[0] / "99-boxflat.rules").write_text(old)
                state = setup.probe()
                self.assertTrue(state["rules"])
                with patch.object(setup, "probe", return_value=dict(state, binary=False)), \
                        patch.object(setup.subprocess, "run") as run:
                    setup.install()
                self.assertIn(["sudo", "install", "-m", "0644", str(setup.ROOT / "udev/99-boxflat.rules"),
                               "/etc/udev/rules.d/99-boxflat.rules"], [c.args[0] for c in run.call_args_list])
                # An administrator's own rule without MODE="0666" is left alone.
                (dirs[0] / "99-boxflat.rules").write_text('SUBSYSTEM=="tty", ATTRS{idVendor}=="346e", GROUP="uucp", MODE="0660"\n')
                self.assertFalse(setup.probe()["rules"])

    def test_failed_package_install_does_not_modify_rules(self):
        state = dict(packages=["python-yaml"], rules=True, binary=False)
        with patch.object(setup, "probe", return_value=state), patch.object(setup.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "omarchy")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                setup.install()
        self.assertEqual(run.call_count, 1)

    def test_waiting_launcher_stops_on_quit(self):
        result = Mock(stdout=json.dumps(dict(packages=["python-yaml"], rules=False, binary=False)))
        with patch.object(setup.subprocess, "run", return_value=result), patch.object(setup.select, "select", return_value=([1], [], [])), patch.object(setup.sys, "stdin", io.StringIO('{"op":"quit"}\n')), patch.object(setup.sys, "stdout", io.StringIO()) as output, patch.object(setup.os, "execv") as execute:
            setup.serve()
            self.assertEqual(json.loads(output.getvalue())["setup"]["packages"], ["python-yaml"])
        execute.assert_not_called()

    def test_launcher_rechecks_then_executes_bridge_after_setup(self):
        results = [Mock(stdout=json.dumps(dict(packages=["python-yaml"], rules=False, binary=False))), Mock(stdout=json.dumps(dict(packages=[], rules=False, binary=False)))]
        with patch.object(setup.subprocess, "run", side_effect=results), patch.object(setup.select, "select", return_value=([], [], [])), patch.object(setup.sys, "stdout", io.StringIO()), patch.object(setup.os, "execv", side_effect=SystemExit) as execute:
            with self.assertRaises(SystemExit):
                setup.serve()
        self.assertEqual(execute.call_args.args[1][-1], str(setup.ROOT / "backend/bridge.py"))


if __name__ == "__main__":
    unittest.main()
