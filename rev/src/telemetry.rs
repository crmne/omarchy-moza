//! One telemetry sample. Rev lights only need the engine; pedal haptics use
//! whatever else a game provides, and skip effects whose inputs are missing.
use moza_rev::listeners::{EngineState, Update};

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

impl From<Update> for Telemetry {
    fn from(update: Update) -> Self {
        Self::engine(update.game.name(), update.engine)
    }
}
