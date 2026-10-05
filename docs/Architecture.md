# Architecture and coverage

MozaService.qml starts a standard-library-only setup launcher, which checks
dependencies before replacing itself with one Python bridge per shell.
Missing dependencies appear in a native setup panel; installation runs only
after a button click in a visible Omarchy terminal. Every monitor's MozaPanel.qml
shares it. The bridge constructs Boxflat's original panel objects without
presenting GTK windows. backend/model.py exports the actual controls, ranges,
options and availability, invoking the original callbacks for edits. Separate
layout and state maps avoid rebuilding controls during live updates.
Wheel/pedal input readings use cached getters on an 8 ms timer while the panel
is open, keeping up with Boxflat's 120 Hz HID sampler. Only changed readings
cross to QML; settings/layout scans remain at 10 Hz (1 Hz when closed), and
the fast timer stops when the panel closes.

The Rust executable in rev/ reuses moza-rev's listeners and protocol client.
Packets, RPM mapping, heartbeat, reconnection and LED writes remain in Rust.
JSON carries status, configuration and Boxflat settings frames. Output queues
are bounded and nonblocking so UI backpressure does not delay LED updates.
Settings work is limited per loop; queued telemetry uses the newest sample.
Closing stdin stops the engine and clears the lights.

Rust owns the base serial port. A proxy delivers replies to Boxflat's connection
manager. Boxflat's normal serial handlers still manage directly attached
peripherals. Boxflat remains responsible for discovery, routing, capability
checks, presets, HID mapping and uinput. The E-Stop callback is retained.

The adapter maps every active row type across Boxflat's 14 sections, including
nested switches, EQs, curves, colours, input bars, entries, calibration buttons
and preset dialogs. Standalone tray/window/autostart management is replaced by
Omarchy's host. Raw custom-command developer mode is not exposed. Firmware
updates are not implemented upstream and are not claimed here.

Tests cover 175 top-level controls, nested preset switches, actual rotation
conversion callbacks, invalid edits, preset names and preset dialogs. Rust
tests cover threshold boundaries, disabled lights and full-width masks.
R12/CS V2P settings reads and the physical LED sweep have been confirmed.
Calibration/FFB writes and other hardware models still need deliberate checks
on their respective devices; adapter coverage is not hardware validation.

Boxflat baseline: d14ed0ed84ee2205d41df0f595af5f1709db7831.
The pinned moza-rev revision includes the modern-wheel initialization submitted
upstream in PR #14. RPM mapping follows the threshold work in PR #15. These
pins can move to upstream once the changes are accepted.

The unmodified Boxflat snapshot is in `vendor/boxflat/`; see [upstream tracking](Upstreams.md).
