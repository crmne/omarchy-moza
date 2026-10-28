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
cross to QML. The rev preview uses the same lightweight path with Rust status
at 50 Hz, keeping the shift flash visible. Settings/layout scans remain at
10 Hz (1 Hz when closed), and the fast timer stops when the panel closes.

The Rust executable in rev/ reuses moza-rev's packet parsers and protocol
client. Packets, RPM mapping, heartbeat, reconnection and LED writes remain in
Rust. JSON carries status, configuration and Boxflat settings frames. Output
queues are bounded and nonblocking so UI backpressure does not delay LED
updates. Settings work is limited per loop. Telemetry is not queued: every
listener overwrites one latest-value slot (`Latest` in `rev/src/telemetry.rs`)
that the loop takes each tick. The UDP ports accept packets from any sender,
including other local users, and the loop is paced by serial writes, so a
flood of packets replaces one sample instead of growing memory.
Closing stdin stops the engine and clears the lights.

The same loop drives the pedal haptic module (`rev/src/haptics.rs`) on its own
USB serial port, found by its 346e:002f ID. Every listener produces one
`Telemetry` record. Wreckfest 2 and Codemasters, read with moza-rev's parsers
in `rev/src/games.rs`, fill only the engine; AMS2, Forza, BeamNG, the ACC / LMU
bridge and the AC listener add gear,
speed, pedal inputs, ABS/TC activity, wheel slip and suspension travel. Each
tick computes the wanted state of all 27 pedal slots and writes only changes
and keep-alive resends, stops first, at most 12 frames per tick. Rust owns the
vibration defaults and validation; the bridge sends whole settings and saves
the copy Rust echoes back. See [pedal haptics](Pedal-haptics.md).

Assetto Corsa uses our `rev/src/assetto_corsa.rs` listener on loopback UDP
9997 instead of moza-rev's RTCarInfo listener. The CSP companion in
assetto-corsa-setup sends versioned JSON with current RPM, `rpmLimiter`, and
`rpmMinimum` at up to 60 Hz. Each packet contains its own limit, so lower
revving cars, car changes, and downshift over-revs need no learning or reset.
Invalid limits are rejected without imposing an arbitrary RPM floor.
The normal two-second telemetry timeout clears stale lights; menus/replays
send zero RPM. This requires the CSP companion, not AC's legacy UDP option.

Rust owns the base serial port. It picks the wheelbase with Boxflat's own base
pattern, so another MOZA serial device, such as the pedal haptic module, is
never opened as a wheelbase when no base is connected. A proxy delivers replies to Boxflat's connection
manager. Boxflat's normal serial handlers still manage directly attached
peripherals. Boxflat remains responsible for discovery, routing, capability
checks, presets, HID mapping and uinput. The E-Stop callback is retained.

The adapter maps every active row type across Boxflat's 14 sections, including
nested switches, EQs, curves, colours, input bars, entries, calibration buttons
and preset dialogs. Standalone tray/window/autostart management is replaced by
Omarchy's host. Raw custom-command developer mode is not exposed. Firmware
updates are not implemented upstream and are not claimed here.

`backend/pedals.py` adapts the pedal limit and calibration button callbacks and
groups live pedal input, calibration and range controls at the top of each pedal tab. Home
keeps idle input rows compact and shows instructions during limit capture.
Limit capture reads and saves the old range, writes and reads back
0–100%, then waits for an explicit Save before sampling serial output. The
opposite limit is preserved; cancellation, timeout, failure and orderly backend
shutdown restore the old range. A single worker keeps serial waits off the GTK
loop and prevents overlapping manual settings edits. Automatic presets should
not run during pedal setup; perform it outside a driving session.
Calibration shows a three-second released-pedal preparation followed by the
existing seven-second recording interval with live HID feedback. The live bar
stays visible afterward; success messages expire after eight seconds, while
errors remain. Stop is sent even on cancellation or exceptions. The protocol has no
readable calibration-completion acknowledgement; the result asks the user to
test travel. Sensor calibration cannot be rolled back by restoring range limits.
Boxflat's capability checks and brake-calibration opt-in remain in effect.
Regression tests simulate clipped serial output, repeat a low-to-high maximum
capture, and exercise missing replies, cancellation, timing, no movement, shutdown
and the actual GTK-button-to-worker path. They do not validate pedal firmware.

Tests cover 175 top-level controls, nested preset switches, actual rotation
conversion callbacks, invalid edits, preset names and preset dialogs. Rust
tests cover threshold boundaries, disabled lights, full-width masks, custom
color framing and palette restoration after connection or LED-count changes.
The independent flash threshold defaults to 95% of redline. Above it, the
whole strip flashes at the configured 1–20 Hz (10 Hz by default), even if the
normal progressive strip has not filled yet.
A monotonic clock drives the phase independently of telemetry packet arrival;
mask changes are sent immediately, including between packets. Dropping below
the threshold, disabled lights, or stale/invalid telemetry resets the phase.
The light test ends with one second of the same flash. Tests cover phase
boundaries, custom rates, rearming, low redlines, single/32-LED strips and test
completion. Older saved configurations get the new defaults without resetting
their existing thresholds, palette or brightness.
The Rust configuration owns the live RGB palette and brightness. It applies
these after moza-rev's initialization and after paused Boxflat wheel tests;
static color reads from Boxflat never overwrite that palette. Old saved rev
settings receive the default green/yellow/red colors and full brightness.
The panel uses no Qt text input types: on Qt 6.12 every editable one reads the
clipboard whenever another application changes it, unbounded, even while
hidden. `controls/KeyField.qml` and `controls/NumberKeyField.qml` build the
text and number fields from key events instead. `tests/test_qml.py` fails if
any plugin QML uses a Qt or kit text input or the clipboard, and runs the
offscreen `qmltestrunner` field tests in `tests/qml/` with stand-ins for the
shell kit.
R12/CS V2P settings reads and the physical LED sweep have been confirmed.
Calibration/FFB writes and other hardware models still need deliberate checks
on their respective devices; adapter coverage is not hardware validation.

Boxflat baseline: d14ed0ed84ee2205d41df0f595af5f1709db7831.
The pinned moza-rev revision includes the modern-wheel initialization submitted
upstream in PR #14. RPM mapping follows the threshold work in PR #15. These
pins can move to upstream once the changes are accepted.

The unmodified Boxflat snapshot is in `vendor/boxflat/`; see [upstream tracking](Upstreams.md).
