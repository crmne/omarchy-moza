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
        with patch.object(setup, "probe", return_value=state), patch.object(setup.subprocess, "run") as run:
            setup.install()
        self.assertEqual(run.call_args_list[0].args[0], ["omarchy", "pkg", "add", "python-yaml"])
        self.assertEqual(run.call_args_list[1].args[0][:4], ["sudo", "cp", "--update=none", "--preserve=mode"])
        self.assertEqual(run.call_count, 3)

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
