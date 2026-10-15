import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
QMLTESTRUNNER = Path("/usr/lib/qt6/bin/qmltestrunner")
# On Qt 6.12 every editable Qt text input reads another application's
# clipboard offer on each clipboard change, unbounded, even while hidden. The
# kit's NumberField is a SpinBox around one, and its TextField is one.
TEXT_INPUTS = re.compile(r"\b(TextInput|TextField|TextEdit|TextArea|SpinBox|NumberField)\b")
CLIPBOARD = re.compile(r"clipboard", re.I)


def code(text):
    """QML without comments, so explanations may name what the code avoids."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)//.*$", "", text)


def text_input_uses(root):
    found = []
    for path in sorted(root.rglob("*.qml")):
        relative = path.relative_to(root)
        if relative.parts[0] in ("vendor", ".git"): continue
        for number, line in enumerate(code(path.read_text()).splitlines(), 1):
            if TEXT_INPUTS.search(line) or CLIPBOARD.search(line):
                found.append(f"{relative}:{number}: {line.strip()}")
    return found


class QmlTests(unittest.TestCase):
    def test_no_qt_text_inputs_or_clipboard(self):
        self.assertTrue(list(ROOT.glob("controls/*.qml")))
        self.assertEqual(text_input_uses(ROOT), [])

    def test_scan_catches_kit_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Row.qml"
            path.write_text("import qs.Ui as UI\n// TextField in a comment is fine\nUI.NumberField { }\n")
            self.assertEqual(text_input_uses(Path(directory)), ["Row.qml:3: UI.NumberField { }"])

    @unittest.skipUnless(QMLTESTRUNNER.exists(), "qt6-declarative's qmltestrunner is not installed")
    def test_key_fields(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1")
            result = subprocess.run([str(QMLTESTRUNNER), "-import", str(ROOT / "tests/qml/imports"),
                                     "-input", str(ROOT / "tests/qml")],
                                    env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"Totals: \d+ passed, 0 failed")


if __name__ == "__main__": unittest.main()
