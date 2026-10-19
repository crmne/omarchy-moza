# MOZA for Omarchy

A native [Omarchy](https://omarchy.org) control panel for MOZA racing hardware.
It combines [Boxflat](https://github.com/Lawstorant/boxflat)'s Python settings
with fast Rust rev lights powered by [moza-rev](https://github.com/francisdb/moza-rev).
The themed interface follows [OmaStats](https://github.com/crmne/omastats).

![MOZA rev lights and pedal inputs in Omarchy](preview.png)

The preview combines real plugin panels over Omarchy's Ristretto wallpaper,
in the same style as [hyprmoncfg](https://github.com/crmne/omarchy-hyprmoncfg).
Screenshots use simulated RPM and input values in an isolated capture host.
They do not represent a live game or additional hardware testing.

<details>
<summary>Rev lights, live inputs and wheelbase settings</summary>

![Rev lights at a simulated 6,420 RPM](screenshots/rev-lights.png)

![Simulated steering and pedal inputs](screenshots/inputs.png)

![Wheelbase settings](screenshots/base.png)

</details>

## Features

- Live RPM, configurable first/full thresholds (80–97% by default), LED count,
  on/off, and a hardware sweep test. Modern wheels also get saved colors and
  brightness. Changes apply without restarting.
- Wheelbase rotation, force feedback, damping, friction, inertia, protection,
  equalizer, force curve, soft limits, temperatures, and startup sound.
- Modern and legacy wheel settings: paddles, encoders, joystick modes,
  combinations, calibration, RPM/button colours, brightness, idle effects.
- Pedals, dashboards, H-pattern and sequential shifters, handbrakes,
  multifunction stalks and universal hubs, using Boxflat's existing controls.
- Boxflat presets with device selection, default profiles and automatic
  application when a game process starts. Preset dialogs stay inside the panel.
- Generic HID detection fixes and Boxflat's device-specific input behaviour.
- Wheel and pedal indicators update at up to 120 Hz while the panel is open.
- A steering-wheel bar icon that appears only while the wheelbase is connected.

Unavailable controls are hidden or disabled using Boxflat's capability checks.
This initial integration has been checked on an R12 with CS V2P (settings reads
and physical LED sweep). Other pages share Boxflat's logic and have adapter
coverage, but have not been tested on every hardware model. Firmware updates
are outside Boxflat's supported feature set.

## Install

Requires Omarchy's Quickshell plugin host and Python 3.12 or newer:

```sh
omarchy plugin add https://github.com/crmne/omarchy-moza.git --enable
```

On a fresh installation, open the steering-wheel icon and choose **Open setup
terminal**. It installs only the missing Boxflat dependencies and device-access
rules through an Omarchy terminal, which may ask for your password. The plugin
starts automatically afterward. Reconnect your devices if rules were installed.
Existing rules are preserved. You can retry interrupted setup from the panel.

The required Arch packages are `python-gobject`, `gtk4`, `libadwaita`,
`python-cairo`, `python-pyserial`, `python-yaml`, `python-evdev` and `python-psutil`.
There is no pip environment, separate Boxflat checkout or Rust compiler needed
for the standard x86-64 installation. [View the setup panel](screenshots/first-run.png).

The repository bundles a reproducibly built, attested x86-64 Rust executable.
For another architecture, build on that machine before enabling the plugin:

```sh
git clone https://github.com/crmne/omarchy-moza.git
cd omarchy-moza
mise install
make build install
omarchy plugin enable crmne.moza
```

Building needs Rust, mbx, a C toolchain, pkg-config and libudev development files.
`mise install` installs the pinned Rust and mbx versions; the system build
dependencies are `base-devel` and `systemd-libs` on Omarchy. Contributors who
do not use mise or mbx can run Cargo directly in `rev/`.

Close standalone Boxflat and stop standalone moza-rev first. They must not
compete for device replies or UDP ports. System packages and device rules are
installed only when you choose setup; nothing privileged runs at startup.

The steering-wheel icon appears when a wheelbase connects and disappears when
it disconnects. It also appears when first-run setup is needed. The background
service keeps watching for reconnection.
Click the icon in the bar, or run:

```sh
omarchy-shell crmne.moza show 'Rev lights'
omarchy-shell crmne.moza show Base
omarchy-shell crmne.moza status
omarchy-shell crmne.moza configure 80 97
```

## Games and settings

The Rust engine listens for Automobilista 2 / Project CARS, Wreckfest 2,
Codemasters legacy telemetry, BeamNG / OutGauge, Assetto Corsa and Forza.
Assetto Corsa uses the small CSP companion installed by
[assetto-corsa-setup](https://github.com/crmne/assetto-corsa-setup), sending
the current car's actual RPM, limiter and idle RPM to `127.0.0.1:9997`.
Run the updated setup script with the game closed, then start a session.
This replaces AC's legacy UDP feed, which has no limiter and guessed a
7,000 RPM ceiling. Low-revving cars work without a fixed RPM floor, car
changes apply immediately, and over-revs never change the limit. Without
the companion or a valid car limiter, AC lights stay off rather than guessing.
No telemetry leaves the computer. Other games' setup and default ports
follow moza-rev. For AMS2, select **Project CARS 2**
UDP and **frequency 1**. Linux can also need the broadcast-routing setup in
[moza-rev's documentation](https://github.com/francisdb/moza-rev).
Occupied telemetry ports are reported in the rev-light page.

Thresholds are percentages of redline. With a 6,800 RPM redline, 80–97% lights
the first LED at 5,440 RPM and fills the bar at 6,596 RPM.

Settings and Boxflat-compatible presets live in `~/.config/omarchy-moza/`
(or `$XDG_CONFIG_HOME/omarchy-moza/`). Existing standalone Boxflat settings
are left alone. Copy chosen `.yml` presets to `~/.config/omarchy-moza/presets/`
before starting the plugin to import them. Device settings are read from hardware.

The plugin runs while enabled, including with the panel closed. Boxflat's
standalone tray, window and autostart options are replaced by the plugin host.
Resets and profile loading retain Boxflat's behaviour. Colour fields accept
`#RRGGBB`.

### Rev lights

On **Rev lights**, choose colors for the first, middle and last sections, using
the color menus or a custom `#RRGGBB` value. Saturated green (`#00ff00`), yellow
(`#ffff00`) and red (`#ff0000`) are the defaults. Custom RGB values are sent
unchanged.
**Brightness (%)** controls the whole strip. The preview uses the
same colors and brightness as the wheel. **Test lights** runs a short sweep,
then flashes the whole strip for one second.

**Flash at (%)** sets a separate shift cue, defaulting to 95% of the game's
reported rev limit. The panel shows the corresponding RPM for the current car.
Lower it for an earlier cue; **Flashes per second** adjusts the rate from 1 to
20, defaulting to 10. The whole strip flashes in your chosen colors, even if
the progressive strip has not reached **Full lights (%)** yet. It returns to
progressive lights below the flash point and clears when telemetry stops.
This cue does not calculate the engine's optimum power-band shift point.

Colors and brightness are saved with the rev-light settings and restored after
reconnecting, changing the LED count or running a wheel test. **Wheel** controls
the wheel's static colors separately; reading those settings no longer replaces
the live rev colors. Custom live colors and brightness require a modern wheel
protocol; the controls are disabled on legacy wheels.

### Pedal calibration and limits

On **Home**, choose **Set max**, wait for the full range to reopen, then hold
the pedal at the position you want to count as fully pressed and choose
**Save max**. You can increase a previously shortened maximum, including when
the input bar already reads 100%. **Set min** works the same way at the released
position. Saving changes only the selected limit. **Cancel**, a 30-second
timeout, or closing the backend restores the previous limits. Keep the panel
open until the result appears, and adjust pedals outside a driving session.

Home shows instructions only while setting a limit. Each **Pedals** tab starts
with **Calibration and range**, followed by **Response curve** and **Other settings**.
The first row is a live input bar and percentage for that pedal, so you can
check the released and fully pressed positions without returning to Home.

On **Pedals**, choose the pedal and **Calibrate**. Keep it released during the
three-second preparation countdown. During the seven-second **Recording**
countdown, press it fully and release it. The instructions and current input
stay visible while recording. Successful results clear after eight seconds;
errors stay visible. If no movement was
detected, the panel asks you to retry. Completed recording resets Range Start
and Range End to 0–100%, so an old shortened limit does not constrain the new
range. Curves, direction and brake sensor ratio are preserved. Brake calibration
still requires Boxflat's opt-in under **Other** for supported pedals.

After calibration, check that releasing the pedal reads 0% and fully pressing
it reads 100%. The recording result is not a firmware acknowledgement of sensor
calibration. Cancelling after recording has begun restores the range limits but
cannot undo sensor calibration, so run calibration again before driving.

Number and text fields read typed keys only and never the clipboard, so there
is no paste. Focusing a number selects it for replacement; Up/Down or the
arrows step it, Return or leaving the field applies it within range, and Escape
restores it. Scrolling the panel never changes a value.

```sh
omarchy plugin disable crmne.moza
omarchy plugin remove crmne.moza
```

Disabling releases the devices. Removal leaves settings and presets intact.

## Development and attribution

```sh
mise install
make test
make validate
make build
```

See [architecture and coverage](docs/Architecture.md) and
[binary provenance](docs/Binary-provenance.md). Screenshots can be reproduced
with the [isolated capture host](docs/Screenshots.md).

See [upstream tracking and repository history](docs/Upstreams.md) for source
pins, verification and the Boxflat update command. Boxflat lives unmodified in
`vendor/boxflat/`, while plugin adaptations live in `backend/`.

This repository retains Boxflat's source and history. The adapter uses its
actual Python controls and callbacks, without showing GTK windows; QML supplies
the visible interface. Rust owns the wheelbase connection and drives rev lights
directly. Python settings requests share that connection.

Boxflat is by Tomasz Pakuła and contributors (GPL-3.0). This integration uses
the same license. moza-rev is by Francis De Brabandere and contributors (MIT;
[notice](docs/moza-rev-LICENSE)). The grouped card component comes from Carmine
Paolino's OmaStats (MIT; [notice](docs/OmaStats-LICENSE)). Neither this project
nor Boxflat is affiliated with MOZA Racing.
