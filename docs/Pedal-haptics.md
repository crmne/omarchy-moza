# Pedal haptics

MOZA's Pedal Haptic Feedback module (Pit House calls it the "Vibration module")
drives up to three actuators, one each on the throttle, brake and clutch. It
connects over USB as `346e:002f` and exposes a CDC serial port, so Linux needs
no driver. Boxflat does not know the device and ignores it.

The module stores no effects or settings. The host decides what to play and
streams it, many times a second, while the game runs. Without a host sending
commands the motors stay silent, so the plugin's Rust engine does what Pit
House does on Windows: it reads game telemetry and streams the effects.

## Protocol

Frames use the usual MOZA serial framing with group `0x4d`, device `0x12`.
The module acknowledges each frame with group `0xcd`, device `0x21`.

```
7e 0b 4d 12  01 SUB PEDAL SLOT EN  DUR(2) FREQ(2) STRENGTH(2)  CHECKSUM
```

| Field | Values |
|---|---|
| `SUB` | `01` set (also stops), `02` query |
| `PEDAL` | `01` throttle, `02` brake, `03` clutch |
| `SLOT` | `00` TC, `01` ABS, `02` lockup, `03` brake threshold, `04` engine, `05` clutch bite point, `06` gear shift, `07` wheel spin, `08` road texture |
| `EN` | `01` on, `00` off |
| `DUR` | milliseconds, big-endian |
| `FREQ` | Hz, 10–100, big-endian; for road texture a suspension position 0–100 |
| `STRENGTH` | fraction of 65535, big-endian |

An effect plays for its duration after the last frame, so the host resends it
to hold it on. Stopping is the same frame with `EN` and every value zero; each
slot is stopped separately. The control box ports are labelled CLUTCH, BRAKE,
THROTTLE from left to right, the reverse of the pedal numbers.

The protocol was first documented by [AZOM](https://github.com/giantorth/AZOM)
(`docs/protocol/devices/pedal-haptics.md`, GPL-3.0). This plugin's own
implementation was written from that description and checked against Pit
House's traffic.

## Pit House's behaviour

On 2026-10-23 we recorded MOZA Pit House 1.4.1.13 writing to the module's
serial port while pressing every Test button and switching every effect on and
off in its "PHF-Official" preset. The findings:

- Switching an effect on sends nothing. Switching it off sends one stop frame
  for that slot. Sliders are not sent. All settings stay in Pit House.
- Strength is `65535 × intensity% / 100`, rounded down: 10% is 6553, 80% is
  52428.
- Engine vibration sweeps the frequency from 10 Hz up to the slider value as
  RPM rises, with a duration of one period (`1000 / Hz` ms), every 33 ms.
- ABS sends 66 ms every 45 ms; TC 200 ms every ~105 ms; gear shift 200 ms;
  lockup 50 ms; clutch bite point 200 ms; brake threshold 50 ms. Road texture
  sends 100 ms frames whose position dips from 100 towards 37 over bumps.

The plugin follows these encodings and timings. Its defaults are the
PHF-Official preset:

| Pedal | On by default |
|---|---|
| Clutch | Engine (100 Hz, 10%), bite point (70% travel, 50 Hz, 50%) |
| Brake | Engine (100 Hz, 10%), ABS (30 Hz, 100%), gear shift (100 Hz, 80%) |
| Throttle | Engine (100 Hz, 10%), TC (50 Hz, 80%), gear shift (100 Hz, 80%) |

## What triggers each effect

| Effect | Plays when | Needs from the game |
|---|---|---|
| Engine | RPM is inside the range; frequency follows RPM | RPM |
| Gear shift | the gear changes, except into neutral | gear |
| TC | the car's traction control intervenes | TC active |
| ABS | the car's ABS intervenes | ABS active |
| Wheel spin | a wheel's slip ratio exceeds 15% with throttle applied | slip, throttle |
| Wheel lockup | a wheel's slip ratio is below −20% under braking, above 2 m/s | slip, brake, speed |
| Brake threshold | brake travel reaches the trigger | brake |
| Clutch bite point | clutch travel is within the zone around the trigger | clutch |
| Road texture | suspension moves, while above 2 m/s | suspension travel, speed |

Per game:

- **Assetto Corsa:** the CSP companion sends CSP's own ABS and TC activity,
  slip ratios and suspension travel.
- **Automobilista 2 / Project CARS 2:** UDP `sCarFlags` bits `0x10` (ABS) and
  `0x40` (TC) light while the aid acts but also flicker, so ABS counts only
  above 6% brake and TC above 6% throttle. UDP has no tyre radius: each wheel's
  radius is learned as speed ÷ wheel rad/s while coasting straight above
  10 m/s, and slip is reported once all four are known.
- **Forza:** slip is normalised to the grip limit (±1), so it is scaled by 0.2
  into a slip ratio. The Dash format adds inputs and gear; Sled has neither.
  Forza reports no ABS or TC activity.
- **BeamNG:** OutGauge's ABS light is set exactly while ABS intervenes. Its TC
  light blinks while traction or stability control acts and is solid when
  switched off, so TC counts only within 600 ms of a blink, on the throttle.

The bite point zone spans up to 20% of travel either side of the trigger at
100% smoothness. Effects whose input a game does not report stay silent.
All effects stop 300 ms after telemetry stops, when vibration is switched off,
and when the plugin exits. A fresh connection first stops every slot, in case
an earlier session left one running.

**Test** plays one effect for three seconds with its current settings, even if
it is switched off, and silences the others meanwhile.

The module can also be connected behind a wheelbase. Pit House then reaches it
through the base with an extended address. The plugin only supports the
module's own USB connection.
