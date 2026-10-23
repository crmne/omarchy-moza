//! Listeners for games whose UDP telemetry carries more than the engine:
//! Automobilista 2 / Project CARS 2, Forza and BeamNG. They replace
//! moza-rev's engine-only listeners on the same ports.
use crate::telemetry::{Telemetry, Wheels};
use moza_rev::{
    listeners::{EngineState, GameId},
    madness,
};
use std::{
    net::UdpSocket,
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

pub trait Parser: Send + 'static {
    fn parse(&mut self, bytes: &[u8], now: Instant) -> Option<Telemetry>;
}

pub fn spawn(port: u16, parser: impl Parser, tx: mpsc::Sender<Telemetry>) -> bool {
    // AMS2 broadcasts, so listen on every address like moza-rev does.
    listen(("0.0.0.0", port), parser, tx)
}

/// For senders on this computer only, such as the Proton helper.
pub fn spawn_local(port: u16, parser: impl Parser, tx: mpsc::Sender<Telemetry>) -> bool {
    listen(("127.0.0.1", port), parser, tx)
}

fn listen(address: (&str, u16), mut parser: impl Parser, tx: mpsc::Sender<Telemetry>) -> bool {
    let port = address.1;
    let Ok(socket) = UdpSocket::bind(address) else {
        return false;
    };
    thread::Builder::new()
        .name(format!("telemetry-{port}"))
        .spawn(move || {
            let mut buffer = [0; 2048];
            while let Ok(n) = socket.recv(&mut buffer) {
                if let Some(telemetry) = parser.parse(&buffer[..n], Instant::now())
                    && tx.send(telemetry).is_err()
                {
                    break;
                }
            }
        })
        .is_ok()
}

fn f32_at(bytes: &[u8], offset: usize) -> f32 {
    f32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap())
}
fn i32_at(bytes: &[u8], offset: usize) -> i32 {
    i32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap())
}
fn wheels(bytes: &[u8], offset: usize) -> Option<Wheels> {
    let w = [0, 1, 2, 3].map(|i| f32_at(bytes, offset + i * 4));
    w.iter().all(|v| v.is_finite()).then_some(w)
}
fn pedal(value: u8) -> f32 {
    f32::from(value) / 255.0
}

/// AMS2 and Project CARS 2 ("Project CARS 2" UDP, packet type 0).
///
/// The flag bits for ABS and TC light while the aid acts, but also flicker
/// at other times, so each is gated on its pedal. UDP has no tyre radius:
/// each wheel's radius is learned while coasting, and slip is reported only
/// once it is known.
#[derive(Default)]
pub struct Ams2 {
    radius: [Option<f32>; 4],
}

const AMS2_IDLE: i32 = 800;
const CAR_ABS: u8 = 0x10;
const CAR_TCS: u8 = 0x40;

impl Parser for Ams2 {
    fn parse(&mut self, bytes: &[u8], _: Instant) -> Option<Telemetry> {
        let d = madness::TelemetryPacket::from_bytes(bytes)?.data;
        let (rpm, redline, speed, flags) = (d.rpm, d.max_rpm, d.speed, d.car_flags);
        if redline == 0 || !speed.is_finite() {
            return None;
        }
        let (throttle, brake, clutch) = (
            pedal(d.unfiltered_throttle),
            pedal(d.unfiltered_brake),
            pedal(d.unfiltered_clutch),
        );
        let gear = match d.gear_num_gears & 0x0f {
            15 => -1,
            g => i32::from(g),
        };
        // Rolling forward is negative; the value is in rad/s.
        let spin = d.tyre_rps.map(f32::abs);
        let coasting = speed > 10.0 && throttle < 0.1 && brake < 0.02;
        for (radius, omega) in self.radius.iter_mut().zip(spin) {
            if coasting && omega > 1.0 {
                let measured = speed / omega;
                if (0.15..=0.6).contains(&measured) {
                    *radius = Some(radius.map_or(measured, |r| r + (measured - r) * 0.05));
                }
            }
        }
        let slip = (self.radius.iter().all(Option::is_some) && speed > 1.0).then(|| {
            [0, 1, 2, 3].map(|i| (spin[i] * self.radius[i].unwrap() - speed) / speed.max(1.0))
        });
        Some(Telemetry {
            gear: Some(gear),
            speed: Some(speed),
            throttle: Some(throttle),
            brake: Some(brake),
            clutch: Some(clutch),
            abs: Some(flags & CAR_ABS != 0 && brake > 0.06),
            tc: Some(flags & CAR_TCS != 0 && throttle > 0.06),
            slip,
            suspension: Some(d.suspension_travel).filter(|w| w.iter().all(|v| v.is_finite())),
            ..Telemetry::engine(
                GameId::Ams2.name(),
                EngineState {
                    rpm: i32::from(rpm),
                    rpm_redline: i32::from(redline),
                    rpm_idle: AMS2_IDLE,
                },
            )
        })
    }
}

