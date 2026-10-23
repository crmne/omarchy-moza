"""Steam launch options for the ACC/LMU telemetry helper.

ACC and Le Mans Ultimate publish telemetry only inside their Proton prefix.
Proton starts bin/omarchy-moza-shm.exe next to the game when the launch
options set PROTON_REMOTE_DEBUG_CMD. This module finds those games and, on
request, adds that option. Steam rewrites localconfig.vdf when it exits, so
changes are made only while Steam is closed, after a backup, and only when
the file parses and serialises back to exactly the same text.
"""
import os
from pathlib import Path
import re
import shlex
import shutil
import time

GAMES = {"805550": "Assetto Corsa Competizione", "2399420": "Le Mans Ultimate"}
VARIABLE = "PROTON_REMOTE_DEBUG_CMD"
TOKEN = re.compile(r'\s*(?:"((?:[^"\\]|\\.)*)"|([{}]))')


def parse(text):
    """Steam's text VDF as nested lists of [key, value], keeping order."""
    pos, stack, current = 0, [], []
    pending = None
    while True:
        match = TOKEN.match(text, pos)
        if not match:
            if text[pos:].strip(): raise ValueError("Unrecognised VDF")
            break
        pos = match.end()
        string, brace = match.groups()
        if brace == "{":
            if pending is None: raise ValueError("Unexpected {")
            child = []
            current.append([pending, child])
            stack.append(current)
            current, pending = child, None
        elif brace == "}":
            if pending is not None or not stack: raise ValueError("Unexpected }")
            current = stack.pop()
        elif pending is None:
            pending = string
        else:
            current.append([pending, string])
            pending = None
    if stack or pending is not None: raise ValueError("Unterminated VDF")
    return current


def dump(entries, depth=0):
    """Serialise exactly as Steam writes localconfig.vdf."""
    out, tabs = [], "\t" * depth
    for key, value in entries:
        if isinstance(value, list):
            out.append(f'{tabs}"{key}"\n{tabs}{{\n{dump(value, depth + 1)}{tabs}}}\n')
        else:
            out.append(f'{tabs}"{key}"\t\t"{value}"\n')
    return "".join(out)


def child(entries, key, create=False):
    for name, value in entries:
        if name.lower() == key.lower() and isinstance(value, list): return value
    if not create: return None
    value = []
    entries.append([key, value])
    return value


def with_helper(options, helper):
    """Launch options that start the helper, keeping the user's own."""
    setting = f"{VARIABLE}={shlex.quote(str(helper))}"
    options = re.sub(rf"{VARIABLE}=(\"[^\"]*\"|'[^']*'|\S+)\s*", "", options).strip()
    if "%command%" not in options:
        options = (options + " %command%").strip()
    return f"{setting} {options}"


def steam_root(home):
    for path in (home / ".local/share/Steam", home / ".steam/steam"):
        if (path / "steamapps/libraryfolders.vdf").exists(): return path.resolve()
    return None


def libraries(root):
    text = (root / "steamapps/libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
    paths = [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]*)"', text)]
    return paths or [root]


def installed(root):
    """App id -> install directory, for the games this module handles."""
    found = {}
    for library in libraries(root):
        for app in GAMES:
            manifest = library / f"steamapps/appmanifest_{app}.acf"
            if app in found or not manifest.exists(): continue
            folder = re.search(r'"installdir"\s+"([^"]*)"', manifest.read_text(errors="replace"))
            if folder: found[app] = library / "steamapps/common" / folder.group(1)
    return found


def steam_running():
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit(): continue
        try: name = (proc / "comm").read_text().strip()
        except OSError: continue
        if name in ("steam", "steamwebhelper"): return True
    return False


def lmu_settings(folder):
    return folder / "UserData/player/Settings.JSON"


class Setup:
    def __init__(self, helper, home=None, running=steam_running):
        self.helper = Path(helper)
        self.home = Path(home or Path.home())
        self.running = running

    def configs(self, root):
        return sorted(root.glob("userdata/*/config/localconfig.vdf"))

    def status(self):
        root = steam_root(self.home)
        if not root: return dict(games=[], steamRunning=False)
        games = installed(root)
        result = []
        for app, folder in games.items():
            ready = False
            for config in self.configs(root):
                try: tree = parse(config.read_text(encoding="utf-8"))
                except (OSError, ValueError): continue
                options = self.options(tree, app)
                ready = ready or str(self.helper) in options
            if app == "2399420":
                try: plugins = '"Enable external plugins": true' in lmu_settings(folder).read_text()
                except OSError: plugins = False
                ready = ready and plugins
            result.append(dict(id=app, name=GAMES[app], ready=ready))
        return dict(games=result, steamRunning=self.running())

    @staticmethod
    def apps(tree, create=False):
        node = tree
        for key in ("UserLocalConfigStore", "Software", "Valve", "Steam", "apps"):
            node = child(node, key, create)
            if node is None: return None
        return node

    def options(self, tree, app):
        apps = self.apps(tree)
        game = child(apps, app) if apps is not None else None
        for key, value in game or []:
            if key == "LaunchOptions" and isinstance(value, str): return value.replace('\\"', '"').replace('\\\\', '\\')
        return ""

    def apply(self):
        """Add the helper to every detected game. Returns what changed."""
        if self.running(): raise ValueError("Close Steam first: it overwrites launch options when it exits.")
        root = steam_root(self.home)
        games = installed(root) if root else {}
        if not games: raise ValueError("Neither ACC nor Le Mans Ultimate is installed in Steam.")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        changed = []
        for config in self.configs(root):
            text = config.read_text(encoding="utf-8")
            tree = parse(text)
            if dump(tree) != text: raise ValueError(f"{config} has an unexpected format; it was left unchanged.")
            apps = self.apps(tree, create=True)
            for app in games:
                game = child(apps, app, create=True)
                current = self.options(tree, app)
                new = with_helper(current, self.helper).replace('\\', '\\\\').replace('"', '\\"')
                for entry in game:
                    if entry[0] == "LaunchOptions": entry[1] = new; break
                else: game.append(["LaunchOptions", new])
            updated = dump(tree)
            if updated != text:
                shutil.copy2(config, config.with_name(f"localconfig.vdf.omarchy-moza-{stamp}.bak"))
                tmp = config.with_suffix(".tmp")
                tmp.write_text(updated, encoding="utf-8")
                os.replace(tmp, config)
                changed.append("launch options")
        if "2399420" in games:
            settings = lmu_settings(games["2399420"])
            try: text = settings.read_text()
            except OSError: text = None
            if text and '"Enable external plugins": false' in text:
                shutil.copy2(settings, settings.with_name(f"Settings.JSON.omarchy-moza-{stamp}.bak"))
                settings.write_text(text.replace('"Enable external plugins": false', '"Enable external plugins": true', 1))
                changed.append("LMU plugins")
        return changed
