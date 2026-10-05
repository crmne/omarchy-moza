#!/usr/bin/env python3
"""Sync an unmodified Boxflat snapshot; ordinary installs never need Git submodules."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "vendor/boxflat"
LOCK = ROOT / "vendor/boxflat.lock.json"
REPOSITORY = "https://github.com/Lawstorant/boxflat.git"
PATHS = ["boxflat", "data", "udev", "LICENSE", "README.md", "requirements.txt", "moza-protocol.md"]


def digest(files):
    return {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}


def snapshot(commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Use a full, immutable 40-character commit SHA")
    with tempfile.TemporaryDirectory(prefix="moza-boxflat-") as directory:
        def git(*args):
            return subprocess.check_output(["git", "-C", directory, *args])
        git("init", "-q")
        git("fetch", "--quiet", "--depth=1", REPOSITORY, commit)
        if git("rev-parse", "FETCH_HEAD").decode().strip() != commit:
            raise ValueError("Fetched commit does not match requested source")
        archive = git("archive", commit, "--", *PATHS)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for entry in tar:
            if entry.isdir():
                continue
            path = Path(entry.name)
            if not entry.isfile() or path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unsupported source entry: {entry.name}")
            files[entry.name] = tar.extractfile(entry).read()
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", metavar="COMMIT", help="Fetch and replace the snapshot at a full SHA")
    parser.add_argument("--upstream", action="store_true", help="Also compare with the original Git commit")
    args = parser.parse_args()
    if args.update:
        files = snapshot(args.update)
        lock = {"repository": REPOSITORY, "commit": args.update, "paths": PATHS, "files": digest(files)}
        DEST.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(DEST)
        for name, data in files.items():
            path = DEST / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        LOCK.write_text(json.dumps(lock, indent=2) + "\n")
    lock = json.loads(LOCK.read_text())
    assert lock["repository"] == REPOSITORY and lock["paths"] == PATHS
    files = {str(p.relative_to(DEST)): p.read_bytes() for p in DEST.rglob("*")
             if p.is_file() and "__pycache__" not in p.parts}
    if digest(files) != lock["files"]:
        raise SystemExit("Boxflat snapshot differs from its lock file; keep adapter changes in backend/")
    if args.upstream and digest(snapshot(lock["commit"])) != lock["files"]:
        raise SystemExit("Boxflat snapshot differs from the pinned upstream source")
    print(f"Boxflat {lock['commit']}: {len(files)} unmodified source files verified")


if __name__ == "__main__":
    main()