/// Forza "Data Out": Sled (232 bytes) or Dash in its Motorsport 7 (311),
/// Motorsport 2023 (331) and Horizon (323/324, 12 extra bytes) layouts.
/// Forza has no ABS or TC flags; its slip ratio is normalised so that ±1
/// is the grip limit, and is scaled here to the ratios other games report.
#[derive(Default)]
pub struct Forza;

const FORZA_SLIP_SCALE: f32 = 0.2;

impl Parser for Forza {
    fn parse(&mut self, b: &[u8], _: Instant) -> Option<Telemetry> {
        let dash = match b.len() {
            232 => None,
            311 | 331 => Some(232),
            323 | 324 => Some(244),
            _ => return None,
        };
        let (redline, idle, rpm) = (f32_at(b, 8), f32_at(b, 12), f32_at(b, 16));
        if i32_at(b, 0) == 0 || !redline.is_finite() || redline <= idle.max(1.0) || !rpm.is_finite()
        {
            return None;
        }
        let velocity = [32, 36, 40].map(|o| f32_at(b, o));
        let mut t = Telemetry {
            speed: Some(velocity.iter().map(|v| v * v).sum::<f32>().sqrt()),
            slip: wheels(b, 84).map(|w| w.map(|s| s * FORZA_SLIP_SCALE)),
            suspension: wheels(b, 196),
            ..Telemetry::engine(
                GameId::Forza.name(),
                EngineState {
                    rpm: rpm as i32,
                    rpm_redline: redline as i32,
                    rpm_idle: idle as i32,
                },
            )
        };
        if let Some(d) = dash {
            t.speed = Some(f32_at(b, d + 12)).filter(|v| v.is_finite());
            t.throttle = Some(pedal(b[d + 71]));
            t.brake = Some(pedal(b[d + 72]));
            t.clutch = Some(pedal(b[d + 73]));
            t.gear = Some(match b[d + 75] {
                0 => -1,
                g => i32::from(g),
            });
        }
        Some(t)
    }
}

/// BeamNG OutGauge. ABS is a clean "intervening" bit. The TC bit blinks
/// while traction or stability control acts and stays lit when it is off,
/// so only blinking counts. OutGauge has no wheel slip or suspension.
pub struct BeamNg {
    redline: f32,
    tc_lit: bool,
    tc_toggled: Option<Instant>,
}
impl Default for BeamNg {
    fn default() -> Self {
        Self {
            redline: 7000.0,
            tc_lit: false,
            tc_toggled: None,
        }
    }
}

const DL_TC: u32 = 1 << 4;
const DL_ABS: u32 = 1 << 10;
const BLINK: Duration = Duration::from_millis(600);

