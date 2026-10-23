//! MOZA pedal haptic module (USB 346e:002f, Pit House's "Vibration module").
//!
//! The module stores no effects. Each pedal has nine oscillator slots that
//! the host keeps alive by resending `duration, frequency, strength` before
//! the duration runs out, and stops with an all-zero disable frame. Timings
//! and encodings follow Pit House 1.4.1.13's own traffic; see
//! docs/Pedal-haptics.md.
use crate::{telemetry::Telemetry, wire};
use serde::{Deserialize, Serialize};
use std::time::{Duration, Instant};

const GROUP: u8 = 0x4d;
const DEVICE: u8 = 0x12;
/// Stop effects quickly when a game stops sending, unlike the rev lights.
pub const STALE: Duration = Duration::from_millis(300);
pub const TEST: Duration = Duration::from_secs(3);
/// Frames per tick, so a burst cannot delay the wheel's serial work.
const BUDGET: usize = 12;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Pedal {
    Throttle = 1,
    Brake = 2,
    Clutch = 3,
}
pub const PEDALS: [Pedal; 3] = [Pedal::Throttle, Pedal::Brake, Pedal::Clutch];

/// Slot numbers are the module's own effect ids.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    Tc = 0,
    Abs = 1,
    Lockup = 2,
    BrakeThreshold = 3,
    Engine = 4,
    Bite = 5,
    GearShift = 6,
    WheelSpin = 7,
    Road = 8,
}
pub const KINDS: [Kind; 9] = [
    Kind::Tc,
    Kind::Abs,
    Kind::Lockup,
    Kind::BrakeThreshold,
    Kind::Engine,
    Kind::Bite,
    Kind::GearShift,
    Kind::WheelSpin,
    Kind::Road,
];

