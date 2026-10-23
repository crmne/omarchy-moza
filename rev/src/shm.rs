//! Assetto Corsa Competizione and Le Mans Ultimate, read from the shared
//! memory that `shm-bridge/omarchy-moza-shm.exe` forwards from the game's
//! Proton prefix. Offsets follow Kunos' ACC Shared Memory 1.8.12 document
//! and LMU's own `SharedMemoryInterface` headers (x64), recomputed here and
//! checked by the tests below; see docs/Pedal-haptics.md.
use crate::{
    games::Parser,
    telemetry::{Telemetry, Wheels},
};
use moza_rev::listeners::EngineState;
use std::time::Instant;

pub const PORT: u16 = 9998;
const ACC: u8 = 1;
const LMU: u8 = 2;
const ACC_LIVE: i32 = 2;
const LMU_ON_TRACK: u8 = 3;
const LMU_PAUSED: u8 = 9;

fn at<const N: usize>(b: &[u8], offset: usize) -> [u8; N] {
    b[offset..offset + N].try_into().unwrap()
}
fn i32_at(b: &[u8], offset: usize) -> i32 {
    i32::from_le_bytes(at(b, offset))
}
fn f32_at(b: &[u8], offset: usize) -> f32 {
    f32::from_le_bytes(at(b, offset))
}
fn f64_at(b: &[u8], offset: usize) -> f32 {
    f64::from_le_bytes(at(b, offset)) as f32
}
fn unit(value: f32) -> Option<f32> {
    value.is_finite().then(|| value.clamp(0.0, 1.0))
}
fn finite(w: Wheels) -> Option<Wheels> {
    w.iter().all(|v| v.is_finite()).then_some(w)
}

/// Drops frames the game did not advance, so effects stop when it pauses.
#[derive(Default)]
pub struct Shm {
    acc_packet: Option<i32>,
    lmu_time: Option<f32>,
}

impl Shm {
    fn acc(&mut self, b: &[u8]) -> Option<Telemetry> {
        if b.len() != 8 + 12 + 800 {
            return None;
        }
        let (status, max_rpm, p) = (i32_at(b, 12), i32_at(b, 16), &b[20..]);
        let packet = i32_at(p, 0);
        let fresh = self.acc_packet.replace(packet) != Some(packet);
        if status != ACC_LIVE || !fresh || max_rpm <= 0 {
            return None;
        }
        let wheels = |offset: usize| finite([0, 1, 2, 3].map(|w: usize| f32_at(p, offset + w * 4)));
        Some(Telemetry {
            // 0 reverse, 1 neutral, 2 first gear.
            gear: Some(i32_at(p, 16) - 1),
            speed: Some(f32_at(p, 28) / 3.6).filter(|v| v.is_finite()),
            throttle: unit(f32_at(p, 4)),
            brake: unit(f32_at(p, 8)),
            clutch: unit(f32_at(p, 364)),
            // ACC reports how much each aid is acting, not its setting.
            tc: Some(f32_at(p, 204) > 0.0),
            abs: Some(f32_at(p, 252) > 0.0),
            slip: wheels(640),
            suspension: wheels(184),
            ..Telemetry::engine(
                "Assetto Corsa Competizione",
                EngineState {
                    rpm: i32_at(p, 20).max(0),
                    rpm_redline: max_rpm,
                    rpm_idle: 800,
                },
            )
        })
    }

    fn lmu(&mut self, b: &[u8]) -> Option<Telemetry> {
        if b.len() != 8 + 17 + 1888 {
            return None;
        }
        let (on_track, phase, realtime, r) = (b[8], b[13], b[20], &b[25..]);
        let time = f64_at(r, 12);
        let fresh = self.lmu_time.replace(time) != Some(time);
        let redline = f64_at(r, 532);
        if on_track != LMU_ON_TRACK
            || phase == LMU_PAUSED
            || realtime == 0
            || !fresh
            || !redline.is_finite()
            || redline <= 0.0
        {
            return None;
        }
        let velocity = [184, 192, 200].map(|o| f64_at(r, o));
        let speed = velocity.iter().map(|v| v * v).sum::<f32>().sqrt();
        let wheel = |w: usize| &r[848 + w * 260..848 + (w + 1) * 260];
        let slip = [0, 1, 2, 3].map(|w| {
            let radius = f32::from(wheel(w)[179]) / 100.0;
            let ground = f64_at(wheel(w), 72).abs();
            (f64_at(wheel(w), 40).abs() * radius - ground) / ground.max(1.0)
        });
        let radii_known = (0..4).all(|w| wheel(w)[179] > 0);
        Some(Telemetry {
            gear: Some(i32_at(r, 352)),
            speed: Some(speed).filter(|v| v.is_finite()),
            throttle: unit(f64_at(r, 388)),
            brake: unit(f64_at(r, 396)),
            clutch: unit(f64_at(r, 412)),
            abs: Some(r[746] != 0),
            tc: Some(r[747] != 0),
            slip: finite(slip).filter(|_| radii_known),
            suspension: finite([0, 1, 2, 3].map(|w| f64_at(wheel(w), 0))),
            ..Telemetry::engine(
                "Le Mans Ultimate",
                EngineState {
                    rpm: f64_at(r, 356).max(0.0) as i32,
                    rpm_redline: redline as i32,
                    rpm_idle: 800,
                },
            )
        })
    }
}

