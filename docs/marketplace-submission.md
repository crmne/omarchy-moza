### Repository URL

https://github.com/crmne/omarchy-moza

### Category

Hardware

### Tags

bar, games, quickshell

### Suggest a missing tag

_No response_

### Maintainer notes

MOZA hardware controls with native Omarchy panels, Boxflat's existing Python
settings logic and a Rust telemetry/rev-light backend. The bar icon appears
when a wheelbase connects and disappears when it disconnects. Steering and
pedal readings update at up to 120 Hz while the panel is open.

The standard `omarchy plugin add` command installs all plugin source and the
bundled binary. A standard-library-only launcher detects missing Python
GTK/Adwaita, serial, YAML, evdev and psutil dependencies and device-access rules.
The native setup panel offers an explicit button to open an Omarchy terminal
for package installation and sudo device-rule installation. No privileged work
runs automatically. Existing rules are preserved, and devices need reconnecting
after new rules are installed. Standalone Boxflat/moza-rev must be stopped so
they do not compete for serial replies or telemetry ports.

The repository includes an x86-64 Linux Rust binary, its SHA-256 checksum,
full source, Cargo.lock and an immutable moza-rev source revision. The binary
is rebuilt twice in a pinned container/toolchain and compared with the committed
file. GitHub attestations identify the verified binary and build report; release
publication requires tests and verification. See docs/Binary-provenance.md.
The bridge shares the wheelbase serial connection with Boxflat settings. Game
telemetry listeners use local UDP ports.

Boxflat is an unmodified snapshot in vendor/boxflat/ with an upstream commit,
per-file hashes and CI comparison with the original source. The snapshot
includes its standalone app module for fidelity, but the plugin entry point is
backend/setup.py, which starts backend/bridge.py. Updates are deliberate;
no runtime source fetching or submodule initialization is needed.

GPL-3.0-only, retaining Boxflat's source/history and attribution. MIT notices
are included for moza-rev and the OmaStats card component. Preview assets show
the real QML controls with explicitly documented simulated RPM/pedal values,
over Omarchy's MIT-licensed Ristretto wallpaper. Reproducible capture tools and
provenance are in tools/capture/ and docs/Screenshots.md.

R12/CS V2P settings reads and the physical LED sweep have been checked. Other
devices have adapter coverage but still need hardware validation. Firmware
updates are not supported by Boxflat.

### Submission checklist

- [x] The repository is public and contains installation and removal instructions.
- [x] I have documented the plugin license and any external dependencies.
- [x] I confirm that I own or have permission to submit this plugin and its preview assets.
- [x] The plugin does not overwrite user configuration without explicit consent.
- [x] I understand that approval is for listing and is not a security review.
