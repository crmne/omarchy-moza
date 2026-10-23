import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import steam

CONFIG = '''"UserLocalConfigStore"
{
\t"Software"
\t{
\t\t"Valve"
\t\t{
\t\t\t"Steam"
\t\t\t{
\t\t\t\t"apps"
\t\t\t\t{
\t\t\t\t\t"805550"
\t\t\t\t\t{
\t\t\t\t\t\t"LaunchOptions"\t\t"gamemoderun %command% -nolog"
\t\t\t\t\t\t"playtime"\t\t"12"
\t\t\t\t\t}
\t\t\t\t}
\t\t\t}
\t\t}
\t}
}
'''


class SteamSetupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        root = self.home / ".local/share/Steam"
        library = self.home / "games"
        (root / "steamapps").mkdir(parents=True)
        (root / "steamapps/libraryfolders.vdf").write_text(
            f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{root}"\n\t}}\n\t"1"\n\t{{\n\t\t"path"\t\t"{library}"\n\t}}\n}}\n')
        (library / "steamapps").mkdir(parents=True)
        for app, folder in (("805550", "Assetto Corsa Competizione"), ("2399420", "Le Mans Ultimate")):
            (library / f"steamapps/appmanifest_{app}.acf").write_text(f'"AppState"\n{{\n\t"installdir"\t\t"{folder}"\n}}\n')
        self.lmu = library / "steamapps/common/Le Mans Ultimate/UserData/player/Settings.JSON"
        self.lmu.parent.mkdir(parents=True)
        self.lmu.write_text('{\n    "Enable external plugins": false,\n    "Other": 1\n}\n')
        self.config = root / "userdata/1/config/localconfig.vdf"
        self.config.parent.mkdir(parents=True)
        self.config.write_text(CONFIG)
        self.running = False
        self.setup = steam.Setup("/plugin dir/bin/omarchy-moza-shm.exe", self.home, lambda: self.running)

    def test_adds_helper_keeping_options_and_backs_up(self):
        self.assertEqual([g["ready"] for g in self.setup.status()["games"]], [False, False])
        self.assertEqual(self.setup.apply(), ["launch options", "LMU plugins"])
        tree = steam.parse(self.config.read_text())
        helper = "PROTON_REMOTE_DEBUG_CMD='/plugin dir/bin/omarchy-moza-shm.exe'"
        self.assertEqual(self.setup.options(tree, "805550"), f"{helper} gamemoderun %command% -nolog")
        self.assertEqual(self.setup.options(tree, "2399420"), f"{helper} %command%")
        self.assertIn('"playtime"\t\t"12"', self.config.read_text())
        self.assertIn('"Enable external plugins": true', self.lmu.read_text())
        self.assertEqual(len(list(self.config.parent.glob("*.bak"))), 1)
        self.assertEqual(len(list(self.lmu.parent.glob("*.bak"))), 1)
        self.assertEqual([g["ready"] for g in self.setup.status()["games"]], [True, True])
        # Running it again changes nothing.
        before = self.config.read_text()
        self.assertEqual(self.setup.apply(), [])
        self.assertEqual(self.config.read_text(), before)

    def test_refuses_while_steam_runs_or_on_unexpected_format(self):
        self.running = True
        with self.assertRaisesRegex(ValueError, "Close Steam"): self.setup.apply()
        self.running = False
        self.config.write_text(CONFIG.replace("\t\t\t\t\t\t\"playtime\"\t\t", "\t\t\t\t\t\t\"playtime\" "))
        with self.assertRaisesRegex(ValueError, "unexpected format"): self.setup.apply()
        self.assertEqual(list(self.config.parent.glob("*.bak")), [])

    def test_without_steam_nothing_is_offered(self):
        self.assertEqual(steam.Setup("/x.exe", self.home / "empty").status(), dict(games=[], steamRunning=False))


if __name__ == "__main__": unittest.main()
