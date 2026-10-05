# Screenshot provenance

`preview.png` is a composition of the real Home and Rev lights panels. The
individual captures are in `screenshots/`. All use production QML controls,
Omarchy's Ristretto palette, JetBrainsMono Nerd Font, and 10 px corner rounding.
The arrangement follows the marketplace preview of
[omarchy-hyprmoncfg](https://github.com/crmne/omarchy-hyprmoncfg).

The capture host uses Boxflat's existing demo model to build the settings
pages. Fixtures supply 6,420 RPM against a 6,800 RPM redline, eight illuminated
LEDs, −18° steering, and throttle/brake/clutch inputs at 72%/26%/8%. These are
illustrative input values, not measurements from a driving session. The
optional E-Stop row and handbrake group are hidden in the sample configuration.

Production `MozaPanel.qml`, `MozaService.qml` and `controls/` are copied into a
temporary host. The copied service's backend process is disabled, and fixtures
are passed through its real `ingest` method. The host has its own HOME and
runtime directory. It never opens hardware or telemetry ports, applies device
settings, or replaces the user's shell or theme.

Only Omarchy's layer-shell window plumbing is adapted to an offscreen floating
window; its actual panel surface is preserved. A 2× device scale produces
sharp text. The host also checks that simulated disconnection hides the icon,
closes the popup and leaves the service ready, and reconnection restores it.

On an Omarchy machine with the documented Python dependencies and Quickshell:

```sh
gpu-lock /usr/bin/python3 -B tools/capture/capture.py
```

`gpu-lock` is the maintainer's machine-wide GPU mutex; use an equivalent
exclusive GPU lock on other capture machines. The script explicitly requests
OpenGL and refuses a software-rendered capture. The checked captures used an
NVIDIA GeForce RTX 3090. Local renderer details are in the ignored
`screenshots/capture.log`.

The background comes from Omarchy's Ristretto
`themes/ristretto/backgrounds/0-launch.png`, used under
[Omarchy's MIT license](Omarchy-LICENSE).
The theme files and background are read from the installed Omarchy package;
they are not vendored. The preview composition adds a dark overlay and soft
shadows. No UI elements are painted over the captured controls.

`setup.png` shows the real first-run panel with simulated missing dependencies.
The capture also verifies that setup remains reachable without a connected wheel.
