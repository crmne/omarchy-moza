//! One telemetry sample. Rev lights only need the engine; pedal haptics use
//! whatever else a game provides, and skip effects whose inputs are missing.
use moza_rev::listeners::EngineState;
use std::sync::{Arc, Mutex, PoisonError};

/// Wheels in front-left, front-right, rear-left, rear-right order.
pub type Wheels = [f32; 4];

#[derive(Clone, Copy, Debug)]
pub struct Telemetry {
    pub game: &'static str,
    pub engine: EngineState,
    /// -1 reverse, 0 neutral, 1 and up forward gears.
    pub gear: Option<i32>,
    /// Metres per second.
    pub speed: Option<f32>,
    /// Pedal travel, 0 released to 1 fully pressed.
    pub throttle: Option<f32>,
    pub brake: Option<f32>,
    pub clutch: Option<f32>,
    /// The car's own ABS or traction control is intervening right now.
    pub abs: Option<bool>,
    pub tc: Option<bool>,
    /// Longitudinal slip ratio: positive when spinning, negative when locking.
    pub slip: Option<Wheels>,
    /// Suspension travel in metres; only its movement matters.
    pub suspension: Option<Wheels>,
}

impl Telemetry {
    pub fn engine(game: &'static str, engine: EngineState) -> Self {
        Self {
            game,
            engine,
            gear: None,
            speed: None,
            throttle: None,
            brake: None,
            clutch: None,
            abs: None,
            tc: None,
            slip: None,
            suspension: None,
        }
    }
}

/// The newest sample from any listener. Listeners overwrite it and the
/// wheel loop takes it, so a sender that outruns the serial-paced loop only
/// replaces one value: retained telemetry never grows past one sample.
#[derive(Clone, Default)]
pub struct Latest(Arc<Mutex<Option<Telemetry>>>);

impl Latest {
    pub fn store(&self, telemetry: Telemetry) {
        *self.0.lock().unwrap_or_else(PoisonError::into_inner) = Some(telemetry);
    }

    pub fn take(&self) -> Option<Telemetry> {
        self.0.lock().unwrap_or_else(PoisonError::into_inner).take()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample(rpm: i32) -> Telemetry {
        Telemetry::engine(
            "test",
            EngineState {
                rpm,
                rpm_redline: 8000,
                rpm_idle: 800,
            },
        )
    }

    #[test]
    fn latest_keeps_only_the_newest_sample() {
        let latest = Latest::default();
        assert!(latest.take().is_none());
        let sender = latest.clone();
        // A flood far beyond what the wheel loop drains retains one sample.
        for rpm in 0..100_000 {
            sender.store(sample(rpm));
        }
        assert_eq!(latest.take().map(|t| t.engine.rpm), Some(99_999));
        assert!(latest.take().is_none(), "taking empties the slot");
    }

    #[test]
    fn latest_is_shared_by_concurrent_listeners() {
        let latest = Latest::default();
        let threads: Vec<_> = (0..4)
            .map(|n| {
                let tx = latest.clone();
                std::thread::spawn(move || {
                    for rpm in 0..10_000 {
                        tx.store(sample(n * 10_000 + rpm));
                    }
                })
            })
            .collect();
        for thread in threads {
            thread.join().unwrap();
        }
        let rpm = latest.take().unwrap().engine.rpm;
        assert_eq!(rpm % 10_000, 9_999, "a listener's last sample, {rpm}");
        assert!(latest.take().is_none());
    }
}
