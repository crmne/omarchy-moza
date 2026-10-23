// Game telemetry and wheelbase I/O stay in Rust. Boxflat submits complete
// settings frames; its Python process never sits in the RPM update path.
mod assetto_corsa;
mod devices;

use moza_rev::{
    listeners::{self, EngineState, Update},
    moza::{self, Moza},
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    io::{self, BufRead, Read, Write},
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

#[derive(Clone, Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct Config {
    start: u8,
    full: u8,
    flash: u8,
    flash_hz: u8,
    leds: usize,
    enabled: bool,
    colors: [String; 3],
    brightness: u8,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            start: 80,
            full: 97,
            flash: 95,
            flash_hz: 10,
            leds: 10,
            enabled: true,
            // Saturated LED colors, not pastel screen-theme swatches. Mixing
            // all three channels makes the physical LEDs pale or pink.
            colors: ["#00ff00", "#ffff00", "#ff0000"].map(String::from),
            brightness: 100,
        }
    }
}
impl Config {
    fn validate(&self) -> bool {
        self.start < self.full
            && self.full <= 100
            && (1..=100).contains(&self.flash)
            && (1..=20).contains(&self.flash_hz)
            && (1..=32).contains(&self.leds)
            && self.brightness <= 100
            && self.colors.iter().all(|c| {
                c.len() == 7
                    && c.starts_with('#')
                    && c.as_bytes()[1..].iter().all(u8::is_ascii_hexdigit)
            })
    }
    fn palette_frames(&self) -> Vec<Vec<u8>> {
        let mut frames = Vec::new();
        for start in (0..self.leds).step_by(5) {
            let mut payload = Vec::new();
            for offset in 0..5 {
                let index = (start + offset).min(self.leds - 1);
                let zone = if index * 10 < self.leds * 5 {
                    0
                } else if index * 10 < self.leds * 8 {
                    1
                } else {
                    2
                };
                payload.push(index as u8);
                for channel in 0..3 {
                    payload.push(
                        u8::from_str_radix(
                            &self.colors[zone][1 + channel * 2..3 + channel * 2],
                            16,
                        )
                        .unwrap(),
                    );
                }
            }
            frames.push(wheel_frame(&[0x19, 0], &payload));
        }
        frames.push(wheel_frame(&[0x1b, 0, 0xff], &[self.brightness]));
        frames
    }
    fn mask(&self, engine: &EngineState) -> u32 {
        // Telemetry is unauthenticated UDP: a non-positive redline would make
        // the light range empty or inverted, so treat it as no data.
        if !self.has_live_engine(engine) {
            return 0;
        }
        let rpm = i64::from(engine.rpm) * 100;
        let first = i64::from(engine.rpm_redline) * i64::from(self.start);
        let last = i64::from(engine.rpm_redline) * i64::from(self.full);
        if rpm < first {
            return 0;
        }
        let lit = 1 + (rpm.min(last) - first) * (self.leds - 1) as i64 / (last - first);
        if lit == 32 {
            u32::MAX
        } else {
            (1u32 << lit) - 1
        }
    }
    fn has_live_engine(&self, engine: &EngineState) -> bool {
        self.enabled
            && engine.rpm > 0
            && engine.rpm_redline > 0
            && engine.rpm_redline > engine.rpm_idle
    }
    fn full_mask(&self) -> u32 {
        u32::MAX >> (32 - self.leds)
    }
}

// Configurable flashes per second, with an immediate lit phase at the shift
// point. The clock runs independently of UDP packet arrival or refresh rate.
fn flash_mask(mask: u32, elapsed: Duration, hz: u8) -> u32 {
    if (elapsed.as_millis() * u128::from(hz) * 2 / 1000).is_multiple_of(2) {
        mask
    } else {
        0
    }
}

#[derive(Default)]
struct ShiftFlash {
    started: Option<Instant>,
}
impl ShiftFlash {
    fn mask(&mut self, config: &Config, engine: Option<&EngineState>, now: Instant) -> u32 {
        let steady = engine.map_or(0, |engine| config.mask(engine));
        let shift_due = engine.is_some_and(|engine| {
            config.has_live_engine(engine)
                && i64::from(engine.rpm) * 100
                    >= i64::from(engine.rpm_redline) * i64::from(config.flash)
        });
        if shift_due {
            let started = *self.started.get_or_insert(now);
            flash_mask(
                config.full_mask(),
                now.duration_since(started),
                config.flash_hz,
            )
        } else {
            self.started = None;
            steady
        }
    }
}

