// Game telemetry and wheelbase I/O stay in Rust. Boxflat submits complete
// settings frames; its Python process never sits in the RPM update path.
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
    leds: usize,
    enabled: bool,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            start: 80,
            full: 97,
            leds: 10,
            enabled: true,
        }
    }
}
impl Config {
    fn validate(&self) -> bool {
        self.start < self.full && self.full <= 100 && (1..=32).contains(&self.leds)
    }
    fn mask(&self, engine: &EngineState) -> u32 {
        if !self.enabled || engine.rpm <= 0 || engine.rpm_redline <= engine.rpm_idle {
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
    ] {
        if !ok {
            failures.push(name);
        }
    }
    listeners::assetto_corsa::spawn(9996, tx);
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
    loop {
        if wheel.is_none() && reconnect.elapsed() > Duration::from_secs(3) {
            reconnect = Instant::now();
            if let Some(p) = moza::find_wheelbase() {
                match Moza::open(&p, moza::detect_protocol(&p)) {
                    Ok(mut w) => {
                        // Finish the default telemetry setup before Boxflat
                        // reads/customises its palette through this connection.
                        w.send_rpm_bitmask(0, config.leds)?;
                        let mut r = w.try_clone_port()?;
                        r.set_timeout(Duration::from_millis(1))?;
                        raw = Some(r);
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
        let mut dirty = false;
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
                    dirty = true;
                }
                Command::Configure { .. } => emit(&out_tx, json!({"error": "Invalid RPM range"})),
                Command::Test => {
                    test = Some(Instant::now());
                    paused_until = Instant::now();
                }
                Command::Pause { milliseconds } => {
                    paused_until = Instant::now() + Duration::from_millis(milliseconds.min(30_000));
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
            dirty = true;
        }
        let active = packet.elapsed() < Duration::from_secs(2);
        let mut next = if active {
            last.as_ref().map_or(0, |u| config.mask(&u.engine))
        } else {
            0
        };
        if let Some(t) = test {
            let index = (t.elapsed().as_millis() / 100) as usize;
            if index >= config.leds * 2 {
                test = None;
            } else {
                next = 1 << (index % config.leds);
            }
            dirty = true;
        }
        if Instant::now() >= paused_until
            && ((dirty && mask != next) || sent.elapsed() > Duration::from_millis(250))
        {
            mask = next;
            if let Some(w) = wheel.as_mut()
                && let Err(e) = w.send_rpm_bitmask(mask, config.leds)
            {
                error = e.to_string();
                wheel = None;
                raw = None;
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
        if status.elapsed() >= Duration::from_millis(100) {
            emit(
                &out_tx,
                json!({"status": {
                    "connected": wheel.is_some(), "device": path, "error": error,
                    "game": if active { last.map(|u| u.game.name()) } else { None },
                    "rpm": if active { last.map_or(0, |u| u.engine.rpm) } else { 0 },
                    "redline": last.map_or(0, |u| u.engine.rpm_redline), "mask": mask,
                    "test": test.is_some(), "unavailableListeners": failures
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
}
