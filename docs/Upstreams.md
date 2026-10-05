# Tracking the upstream projects

The plugin keeps Boxflat in Python and the rev-light engine in Rust. There is
no parallel implementation of Boxflat's device settings to keep in sync.

## Boxflat

`vendor/boxflat/` is an unmodified snapshot of selected paths from
[Lawstorant/boxflat](https://github.com/Lawstorant/boxflat), pinned by full commit
SHA in `vendor/boxflat.lock.json`. The lock also records every file's SHA-256.
The snapshot includes the original license, README, protocol documentation,
Python package, data and device-access rules. Our adapter lives in `backend/`.

The initial pin is `d14ed0ed84ee2205d41df0f595af5f1709db7831`. To verify it:

```sh
python3 -B tools/boxflat-source.py             # offline integrity check
python3 -B tools/boxflat-source.py --upstream  # compare with the upstream Git commit
```

To update, choose and review a full upstream commit SHA:

```sh
python3 -B tools/boxflat-source.py --update FULL_40_CHARACTER_COMMIT_SHA
make test
make validate
git diff -- vendor/ backend/
```

Commit the snapshot and lock together. CI checks the files against the pinned
original Git source. Keep plugin adaptations in `backend/`; do not patch the
vendor directory. Review new controls and check affected hardware before
shipping an update. Updates are deliberate, never fetched at plugin startup.

A checked-in snapshot is used because the Omarchy installer performs a plain
clone without recursive submodule initialization. GitHub source archives also
need to contain the actual Python files. No extra Git command is required of
the person installing the plugin.

## moza-rev

`rev/Cargo.toml` pins the Rust library to commit
`5d397dd3764a9d961c6bd5b463a5785dec85bdff` in
[crmne/moza-rev](https://github.com/crmne/moza-rev). `Cargo.lock` fixes the rest
of the Rust dependency graph. This fork carries modern-wheel initialization
submitted to [francisdb/moza-rev#14](https://github.com/francisdb/moza-rev/pull/14).
It can switch to the upstream repository after that support is available there.
Changing a pin requires rebuilding and verifying the bundled executable.

## Repository history and attribution

This repository began with Boxflat's Git history. That is why Boxflat's authors
appear among its contributors. moza-rev is a Cargo dependency, not this
repository's parent history. The history is preserved to retain attribution;
the directory layout makes the ownership of each component explicit.

Boxflat and this integration use GPL-3.0. The moza-rev MIT license is in
`docs/moza-rev-LICENSE`; the Boxflat license is also retained in its snapshot.