fn test_mask(config: &Config, elapsed: Duration) -> Option<u32> {
    let sweep = Duration::from_millis(config.leds as u64 * 200);
    if elapsed < sweep {
        Some(1 << ((elapsed.as_millis() / 100) as usize % config.leds))
    } else if elapsed < sweep + Duration::from_secs(1) {
        Some(flash_mask(
            config.full_mask(),
            elapsed - sweep,
            config.flash_hz,
        ))
    } else {
        None
    }
}

// Modern wheel commands from Boxflat's serial.yml. Escape custom RGB bytes
// exactly like moza-rev: body 0x7e bytes contribute twice to the wire checksum.
fn wheel_frame(command: &[u8], payload: &[u8]) -> Vec<u8> {
    let mut frame = vec![0x7e, (command.len() + payload.len()) as u8, 0x3f, 0x17];
    frame.extend_from_slice(command);
    frame.extend_from_slice(payload);
    let checksum = (13
        + frame.iter().map(|b| u32::from(*b)).sum::<u32>()
        + 0x7e * frame[2..].iter().filter(|b| **b == 0x7e).count() as u32) as u8;
    frame.push(checksum);
    let mut wire = frame[..2].to_vec();
    for byte in &frame[2..] {
        wire.push(*byte);
        if *byte == 0x7e {
            wire.push(*byte);
        }
    }
    wire
}

fn drive_lights(
    wheel: &mut Moza,
    port: &mut dyn Write,
    config: &Config,
    mask: u32,
    restore_palette: bool,
    modern: bool,
) -> io::Result<()> {
    // send_rpm_bitmask initializes the wheel on connect or LED-count changes.
    // Our saved palette must follow that setup, never race it via Python reads.
    wheel.send_rpm_bitmask(mask, config.leds)?;
    if modern && restore_palette {
        for frame in config.palette_frames() {
            port.write_all(&frame)?;
        }
        port.flush()?;
    }
    Ok(())
}

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
enum Command {
    Configure { config: Config },
    Write { frame: Vec<u8> },
    Test,
    Pause { milliseconds: u64 },
    Quit,
}

fn emit(tx: &mpsc::SyncSender<Value>, value: Value) {
    // UI backpressure must never delay the wheel. Boxflat retries reads.
    let _ = tx.try_send(value);
}