impl Parser for BeamNg {
    fn parse(&mut self, b: &[u8], now: Instant) -> Option<Telemetry> {
        if !matches!(b.len(), 92 | 96) {
            return None;
        }
        let rpm = f32_at(b, 16);
        if !rpm.is_finite() || rpm <= 1.0 {
            return None;
        }
        // No maximum in OutGauge: follow the highest RPM seen, like moza-rev.
        self.redline = self.redline.max(rpm);
        let show = u32::from_le_bytes(b[44..48].try_into().unwrap());
        let tc_lit = show & DL_TC != 0;
        if tc_lit != self.tc_lit {
            self.tc_lit = tc_lit;
            self.tc_toggled = Some(now);
        }
        let throttle = f32_at(b, 48).clamp(0.0, 1.0);
        Some(Telemetry {
            // 0 reverse, 1 neutral, 2 first gear.
            gear: Some(i32::from(b[10]) - 1),
            speed: Some(f32_at(b, 12)).filter(|v| v.is_finite()),
            throttle: Some(throttle),
            brake: Some(f32_at(b, 52).clamp(0.0, 1.0)),
            clutch: Some(f32_at(b, 56).clamp(0.0, 1.0)),
            abs: Some(show & DL_ABS != 0),
            tc: Some(
                throttle > 0.05
                    && self
                        .tc_toggled
                        .is_some_and(|at| now.duration_since(at) < BLINK),
            ),
            ..Telemetry::engine(
                GameId::BeamNG.name(),
                EngineState {
                    rpm: rpm as i32,
                    rpm_redline: self.redline as i32,
                    rpm_idle: 800,
                },
            )
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn put(b: &mut [u8], offset: usize, value: f32) {
        b[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }

    fn ams2(rpm: u16, speed: f32, throttle: u8, brake: u8, flags: u8, rps: f32) -> Vec<u8> {
        let mut b = vec![0; 559];
        b[10] = 0; // telemetry packet type
        b[13] = throttle;
        b[14] = brake;
        b[16] = 40; // clutch
        b[17] = flags;
        put(&mut b, 36, speed);
        b[40..42].copy_from_slice(&rpm.to_le_bytes());
        b[42..44].copy_from_slice(&8000u16.to_le_bytes());
        b[45] = 0x63; // 6 gears, third
        for w in 0..4 {
            put(&mut b, 160 + w * 4, -rps);
            put(&mut b, 312 + w * 4, 0.05);
        }
        b
    }

    #[test]
    fn ams2_reads_inputs_gated_aids_and_learns_radius_before_slip() {
        let mut p = Ams2::default();
        let now = Instant::now();
        let t = p
            .parse(&ams2(6000, 30.0, 255, 0, CAR_ABS | CAR_TCS, 100.0), now)
            .unwrap();
        assert_eq!(
            (t.engine.rpm, t.engine.rpm_redline, t.gear),
            (6000, 8000, Some(3))
        );
        assert_eq!((t.throttle, t.brake), (Some(1.0), Some(0.0)));
        assert!((t.clutch.unwrap() - 40.0 / 255.0).abs() < 1e-6);
        // ABS needs the brake, TC the throttle.
        assert_eq!((t.abs, t.tc), (Some(false), Some(true)));
        assert!(t.slip.is_none(), "no radius learned yet");
        assert_eq!(t.suspension, Some([0.05; 4]));
        // Coasting at 30 m/s with wheels at 100 rad/s: radius 0.3 m.
        p.parse(&ams2(5000, 30.0, 0, 0, 0, 100.0), now);
        let t = p.parse(&ams2(6000, 30.0, 255, 0, 0, 120.0), now).unwrap();
        assert!((t.slip.unwrap()[2] - 0.2).abs() < 1e-4, "{:?}", t.slip);
        let t = p
            .parse(&ams2(3000, 30.0, 0, 200, CAR_ABS, 50.0), now)
            .unwrap();
        assert!((t.slip.unwrap()[0] + 0.5).abs() < 1e-4);
        assert_eq!(t.abs, Some(true));
        let mut reverse = ams2(2000, 2.0, 0, 0, 0, 5.0);
        reverse[45] = 0x6f;
        assert_eq!(p.parse(&reverse, now).unwrap().gear, Some(-1));
        // Menus report no maximum RPM.
        let mut menu = ams2(0, 0.0, 0, 0, 0, 0.0);
        menu[42..44].copy_from_slice(&0u16.to_le_bytes());
        assert!(p.parse(&menu, now).is_none());
    }

    fn forza(len: usize) -> Vec<u8> {
        let mut b = vec![0; len];
        b[0] = 1;
        put(&mut b, 8, 8000.0);
        put(&mut b, 12, 900.0);
        put(&mut b, 16, 5000.0);
        put(&mut b, 40, 20.0);
        for (w, slip) in [0.0f32, 0.0, 1.5, 1.5].iter().enumerate() {
            put(&mut b, 84 + w * 4, *slip);
            put(&mut b, 196 + w * 4, 0.04);
        }
        b
    }

    #[test]
    fn forza_layouts_are_told_apart_by_length() {
        let now = Instant::now();
        let sled = Forza.parse(&forza(232), now).unwrap();
        assert_eq!(
            (
                sled.engine.rpm,
                sled.engine.rpm_redline,
                sled.engine.rpm_idle
            ),
            (5000, 8000, 900)
        );
        assert_eq!(sled.speed, Some(20.0));
        assert!(sled.throttle.is_none() && sled.gear.is_none());
        assert!((sled.slip.unwrap()[3] - 0.3).abs() < 1e-6);
        assert_eq!(sled.suspension, Some([0.04; 4]));
        for (len, dash) in [(311, 232), (331, 232), (323, 244), (324, 244)] {
            let mut b = forza(len);
            put(&mut b, dash + 12, 33.0);
            b[dash + 71] = 255;
            b[dash + 72] = 0;
            b[dash + 73] = 51;
            b[dash + 75] = 4;
            let t = Forza.parse(&b, now).unwrap();
            assert_eq!(
                (t.speed, t.throttle, t.brake, t.gear),
                (Some(33.0), Some(1.0), Some(0.0), Some(4)),
                "{len}"
            );
            assert!((t.clutch.unwrap() - 0.2).abs() < 1e-6);
            b[dash + 75] = 0;
            assert_eq!(Forza.parse(&b, now).unwrap().gear, Some(-1));
        }
        assert!(Forza.parse(&forza(300), now).is_none());
        let mut paused = forza(311);
        paused[0] = 0;
        assert!(Forza.parse(&paused, now).is_none());
    }

    fn outgauge(rpm: f32, gear: u8, show: u32, throttle: f32) -> Vec<u8> {
        let mut b = vec![0; 96];
        b[10] = gear;
        put(&mut b, 12, 25.0);
        put(&mut b, 16, rpm);
        b[44..48].copy_from_slice(&show.to_le_bytes());
        put(&mut b, 48, throttle);
        put(&mut b, 52, 0.5);
        b
    }

    #[test]
    fn beamng_abs_is_direct_and_tc_must_blink() {
        let mut p = BeamNg::default();
        let now = Instant::now();
        let t = p.parse(&outgauge(3000.0, 4, DL_ABS, 0.0), now).unwrap();
        assert_eq!(
            (t.gear, t.abs, t.tc, t.speed),
            (Some(3), Some(true), Some(false), Some(25.0))
        );
        assert!(t.slip.is_none() && t.suspension.is_none());
        // A solid TC light (switched off) does not count once it has settled.
        p.parse(&outgauge(3000.0, 4, DL_TC, 0.8), now);
        let later = now + Duration::from_secs(1);
        assert_eq!(
            p.parse(&outgauge(3000.0, 4, DL_TC, 0.8), later).unwrap().tc,
            Some(false)
        );
        // Blinking while on the throttle does.
        assert_eq!(
            p.parse(&outgauge(3000.0, 4, 0, 0.8), later).unwrap().tc,
            Some(true)
        );
        assert_eq!(
            p.parse(&outgauge(3000.0, 4, 0, 0.0), later).unwrap().tc,
            Some(false)
        );
        assert_eq!(
            p.parse(&outgauge(3000.0, 0, 0, 0.0), later).unwrap().gear,
            Some(-1)
        );
        // The redline follows the highest RPM seen.
        assert_eq!(
            p.parse(&outgauge(7600.0, 4, 0, 1.0), later)
                .unwrap()
                .engine
                .rpm_redline,
            7600
        );
        assert!(p.parse(&outgauge(0.0, 1, 0, 0.0), later).is_none());
        assert!(p.parse(&[0; 64], later).is_none());
    }
}