impl Parser for Shm {
    fn parse(&mut self, b: &[u8], _: Instant) -> Option<Telemetry> {
        if b.len() < 8 || &b[..4] != b"OMZ1" {
            return None;
        }
        match b[4] {
            ACC => self.acc(b),
            LMU => self.lmu(b),
            _ => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn put<const N: usize>(b: &mut [u8], offset: usize, value: [u8; N]) {
        b[offset..offset + N].copy_from_slice(&value);
    }

    fn acc(packet: i32, status: i32) -> Vec<u8> {
        let mut b = vec![0; 820];
        b[..5].copy_from_slice(b"OMZ1\x01");
        put(&mut b, 12, status.to_le_bytes());
        put(&mut b, 16, 8500i32.to_le_bytes());
        let p = 20;
        put(&mut b, p, packet.to_le_bytes());
        put(&mut b, p + 4, 0.75f32.to_le_bytes());
        put(&mut b, p + 8, 0.25f32.to_le_bytes());
        put(&mut b, p + 16, 4i32.to_le_bytes());
        put(&mut b, p + 20, 7100i32.to_le_bytes());
        put(&mut b, p + 28, 180.0f32.to_le_bytes());
        put(&mut b, p + 204, 0.4f32.to_le_bytes());
        put(&mut b, p + 364, 0.1f32.to_le_bytes());
        for w in 0..4 {
            put(&mut b, p + 184 + w * 4, 0.03f32.to_le_bytes());
            put(&mut b, p + 640 + w * 4, (w as f32 * 0.1).to_le_bytes());
        }
        b
    }

    #[test]
    fn acc_physics_page_needs_live_status_and_fresh_packets() {
        let mut s = Shm::default();
        let now = Instant::now();
        let t = s.parse(&acc(1, ACC_LIVE), now).unwrap();
        assert_eq!(t.game, "Assetto Corsa Competizione");
        assert_eq!(
            (t.engine.rpm, t.engine.rpm_redline, t.gear),
            (7100, 8500, Some(3))
        );
        assert_eq!(
            (t.throttle, t.brake, t.clutch),
            (Some(0.75), Some(0.25), Some(0.1))
        );
        assert!((t.speed.unwrap() - 50.0).abs() < 1e-4);
        assert_eq!((t.tc, t.abs), (Some(true), Some(false)));
        assert_eq!(t.slip, Some([0.0, 0.1, 0.2, 0.3]));
        assert_eq!(t.suspension, Some([0.03; 4]));
        // A repeated packet means the game paused or closed.
        assert!(s.parse(&acc(1, ACC_LIVE), now).is_none());
        assert!(s.parse(&acc(2, 3), now).is_none());
        assert!(s.parse(&acc(3, ACC_LIVE), now).is_some());
        assert!(s.parse(&acc(4, ACC_LIVE)[..819], now).is_none());
    }

    fn lmu(time: f64) -> Vec<u8> {
        let mut b = vec![0; 8 + 17 + 1888];
        b[..5].copy_from_slice(b"OMZ1\x02");
        b[8] = LMU_ON_TRACK;
        b[13] = 5; // green flag
        b[20] = 1; // realtime
        let r = 25;
        put(&mut b, r + 12, time.to_le_bytes());
        put(&mut b, r + 200, (-40.0f64).to_le_bytes());
        put(&mut b, r + 352, 5i32.to_le_bytes());
        put(&mut b, r + 356, 8200.0f64.to_le_bytes());
        put(&mut b, r + 388, 1.0f64.to_le_bytes());
        put(&mut b, r + 396, 0.0f64.to_le_bytes());
        put(&mut b, r + 412, 0.0f64.to_le_bytes());
        put(&mut b, r + 532, 9000.0f64.to_le_bytes());
        b[r + 747] = 1;
        for w in 0..4 {
            let wheel = r + 848 + w * 260;
            put(&mut b, wheel, 0.02f64.to_le_bytes());
            // 33 cm radius: 40 m/s is 121.2 rad/s; the rears spin 10% faster.
            let omega: f64 = if w < 2 { 40.0 / 0.33 } else { 44.0 / 0.33 };
            put(&mut b, wheel + 40, (-omega).to_le_bytes());
            put(&mut b, wheel + 72, 40.0f64.to_le_bytes());
            b[wheel + 179] = 33;
        }
        b
    }

    #[test]
    fn lmu_player_record_reports_aids_slip_and_pauses() {
        let mut s = Shm::default();
        let now = Instant::now();
        let t = s.parse(&lmu(10.0), now).unwrap();
        assert_eq!(t.game, "Le Mans Ultimate");
        assert_eq!(
            (t.engine.rpm, t.engine.rpm_redline, t.gear),
            (8200, 9000, Some(5))
        );
        assert_eq!(
            (t.speed, t.throttle, t.abs, t.tc),
            (Some(40.0), Some(1.0), Some(false), Some(true))
        );
        let slip = t.slip.unwrap();
        assert!(
            slip[0].abs() < 1e-3 && (slip[3] - 0.1).abs() < 1e-3,
            "{slip:?}"
        );
        assert_eq!(t.suspension, Some([0.02; 4]));
        // The clock must advance, and the car must be on track, live and unpaused.
        assert!(s.parse(&lmu(10.0), now).is_none());
        for (offset, value) in [(8, 1), (13, LMU_PAUSED), (20, 0)] {
            let mut b = lmu(11.0 + offset as f64);
            b[offset] = value;
            assert!(s.parse(&b, now).is_none(), "{offset}");
        }
        let mut unknown_radius = lmu(30.0);
        unknown_radius[25 + 848 + 179] = 0;
        assert!(s.parse(&unknown_radius, now).unwrap().slip.is_none());
        assert!(s.parse(b"OMZ1\x03\0\0\0", now).is_none());
    }
}