fn main() -> io::Result<()> {
    let (out_tx, out_rx) = mpsc::sync_channel::<Value>(512);
    thread::spawn(move || {
        let mut output = io::stdout().lock();
        for record in out_rx {
            if writeln!(output, "{record}")
                .and_then(|_| output.flush())
                .is_err()
            {
                break;
            }
        }
    });
    let (cmd_tx, cmd_rx) = mpsc::sync_channel(256);
    thread::spawn(move || {
        let mut input = io::stdin().lock();
        loop {
            let mut line = String::new();
            let result = input.by_ref().take(65537).read_line(&mut line);
            if !matches!(result, Ok(1..=65536)) {
                break;
            }
            if let Ok(command) = serde_json::from_str::<Command>(&line)
                && cmd_tx.send(command).is_err()
            {
                return;
            }
        }
        let _ = cmd_tx.send(Command::Quit);
    });
    let (tx, rx) = mpsc::channel::<Update>();
    let mut failures = Vec::new();
    for (name, ok) in [
        (
            "Wreckfest 2 :23123",
            listeners::wreckfest_2::spawn(23123, tx.clone()),
        ),
        (
            "DiRT / F1 :20777",
            listeners::codemasters_legacy::spawn(20777, tx.clone()),
        ),
        (
            "AMS2 / PC2 :5606",
            listeners::madness::spawn(5606, tx.clone()),
        ),
        ("BeamNG :4444", listeners::outgauge::spawn(4444, tx.clone())),
        ("Forza :9999", listeners::forza::spawn(9999, tx.clone())),
        (
            "Assetto Corsa :9997",
            assetto_corsa::spawn(9997, tx.clone()),
        ),
    ] {
        if !ok {
            failures.push(name);
        }
    }
    drop(tx);
    let mut config = Config::default();
    let mut wheel: Option<Moza> = None;
    let mut raw: Option<Box<dyn serialport::SerialPort>> = None;
    let mut path = String::new();
    let mut reconnect = Instant::now() - Duration::from_secs(4);
    let mut sent = Instant::now();
    let mut status = Instant::now();
    let mut packet = Instant::now() - Duration::from_secs(3);
    let mut last: Option<Update> = None;
    let mut mask = 0;
    let mut test: Option<Instant> = None;
    let mut paused_until = Instant::now();
    let mut error = String::new();
    let mut modern = false;
    let mut palette_dirty = true;
    let mut shift_flash = ShiftFlash::default();
    loop {
        if wheel.is_none() && reconnect.elapsed() > Duration::from_secs(3) {
            reconnect = Instant::now();
            if let Some(p) = devices::find_wheelbase() {
                match Moza::open(&p, moza::detect_protocol(&p)) {
                    Ok(mut w) => {
                        // Finish protocol setup before sharing the connection
                        // with Boxflat. The saved palette follows below.
                        w.send_rpm_bitmask(0, config.leds)?;
                        let mut r = w.try_clone_port()?;
                        r.set_timeout(Duration::from_millis(1))?;
                        raw = Some(r);
                        modern = moza::detect_protocol(&p) == moza::Protocol::Modern;
                        palette_dirty = true;
                        wheel = Some(w);
                        path = p;
                        error.clear();
                        sent = Instant::now() - Duration::from_secs(1);
                    }
                    Err(e) => error = e.to_string(),
                }
            } else {
                path.clear();
            }
        }
        // Bound settings work each tick so a preset cannot starve telemetry.
        for _ in 0..8 {
            let Ok(cmd) = cmd_rx.try_recv() else {
                break;
            };
            match cmd {
                Command::Quit => {
                    if let Some(w) = wheel.as_mut() {
                        let _ = w.send_rpm_bitmask(0, config.leds);
                    }
                    return Ok(());
                }
                Command::Configure { config: next } if next.validate() => {
                    config = next;
                    palette_dirty = true;
                    shift_flash = ShiftFlash::default();
                }
                Command::Configure { .. } => {
                    emit(&out_tx, json!({"error": "Invalid rev-light settings"}))
                }
                Command::Test => {
                    test = Some(Instant::now());
                    paused_until = Instant::now();
                    palette_dirty = true;
                }
                Command::Pause { milliseconds } => {
                    paused_until = Instant::now() + Duration::from_millis(milliseconds.min(30_000));
                    palette_dirty = true;
                }
                Command::Write { frame } => {
                    // Boxflat provides complete wire frames, including checksum.
                    if frame.len() >= 6
                        && frame.len() <= 128
                        && frame[0] == 0x7e
                        && let Some(port) = raw.as_mut()
                        && let Err(e) = port.write_all(&frame)
                    {
                        error = e.to_string();
                        wheel = None;
                        raw = None;
                    }
                }
            }
        }
        // Keep the freshest packet if a settings burst briefly got ahead.
        for update in rx.try_iter().take(4096) {
            last = Some(update);
            packet = Instant::now();
        }
        let active = packet.elapsed() < Duration::from_secs(2);
        let mut next = shift_flash.mask(
            &config,
            last.as_ref().filter(|_| active).map(|u| &u.engine),
            Instant::now(),
        );
        if let Some(t) = test {
            if let Some(preview) = test_mask(&config, t.elapsed()) {
                next = preview;
            } else {
                test = None;
            }
        }
        if Instant::now() >= paused_until
            && (palette_dirty || mask != next || sent.elapsed() > Duration::from_millis(250))
        {
            mask = next;
            if let (Some(w), Some(port)) = (wheel.as_mut(), raw.as_mut()) {
                match drive_lights(w, port, &config, mask, palette_dirty, modern) {
                    Ok(()) => palette_dirty = false,
                    Err(e) => {
                        error = e.to_string();
                        wheel = None;
                        raw = None;
                    }
                }
            }
            sent = Instant::now();
        }
        if let Some(port) = raw.as_mut() {
            let mut bytes = [0; 1024];
            match port.read(&mut bytes) {
                Ok(n) if n > 0 => emit(&out_tx, json!({"serial": &bytes[..n]})),
                Err(e)
                    if ![io::ErrorKind::TimedOut, io::ErrorKind::WouldBlock]
                        .contains(&e.kind()) =>
                {
                    error = e.to_string();
                    wheel = None;
                    raw = None;
                }
                _ => {}
            }
        }
        if status.elapsed() >= Duration::from_millis(20) {
            emit(
                &out_tx,
                json!({"status": {
                    "connected": wheel.is_some(), "device": path, "error": error,
                    "game": if active { last.map(|u| u.game.name()) } else { None },
                    "rpm": if active { last.map_or(0, |u| u.engine.rpm) } else { 0 },
                    "redline": last.map_or(0, |u| u.engine.rpm_redline), "mask": mask,
                    "test": test.is_some(), "unavailableListeners": failures,
                    "customColors": wheel.is_some() && modern
                }}),
            );
            status = Instant::now();
        }
        thread::sleep(Duration::from_millis(2));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn engine(rpm: i32) -> EngineState {
        EngineState {
            rpm,
            rpm_redline: 6800,
            rpm_idle: 800,
        }
    }
    #[test]
    fn exact_thresholds() {
        let c = Config::default();
        assert_eq!(c.mask(&engine(5439)), 0);
        assert_eq!(c.mask(&engine(5440)), 1);
        assert_eq!(c.mask(&engine(6595)), 511);
        assert_eq!(c.mask(&engine(6596)), 1023);
        assert_eq!(c.mask(&engine(9000)), 1023);
    }
    #[test]
    fn shift_flash_starts_before_full_and_follows_the_clock() {
        let config = Config::default();
        let mut flash = ShiftFlash::default();
        let now = Instant::now();
        assert_eq!(flash.mask(&config, Some(&engine(6459)), now), 255);
        for (ms, expected) in [(0, 1023), (49, 1023), (50, 0), (99, 0), (100, 1023)] {
            assert_eq!(
                flash.mask(
                    &config,
                    Some(&engine(6460)),
                    now + Duration::from_millis(ms)
                ),
                expected
            );
        }
        // A gear change immediately restores the progressive strip and resets
        // the phase, even if the previous flash was off.
        assert_eq!(
            flash.mask(
                &config,
                Some(&engine(6459)),
                now + Duration::from_millis(400)
            ),
            255
        );
        assert_eq!(
            flash.mask(
                &config,
                Some(&engine(6800)),
                now + Duration::from_millis(410)
            ),
            1023
        );
    }
    #[test]
    fn shift_flash_clears_on_stale_invalid_or_disabled_telemetry() {
        let now = Instant::now();
        let config = Config::default();
        for missing in [
            None,
            Some(engine(0)),
            Some(EngineState {
                rpm_redline: 0,
                ..engine(6800)
            }),
        ] {
            let mut flash = ShiftFlash::default();
            assert_eq!(flash.mask(&config, Some(&engine(6800)), now), 1023);
            assert_eq!(
                flash.mask(&config, missing.as_ref(), now + Duration::from_millis(250)),
                0
            );
            assert!(flash.started.is_none());
        }
        let mut flash = ShiftFlash::default();
        flash.mask(&config, Some(&engine(6800)), now);
        assert_eq!(
            flash.mask(
                &Config {
                    enabled: false,
                    ..config
                },
                Some(&engine(6800)),
                now
            ),
            0
        );
        assert!(flash.started.is_none());
    }
    #[test]
    fn shift_flash_supports_low_redlines_and_one_or_32_leds() {
        let now = Instant::now();
        for leds in [1, 10, 32] {
            let config = Config {
                leds,
                ..Default::default()
            };
            let engine = EngineState {
                rpm: 97,
                rpm_redline: 100,
                rpm_idle: 20,
            };
            let full = u32::MAX >> (32 - leds);
            let mut flash = ShiftFlash::default();
            assert_eq!(flash.mask(&config, Some(&engine), now), full);
            assert_eq!(
                flash.mask(&config, Some(&engine), now + Duration::from_millis(50)),
                0
            );
            let below = EngineState { rpm: 94, ..engine };
            assert_ne!(
                flash.mask(&config, Some(&below), now + Duration::from_millis(51)),
                0
            );
            assert!(flash.started.is_none());
        }
    }
    #[test]
    fn flash_point_is_independent_of_the_progressive_range() {
        let now = Instant::now();
        let early = Config {
            flash: 50,
            ..Default::default()
        };
        let mut flash = ShiftFlash::default();
        assert_eq!(early.mask(&engine(3400)), 0);
        assert_eq!(flash.mask(&early, Some(&engine(3400)), now), 1023);
        let late = Config {
            flash: 100,
            ..Default::default()
        };
        let mut flash = ShiftFlash::default();
        assert_eq!(flash.mask(&late, Some(&engine(6799)), now), 1023);
        assert_eq!(
            flash.mask(&late, Some(&engine(6799)), now + Duration::from_millis(50)),
            1023
        );
        assert!(flash.started.is_none());
    }
    #[test]
    fn custom_flash_rates_have_the_requested_period() {
        for hz in 1..=20 {
            let half_period = 1000_u64.div_ceil(2 * u64::from(hz));
            let period = 1000_u64.div_ceil(u64::from(hz));
            assert_eq!(flash_mask(1023, Duration::ZERO, hz), 1023);
            assert_eq!(flash_mask(1023, Duration::from_millis(half_period), hz), 0);
            assert_eq!(flash_mask(1023, Duration::from_millis(period), hz), 1023);
            assert_eq!(flash_mask(1023, Duration::from_secs(1), hz), 1023);
        }
    }
    #[test]
    fn test_lights_sweeps_then_previews_shift_flash() {
        for leds in [1, 10, 32] {
            let config = Config {
                leds,
                ..Default::default()
            };
            let sweep = Duration::from_millis(leds as u64 * 200);
            assert_eq!(test_mask(&config, Duration::ZERO), Some(1));
            assert_eq!(
                test_mask(&config, sweep - Duration::from_millis(1)),
                Some(1 << (leds - 1))
            );
            assert_eq!(test_mask(&config, sweep), Some(u32::MAX >> (32 - leds)));
            assert_eq!(
                test_mask(&config, sweep + Duration::from_millis(50)),
                Some(0)
            );
            assert_eq!(test_mask(&config, sweep + Duration::from_secs(1)), None);
        }
    }
    #[test]
    fn low_revving_cars_fill_the_strip_at_their_own_limit() {
        for redline in [100, 500, 2000, 6500] {
            let engine = EngineState {
                rpm: redline * 97 / 100,
                rpm_redline: redline,
                rpm_idle: redline / 5,
            };
            assert_eq!(Config::default().mask(&engine), 1023);
        }
    }
    #[test]
    fn rejects_invalid_configuration() {
        for c in [
            Config {
                start: 97,
                ..Default::default()
            },
            Config {
                full: 101,
                ..Default::default()
            },
            Config {
                flash: 0,
                ..Default::default()
            },
            Config {
                flash: 101,
                ..Default::default()
            },
            Config {
                flash_hz: 0,
                ..Default::default()
            },
            Config {
                flash_hz: 21,
                ..Default::default()
            },
            Config {
                leds: 0,
                ..Default::default()
            },
            Config {
                leds: 33,
                ..Default::default()
            },
        ] {
            assert!(!c.validate());
        }
    }
    #[test]
    fn ignores_non_positive_redline() {
        for (rpm_redline, rpm_idle) in [(0, -1), (-5, -10), (i32::MIN + 1, i32::MIN)] {
            for rpm in [1, 6800, i32::MAX] {
                let engine = EngineState {
                    rpm,
                    rpm_redline,
                    rpm_idle,
                };
                assert_eq!(Config::default().mask(&engine), 0);
            }
        }
    }
    #[test]
    fn handles_disabled_and_full_width() {
        assert_eq!(
            Config {
                enabled: false,
                ..Default::default()
            }
            .mask(&engine(6800)),
            0
        );
        assert_eq!(
            Config {
                leds: 32,
                ..Default::default()
            }
            .mask(&engine(6800)),
            u32::MAX
        );
    }

    #[test]
    fn validates_colors_and_brightness() {
        for color in ["red", "#12345", "#1234567", "#ggffff", "#é1234"] {
            let mut c = Config::default();
            c.colors[0] = color.into();
            assert!(!c.validate());
        }
        assert!(
            !Config {
                brightness: 101,
                ..Default::default()
            }
            .validate()
        );
        let old: Config =
            serde_json::from_str(r#"{"start":75,"full":98,"leds":10,"enabled":true}"#).unwrap();
        assert_eq!(old.colors, Config::default().colors);
        assert_eq!(old.start, 75);
        assert!(old.validate());
    }

    #[test]
    fn pads_palette_without_addressing_extra_leds() {
        for leds in 1..=32 {
            let c = Config {
                leds,
                ..Default::default()
            };
            let frames = c.palette_frames();
            assert_eq!(frames.len(), leds.div_ceil(5) + 1);
            for (batch, frame) in frames[..frames.len() - 1].iter().enumerate() {
                // Default RGB values contain no escaped bytes.
                for offset in 0..5 {
                    let index = (batch * 5 + offset).min(leds - 1);
                    let record = &frame[6 + offset * 4..10 + offset * 4];
                    assert_eq!(record[0] as usize, index);
                    let expected = if index * 10 < leds * 5 {
                        [0, 255, 0]
                    } else if index * 10 < leds * 8 {
                        [255, 255, 0]
                    } else {
                        [255, 0, 0]
                    };
                    assert_eq!(record[1..], expected);
                }
            }
            assert_eq!(&frames.last().unwrap()[4..8], &[0x1b, 0, 0xff, 100]);
        }
    }

    #[test]
    fn custom_colors_escape_payload_and_checksum() {
        // Body 0x7e is doubled and both copies contribute to the checksum.
        assert_eq!(
            wheel_frame(&[0x19, 0], &[0, 0x7e, 0, 0]),
            vec![0x7e, 6, 0x3f, 0x17, 0x19, 0, 0, 0x7e, 0x7e, 0, 0, 0xfc]
        );
        assert_eq!(
            wheel_frame(&[0x19, 0], &[0, 0, 0, 0x7e]),
            vec![0x7e, 6, 0x3f, 0x17, 0x19, 0, 0, 0, 0, 0x7e, 0x7e, 0xfc]
        );
        // This particular payload produces a checksum of 0x7e.
        assert_eq!(
            wheel_frame(&[0x19, 0], &[0, 125, 1, 0]),
            vec![0x7e, 6, 0x3f, 0x17, 0x19, 0, 0, 125, 1, 0, 0x7e, 0x7e]
        );
    }

    #[cfg(unix)]
    #[test]
    fn legacy_wheels_do_not_receive_modern_palette_commands() {
        use serialport::SerialPort;
        let (_peer, port) = serialport::TTYPort::pair().unwrap();
        let mut wheel = Moza::open(&port.name().unwrap(), moza::Protocol::Legacy).unwrap();
        let mut palette_sink = Vec::new();
        drive_lights(
            &mut wheel,
            &mut palette_sink,
            &Config::default(),
            1,
            true,
            false,
        )
        .unwrap();
        assert!(palette_sink.is_empty());
    }

    #[cfg(unix)]
    #[test]
    fn saved_palette_follows_initialization_resize_and_test_restore() {
        use serialport::SerialPort;
        fn drain(peer: &mut serialport::TTYPort) -> Vec<u8> {
            let mut bytes = Vec::new();
            let mut buffer = [0; 1024];
            loop {
                match peer.read(&mut buffer) {
                    Ok(n) if n > 0 => bytes.extend_from_slice(&buffer[..n]),
                    Err(e) if e.kind() == io::ErrorKind::TimedOut => break,
                    result => panic!("unexpected serial read: {result:?}"),
                }
            }
            bytes
        }
        let (mut peer, mut port) = serialport::TTYPort::pair().unwrap();
        peer.set_timeout(Duration::from_millis(10)).unwrap();
        let mut wheel = Moza::open(&port.name().unwrap(), moza::Protocol::Modern).unwrap();
        let mut c = Config {
            colors: ["#112233", "#445566", "#778899"].map(String::from),
            brightness: 37,
            ..Default::default()
        };
        for leds in [10, 7, 7] {
            c.leds = leds;
            drive_lights(&mut wheel, &mut port, &c, 1, true, true).unwrap();
            let bytes = drain(&mut peer);
            assert!(bytes.ends_with(&c.palette_frames().concat()));
            drive_lights(&mut wheel, &mut port, &c, 3, false, true).unwrap();
            let heartbeat = drain(&mut peer);
            assert_eq!(&heartbeat[4..6], &[0x1a, 0]);
            assert_eq!(heartbeat.len(), 9);
        }
        // A fresh connection repeats setup, then restores the saved palette.
        drop(wheel);
        let mut wheel = Moza::open(&port.name().unwrap(), moza::Protocol::Modern).unwrap();
        drive_lights(&mut wheel, &mut port, &c, 0, true, true).unwrap();
        assert!(drain(&mut peer).ends_with(&c.palette_frames().concat()));
    }
}