impl Kind {
    /// Pit House offers ABS, lockup and brake threshold on the brake only,
    /// and the bite point on the clutch only.
    pub fn available(self, pedal: Pedal) -> bool {
        match self {
            Kind::Abs | Kind::Lockup | Kind::BrakeThreshold => pedal == Pedal::Brake,
            Kind::Bite => pedal == Pedal::Clutch,
            _ => true,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct Effect {
    pub enabled: bool,
    /// Hz, 10–100. The engine effect reaches it at the end of its RPM range.
    pub frequency: u8,
    /// Percent of full strength.
    pub intensity: u8,
    /// Engine RPM range.
    pub start: u32,
    pub end: u32,
    /// Pedal travel percent for the brake threshold and bite point.
    pub trigger: u8,
    /// Width of the bite point zone, percent.
    pub smoothness: u8,
}
impl Default for Effect {
    fn default() -> Self {
        Self {
            enabled: false,
            frequency: 50,
            intensity: 50,
            start: 500,
            end: 10000,
            trigger: 70,
            smoothness: 50,
        }
    }
}
impl Effect {
    fn on(frequency: u8, intensity: u8) -> Self {
        Self {
            enabled: true,
            frequency,
            intensity,
            ..Default::default()
        }
    }
    fn off(frequency: u8) -> Self {
        Self {
            frequency,
            ..Default::default()
        }
    }
    fn validate(&self) -> bool {
        (10..=100).contains(&self.frequency)
            && self.intensity <= 100
            && self.start < self.end
            && self.end <= 30000
            && self.trigger <= 100
            && self.smoothness <= 100
    }
    fn strength(&self) -> u16 {
        (65535 * u32::from(self.intensity) / 100) as u16
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct PedalEffects {
    pub tc: Effect,
    pub abs: Effect,
    pub lockup: Effect,
    pub brake_threshold: Effect,
    pub engine: Effect,
    pub bite: Effect,
    pub gear_shift: Effect,
    pub wheel_spin: Effect,
    pub road: Effect,
}
impl Default for PedalEffects {
    fn default() -> Self {
        Self {
            tc: Effect::off(50),
            abs: Effect::off(30),
            lockup: Effect::off(50),
            brake_threshold: Effect {
                trigger: 75,
                ..Effect::off(50)
            },
            engine: Effect {
                frequency: 100,
                intensity: 10,
                ..Effect::on(100, 10)
            },
            bite: Effect::off(50),
            gear_shift: Effect::off(50),
            wheel_spin: Effect::off(40),
            road: Effect::off(50),
        }
    }
}
impl PedalEffects {
    pub fn get(&self, kind: Kind) -> &Effect {
        match kind {
            Kind::Tc => &self.tc,
            Kind::Abs => &self.abs,
            Kind::Lockup => &self.lockup,
            Kind::BrakeThreshold => &self.brake_threshold,
            Kind::Engine => &self.engine,
            Kind::Bite => &self.bite,
            Kind::GearShift => &self.gear_shift,
            Kind::WheelSpin => &self.wheel_spin,
            Kind::Road => &self.road,
        }
    }
}

/// Defaults are Pit House's "PHF-Official" preset.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct Config {
    pub enabled: bool,
    pub throttle: PedalEffects,
    pub brake: PedalEffects,
    pub clutch: PedalEffects,
}
impl Default for Config {
    fn default() -> Self {
        let base = PedalEffects::default();
        Self {
            enabled: true,
            throttle: PedalEffects {
                tc: Effect::on(50, 80),
                gear_shift: Effect::on(100, 80),
                ..base
            },
            brake: PedalEffects {
                abs: Effect::on(30, 100),
                gear_shift: Effect::on(100, 80),
                ..base
            },
            clutch: PedalEffects {
                bite: Effect::on(50, 50),
                ..base
            },
        }
    }
}
impl Config {
    pub fn pedal(&self, pedal: Pedal) -> &PedalEffects {
        match pedal {
            Pedal::Throttle => &self.throttle,
            Pedal::Brake => &self.brake,
            Pedal::Clutch => &self.clutch,
        }
    }
    pub fn validate(&self) -> bool {
        PEDALS.iter().all(|&pedal| {
            KINDS.iter().all(|&kind| {
                let effect = self.pedal(pedal).get(kind);
                effect.validate() && (kind.available(pedal) || !effect.enabled)
            })
        })
    }
}

/// One slot's command. `duration` is in milliseconds; for road texture the
/// frequency field carries a suspension position from 0 to 100.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Output {
    pub duration: u16,
    pub frequency: u16,
    pub strength: u16,
    /// Resend interval while the output stays the same.
    pub refresh: Duration,
}

pub fn set_frame(pedal: Pedal, kind: Kind, output: Option<Output>) -> Vec<u8> {
    let (enable, o) = match output {
        Some(o) => (1, o),
        None => (
            0,
            Output {
                duration: 0,
                frequency: 0,
                strength: 0,
                refresh: Duration::ZERO,
            },
        ),
    };
    let mut payload = vec![0x01, 0x01, pedal as u8, kind as u8, enable];
    for value in [o.duration, o.frequency, o.strength] {
        payload.extend_from_slice(&value.to_be_bytes());
    }
    wire::frame(GROUP, DEVICE, &payload)
}

/// Pit House's engine effect: one period per frame, rising with RPM.
fn engine_output(effect: &Effect, rpm: f32) -> Option<Output> {
    if rpm < effect.start as f32 {
        return None;
    }
    let t = ((rpm - effect.start as f32) / (effect.end - effect.start) as f32).clamp(0.0, 1.0);
    let frequency = (10.0 + t * f32::from(effect.frequency - 10)).round() as u16;
    Some(Output {
        duration: 1000 / frequency,
        frequency,
        strength: effect.strength(),
        refresh: Duration::from_millis(33),
    })
}

fn pulse(effect: &Effect, duration: u16, refresh: u64) -> Output {
    Output {
        duration,
        frequency: u16::from(effect.frequency),
        strength: effect.strength(),
        refresh: Duration::from_millis(refresh),
    }
}

fn road_output(effect: &Effect, position: f32) -> Output {
    Output {
        duration: 100,
        frequency: position.round().clamp(0.0, 100.0) as u16,
        strength: effect.strength(),
        refresh: Duration::from_millis(33),
    }
}

/// Suspension speed, in m/s, at which road texture reaches its deepest
/// position. Pit House's test dips from 100 to 37.
const ROAD_FULL: f32 = 0.5;
const SLIP: f32 = 0.15;
const LOCK: f32 = 0.2;
const SHIFT: Duration = Duration::from_millis(200);

#[derive(Default)]
pub struct Haptics {
    sent: [[Option<(Output, Instant)>; 9]; 3],
    gear: Option<i32>,
    shift: Option<Instant>,
    suspension: Option<([f32; 4], Instant)>,
    road: f32,
    test: Option<(Pedal, Kind, Instant)>,
}

impl Haptics {
    pub fn test(&mut self, pedal: Pedal, kind: Kind, now: Instant) {
        self.test = Some((pedal, kind, now));
    }
    pub fn testing(&self) -> Option<(Pedal, Kind)> {
        self.test.map(|(pedal, kind, _)| (pedal, kind))
    }
    /// Slots currently held on, for the panel.
    pub fn active(&self) -> Vec<(Pedal, Kind)> {
        let mut active = Vec::new();
        for pedal in PEDALS {
            for kind in KINDS {
                if self.sent[pedal as usize - 1][kind as usize].is_some() {
                    active.push((pedal, kind));
                }
            }
        }
        active
    }

    /// Forget what the module has, after a reconnect.
    pub fn reset(&mut self) {
        self.sent = Default::default();
    }

    /// Disable frames for every slot, sent on exit and on a fresh connection.
    pub fn stop_all(&mut self) -> Vec<Vec<u8>> {
        self.sent = Default::default();
        PEDALS
            .iter()
            .flat_map(|&pedal| KINDS.iter().map(move |&kind| set_frame(pedal, kind, None)))
            .collect()
    }

    fn observe(&mut self, telemetry: Option<&Telemetry>, now: Instant) {
        let Some(t) = telemetry else {
            self.gear = None;
            self.suspension = None;
            self.road = 0.0;
            return;
        };
        if let Some(gear) = t.gear {
            if self.gear.is_some_and(|previous| previous != gear) && gear != 0 {
                self.shift = Some(now);
            }
            self.gear = Some(gear);
        }
        if let Some(travel) = t.suspension {
            if let Some((previous, at)) = self.suspension {
                let dt = now.duration_since(at).as_secs_f32();
                if dt > 0.0 {
                    let speed = travel
                        .iter()
                        .zip(previous)
                        .map(|(a, b)| (a - b).abs())
                        .sum::<f32>()
                        / 4.0
                        / dt;
                    // Light smoothing so packet jitter does not read as bumps.
                    self.road += (speed.min(ROAD_FULL * 2.0) - self.road) * 0.5;
                }
            }
            self.suspension = Some((travel, now));
        }
    }

    fn target(&self, effect: &Effect, kind: Kind, t: &Telemetry, now: Instant) -> Option<Output> {
        let moving = t.speed.is_some_and(|speed| speed > 2.0);
        match kind {
            Kind::Engine => (t.engine.rpm > 0)
                .then(|| engine_output(effect, t.engine.rpm as f32))
                .flatten(),
            Kind::Abs => t.abs?.then(|| pulse(effect, 66, 45)),
            Kind::Tc => t.tc?.then(|| pulse(effect, 200, 105)),
            Kind::Lockup => {
                let locked = t.slip?.iter().fold(0.0f32, |worst, s| worst.max(-s));
                (moving && t.brake? > 0.05 && locked > LOCK).then(|| pulse(effect, 50, 33))
            }
            Kind::WheelSpin => {
                let spin = t.slip?.iter().fold(0.0f32, |worst, s| worst.max(*s));
                (t.throttle? > 0.05 && spin > SLIP).then(|| pulse(effect, 100, 50))
            }
            Kind::BrakeThreshold => {
                (t.brake? * 100.0 >= f32::from(effect.trigger)).then(|| pulse(effect, 50, 33))
            }
            Kind::Bite => {
                // The zone is centred on the trigger; smoothness sets its
                // width, up to 20% of pedal travel either side.
                let width = (f32::from(effect.smoothness) * 0.2).max(1.0);
                let distance = (t.clutch? * 100.0 - f32::from(effect.trigger)).abs();
                (distance <= width).then(|| pulse(effect, 200, 33))
            }
            Kind::GearShift => self
                .shift
                .filter(|at| now.duration_since(*at) < SHIFT)
                .map(|_| pulse(effect, SHIFT.as_millis() as u16, 250)),
            Kind::Road => (moving && t.suspension.is_some())
                .then(|| road_output(effect, 100.0 - 63.0 * (self.road / ROAD_FULL).min(1.0))),
        }
    }

    /// Previews an effect with its current settings, like Pit House's Test.
    fn test_output(effect: &Effect, kind: Kind, elapsed: Duration) -> Option<Output> {
        let phase = elapsed.as_secs_f32() / TEST.as_secs_f32();
        // Out and back once, as Pit House sweeps RPM and road position.
        let wave = 1.0 - (phase * 2.0 - 1.0).abs();
        match kind {
            Kind::Engine => engine_output(
                effect,
                effect.start as f32 + wave * (effect.end - effect.start) as f32,
            ),
            Kind::Road => Some(road_output(effect, 100.0 - 63.0 * wave)),
            Kind::GearShift => (elapsed.as_millis() % 750 < SHIFT.as_millis())
                .then(|| pulse(effect, SHIFT.as_millis() as u16, 250)),
            Kind::Abs => Some(pulse(effect, 66, 45)),
            Kind::Tc => Some(pulse(effect, 200, 105)),
            Kind::WheelSpin => Some(pulse(effect, 100, 50)),
            Kind::Bite => Some(pulse(effect, 200, 33)),
            Kind::Lockup | Kind::BrakeThreshold => Some(pulse(effect, 50, 33)),
        }
    }

    /// Frames to write now. `telemetry` is None when no game is live.
    pub fn tick(
        &mut self,
        config: &Config,
        telemetry: Option<&Telemetry>,
        now: Instant,
    ) -> Vec<Vec<u8>> {
        self.observe(telemetry, now);
        if self
            .test
            .is_some_and(|(_, _, started)| now.duration_since(started) >= TEST)
        {
            self.test = None;
        }
        let mut stops = Vec::new();
        let mut updates = Vec::new();
        for pedal in PEDALS {
            for kind in KINDS {
                let effect = config.pedal(pedal).get(kind);
                let want = match self.test {
                    Some((p, k, started)) if p == pedal && k == kind => {
                        Self::test_output(effect, kind, now.duration_since(started))
                    }
                    // A test plays alone so it can be told apart.
                    Some(_) => None,
                    None if config.enabled && effect.enabled && kind.available(pedal) => {
                        telemetry.and_then(|t| self.target(effect, kind, t, now))
                    }
                    None => None,
                };
                let sent = self.sent[pedal as usize - 1][kind as usize];
                match (want, sent) {
                    (None, Some(_)) => stops.push((pedal, kind, None)),
                    (Some(o), Some((previous, at)))
                        if o == previous && now.duration_since(at) < o.refresh => {}
                    (Some(o), _) => updates.push((pedal, kind, Some(o))),
                    (None, None) => {}
                }
            }
        }
        // A missed stop leaves a motor running, so stops always go first.
        // The oldest updates follow, so every slot gets its turn.
        updates.sort_by_key(|(pedal, kind, _)| {
            self.sent[*pedal as usize - 1][*kind as usize].map(|(_, at)| at)
        });
        let budget = BUDGET.saturating_sub(stops.len());
        stops
            .into_iter()
            .chain(updates.into_iter().take(budget))
            .map(|(pedal, kind, output)| {
                self.sent[pedal as usize - 1][kind as usize] = output.map(|o| (o, now));
                set_frame(pedal, kind, output)
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use moza_rev::listeners::EngineState;

    fn car() -> Telemetry {
        Telemetry {
            gear: Some(3),
            speed: Some(30.0),
            throttle: Some(0.0),
            brake: Some(0.0),
            clutch: Some(0.0),
            abs: Some(false),
            tc: Some(false),
            slip: Some([0.0; 4]),
            suspension: Some([0.1; 4]),
            ..Telemetry::engine(
                "Test",
                EngineState {
                    rpm: 0,
                    rpm_redline: 8000,
                    rpm_idle: 900,
                },
            )
        }
    }
    fn decode(frame: &[u8]) -> (u8, u8, u8, u16, u16, u16) {
        let p = &frame[4..15];
        let word = |i: usize| u16::from_be_bytes([p[i], p[i + 1]]);
        (p[2], p[3], p[4], word(5), word(7), word(9))
    }

    #[test]
    fn frames_match_pit_house_bytes() {
        // Captured from Pit House: brake ABS test at 30 Hz, 100%.
        let abs = Effect::on(30, 100);
        assert_eq!(
            set_frame(Pedal::Brake, Kind::Abs, Some(pulse(&abs, 66, 45))),
            [
                0x7e, 0x0b, 0x4d, 0x12, 1, 1, 2, 1, 1, 0, 66, 0, 30, 0xff, 0xff, 0x59
            ]
        );
        // Engine at 10% (6553) and the matching disable.
        let engine = Effect::on(100, 10);
        assert_eq!(
            set_frame(Pedal::Clutch, Kind::Engine, engine_output(&engine, 500.0)),
            [
                0x7e, 0x0b, 0x4d, 0x12, 1, 1, 3, 4, 1, 0, 100, 0, 10, 0x19, 0x99, 0x1f
            ]
        );
        assert_eq!(
            set_frame(Pedal::Clutch, Kind::Engine, None),
            [
                0x7e, 0x0b, 0x4d, 0x12, 1, 1, 3, 4, 0, 0, 0, 0, 0, 0, 0, 0xfe
            ]
        );
    }

    #[test]
    fn intensity_matches_pit_house_strengths() {
        for (percent, strength) in [(10, 6553), (50, 32767), (80, 52428), (100, 65535)] {
            assert_eq!(Effect::on(50, percent).strength(), strength);
        }
    }

    #[test]
    fn engine_frequency_follows_rpm_with_one_period_duration() {
        let e = Effect::on(100, 10);
        assert_eq!(engine_output(&e, 499.0), None);
        let low = engine_output(&e, 500.0).unwrap();
        assert_eq!((low.frequency, low.duration), (10, 100));
        let mid = engine_output(&e, 5250.0).unwrap();
        assert_eq!((mid.frequency, mid.duration), (55, 18));
        let top = engine_output(&e, 20000.0).unwrap();
        assert_eq!((top.frequency, top.duration), (100, 10));
        let capped = engine_output(&Effect::on(60, 10), 10000.0).unwrap();
        assert_eq!(capped.frequency, 60);
    }

    #[test]
    fn defaults_are_the_official_preset_and_valid() {
        let c = Config::default();
        assert!(c.validate());
        let on = |p: Pedal| -> Vec<Kind> {
            KINDS
                .into_iter()
                .filter(|k| c.pedal(p).get(*k).enabled)
                .collect()
        };
        assert_eq!(on(Pedal::Clutch), [Kind::Engine, Kind::Bite]);
        assert_eq!(on(Pedal::Brake), [Kind::Abs, Kind::Engine, Kind::GearShift]);
        assert_eq!(
            on(Pedal::Throttle),
            [Kind::Tc, Kind::Engine, Kind::GearShift]
        );
        assert_eq!(c.brake.abs.frequency, 30);
        assert_eq!(c.brake.brake_threshold.trigger, 75);
        assert_eq!(c.clutch.bite.trigger, 70);
    }

    #[test]
    fn demo_defaults_file_matches() {
        let file: serde_json::Value =
            serde_json::from_str(include_str!("../../backend/haptics-defaults.json")).unwrap();
        assert_eq!(file, serde_json::to_value(Config::default()).unwrap());
    }

    #[test]
    fn rejects_out_of_range_or_unavailable_effects() {
        let mut c = Config::default();
        c.throttle.abs.enabled = true;
        assert!(!c.validate());
        for bad in [
            Effect {
                frequency: 9,
                ..Effect::default()
            },
            Effect {
                frequency: 101,
                ..Effect::default()
            },
            Effect {
                intensity: 101,
                ..Effect::default()
            },
            Effect {
                start: 10000,
                end: 10000,
                ..Effect::default()
            },
            Effect {
                trigger: 101,
                ..Effect::default()
            },
        ] {
            let c = Config {
                brake: PedalEffects {
                    tc: bad,
                    ..PedalEffects::default()
                },
                ..Config::default()
            };
            assert!(!c.validate(), "{bad:?}");
        }
        let partial: Config =
            serde_json::from_str(r#"{"brake":{"abs":{"enabled":false}}}"#).unwrap();
        assert!(!partial.brake.abs.enabled);
        assert_eq!(partial.brake.abs.frequency, 50);
        assert!(serde_json::from_str::<Config>(r#"{"brake":{"nitro":{}}}"#).is_err());
    }

    #[test]
    fn abs_streams_while_active_then_stops_once() {
        let config = Config::default();
        let mut h = Haptics::default();
        let now = Instant::now();
        let mut t = car();
        t.abs = Some(true);
        let frames = h.tick(&config, Some(&t), now);
        assert_eq!(frames.len(), 1);
        assert_eq!(decode(&frames[0]), (2, 1, 1, 66, 30, 65535));
        // Held, not resent, until its refresh interval.
        assert!(
            h.tick(&config, Some(&t), now + Duration::from_millis(44))
                .is_empty()
        );
        assert_eq!(
            h.tick(&config, Some(&t), now + Duration::from_millis(45))
                .len(),
            1
        );
        t.abs = Some(false);
        let frames = h.tick(&config, Some(&t), now + Duration::from_millis(50));
        assert_eq!(frames.len(), 1);
        assert_eq!(decode(&frames[0]), (2, 1, 0, 0, 0, 0));
        assert!(
            h.tick(&config, Some(&t), now + Duration::from_millis(60))
                .is_empty()
        );
    }

    #[test]
    fn engine_runs_on_every_pedal_and_stops_when_telemetry_ends() {
        let config = Config::default();
        let mut h = Haptics::default();
        let now = Instant::now();
        let mut t = car();
        t.engine.rpm = 5250;
        let frames = h.tick(&config, Some(&t), now);
        let mut slots: Vec<_> = frames.iter().map(|f| decode(f)).collect();
        slots.sort();
        assert_eq!(
            slots,
            [
                (1, 4, 1, 18, 55, 6553),
                (2, 4, 1, 18, 55, 6553),
                (3, 4, 1, 18, 55, 6553)
            ]
        );
        let stops = h.tick(&config, None, now + Duration::from_millis(10));
        assert_eq!(stops.len(), 3);
        assert!(stops.iter().all(|f| decode(f).2 == 0));
        assert!(h.active().is_empty());
    }

    #[test]
    fn gear_changes_kick_once_but_neutral_does_not() {
        let config = Config::default();
        let mut h = Haptics::default();
        let now = Instant::now();
        let mut t = car();
        assert!(h.tick(&config, Some(&t), now).is_empty());
        t.gear = Some(4);
        let kicks = h.tick(&config, Some(&t), now + Duration::from_millis(10));
        let mut slots: Vec<_> = kicks.iter().map(|f| decode(f)).collect();
        slots.sort();
        assert_eq!(
            slots,
            [(1, 6, 1, 200, 100, 52428), (2, 6, 1, 200, 100, 52428)]
        );
        // One frame covers the kick; then the slots are released.
        assert!(
            h.tick(&config, Some(&t), now + Duration::from_millis(100))
                .is_empty()
        );
        assert_eq!(
            h.tick(&config, Some(&t), now + Duration::from_millis(220))
                .len(),
            2
        );
        t.gear = Some(0);
        assert!(
            h.tick(&config, Some(&t), now + Duration::from_millis(300))
                .is_empty()
        );
    }

    #[test]
    fn inputs_drive_brake_threshold_and_bite_point() {
        let mut config = Config::default();
        config.brake.brake_threshold.enabled = true;
        config.brake.abs.enabled = false;
        config.clutch.engine.enabled = false;
        let mut h = Haptics::default();
        let now = Instant::now();
        let mut t = car();
        t.brake = Some(0.74);
        t.clutch = Some(0.5);
        assert!(h.tick(&config, Some(&t), now).is_empty());
        t.brake = Some(0.75);
        t.clutch = Some(0.69);
        let mut slots: Vec<_> = h
            .tick(&config, Some(&t), now + Duration::from_millis(1))
            .iter()
            .map(|f| decode(f))
            .collect();
        slots.sort();
        assert_eq!(slots, [(2, 3, 1, 50, 50, 32767), (3, 5, 1, 200, 50, 32767)]);
    }

    #[test]
    fn slip_drives_wheel_spin_and_lockup_only_with_the_matching_pedal() {
        let mut config = Config::default();
        config.throttle.wheel_spin.enabled = true;
        config.brake.lockup.enabled = true;
        let mut h = Haptics::default();
        let now = Instant::now();
        let mut t = car();
        t.slip = Some([0.0, 0.0, 0.5, 0.5]);
        assert!(h.tick(&config, Some(&t), now).is_empty());
        t.throttle = Some(0.8);
        let frames = h.tick(&config, Some(&t), now + Duration::from_millis(1));
        assert_eq!(
            frames.iter().map(|f| decode(f)).collect::<Vec<_>>(),
            [(1, 7, 1, 100, 40, 32767)]
        );
        t.throttle = Some(0.0);
        t.brake = Some(0.6);
        t.slip = Some([-0.5, 0.0, 0.0, 0.0]);
        let mut slots: Vec<_> = h
            .tick(&config, Some(&t), now + Duration::from_millis(2))
            .iter()
            .map(|f| decode(f))
            .collect();
        slots.sort();
        assert_eq!(slots, [(1, 7, 0, 0, 0, 0), (2, 2, 1, 50, 50, 32767)]);
    }

    #[test]
    fn missing_inputs_leave_effects_off() {
        let mut config = Config::default();
        for p in [&mut config.throttle, &mut config.brake] {
            p.wheel_spin.enabled = true;
            p.road.enabled = true;
        }
        let mut h = Haptics::default();
        let mut t = Telemetry::engine("Engine only", car().engine);
        t.engine.rpm = 0;
        assert!(h.tick(&config, Some(&t), Instant::now()).is_empty());
    }

    #[test]
    fn road_texture_follows_suspension_movement() {
        let mut config = Config::default();
        config.brake.road.enabled = true;
        config.brake.abs.enabled = false;
        let mut h = Haptics::default();
        let now = Instant::now();
        let mut t = car();
        let first = h.tick(&config, Some(&t), now);
        assert_eq!(decode(&first[0]), (2, 8, 1, 100, 100, 32767));
        t.suspension = Some([0.12; 4]);
        let bump = h.tick(&config, Some(&t), now + Duration::from_millis(40));
        assert!(decode(&bump[0]).4 < 100, "{:?}", decode(&bump[0]));
    }

    #[test]
    fn tests_play_alone_with_current_settings_then_end() {
        let config = Config::default();
        let mut h = Haptics::default();
        let now = Instant::now();
        let mut t = car();
        t.engine.rpm = 3000;
        h.tick(&config, Some(&t), now);
        h.test(Pedal::Clutch, Kind::Bite, now);
        let frames = h.tick(&config, Some(&t), now + Duration::from_millis(1));
        let mut slots: Vec<_> = frames.iter().map(|f| decode(f)).collect();
        slots.sort();
        assert_eq!(
            slots,
            [
                (1, 4, 0, 0, 0, 0),
                (2, 4, 0, 0, 0, 0),
                (3, 4, 0, 0, 0, 0),
                (3, 5, 1, 200, 50, 32767)
            ]
        );
        let after = h.tick(&config, Some(&t), now + TEST);
        assert!(h.testing().is_none());
        assert!(after.iter().any(|f| decode(f) == (3, 5, 0, 0, 0, 0)));
    }

    #[test]
    fn disabled_config_and_budget_put_stops_first() {
        let mut config = Config::default();
        let mut h = Haptics::default();
        let now = Instant::now();
        let mut t = car();
        t.engine.rpm = 3000;
        t.abs = Some(true);
        assert_eq!(h.tick(&config, Some(&t), now).len(), 4);
        config.enabled = false;
        let stops = h.tick(&config, Some(&t), now + Duration::from_millis(1));
        assert_eq!(stops.len(), 4);
        assert!(stops.iter().all(|f| decode(f).2 == 0));
        assert_eq!(h.stop_all().len(), 27);
    }
}
