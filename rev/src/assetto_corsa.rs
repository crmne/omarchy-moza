//! Exact AC telemetry from the companion CSP app, never an observed RPM peak.
//! Version 2 adds what pedal haptics need; version 1 carries the engine only.
use crate::telemetry::{Latest, Telemetry, Wheels};
use moza_rev::listeners::{EngineState, GameId};
use serde::Deserialize;
use std::{io, net::UdpSocket, thread};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Packet {
    protocol: String,
    rpm: i32,
    redline: i32,
    idle: i32,
    gear: Option<i32>,
    speed: Option<f32>,
    throttle: Option<f32>,
    brake: Option<f32>,
    clutch: Option<f32>,
    abs: Option<bool>,
    tc: Option<bool>,
    slip: Option<Wheels>,
    suspension: Option<Wheels>,
}

fn unit(value: Option<f32>) -> Option<f32> {
    value.filter(|v| v.is_finite()).map(|v| v.clamp(0.0, 1.0))
}

fn finite(wheels: Option<Wheels>) -> Option<Wheels> {
    wheels.filter(|w| w.iter().all(|v| v.is_finite()))
}

fn parse(bytes: &[u8]) -> Option<Telemetry> {
    let p: Packet = serde_json::from_slice(bytes).ok()?;
    if !matches!(
        p.protocol.as_str(),
        "omarchy-moza-ac/1" | "omarchy-moza-ac/2"
    ) || p.rpm < 0
        || p.idle < 0
        || p.redline <= p.idle
    {
        return None;
    }
    Some(Telemetry {
        gear: p.gear,
        speed: p.speed.filter(|v| v.is_finite()),
        throttle: unit(p.throttle),
        brake: unit(p.brake),
        clutch: unit(p.clutch),
        abs: p.abs,
        tc: p.tc,
        slip: finite(p.slip),
        suspension: finite(p.suspension),
        ..Telemetry::engine(
            GameId::AssettoCorsa.name(),
            EngineState {
                rpm: p.rpm,
                rpm_redline: p.redline,
                rpm_idle: p.idle,
            },
        )
    })
}

pub fn spawn(port: u16, latest: Latest) -> bool {
    let Ok(socket) = UdpSocket::bind(("127.0.0.1", port)) else {
        return false;
    };
    thread::Builder::new()
        .name("assetto-corsa-csp".into())
        .spawn(move || {
            let mut buffer = [0; 1024];
            loop {
                let n = match socket.recv(&mut buffer) {
                    Ok(n) => n,
                    Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                    Err(_) => break,
                };
                if let Some(telemetry) = parse(&buffer[..n]) {
                    latest.store(telemetry);
                }
            }
        })
        .is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn packet(rpm: i32, redline: i32, idle: i32) -> Vec<u8> {
        format!(
            r#"{{"protocol":"omarchy-moza-ac/1","rpm":{rpm},"redline":{redline},"idle":{idle}}}"#
        )
        .into_bytes()
    }

    #[test]
    fn limit_is_reported_not_learned_and_can_decrease_between_cars() {
        for (rpm, redline, idle) in [(8500, 9000, 1200), (6300, 6500, 1250), (450, 500, 100)] {
            let engine = parse(&packet(rpm, redline, idle)).unwrap().engine;
            assert_eq!(engine.rpm_redline, redline);
            assert_eq!(engine.rpm, rpm);
            assert_eq!(engine.rpm_idle, idle);
        }
        // Over-revving on a downshift must not move the reported limit.
        assert_eq!(
            parse(&packet(7200, 6500, 1250)).unwrap().engine.rpm_redline,
            6500
        );
        assert_eq!(parse(&packet(0, 500, 100)).unwrap().engine.rpm, 0);
    }

    #[test]
    fn invalid_or_unrelated_packets_are_ignored() {
        for values in [
            (-1, 6500, 100),
            (100, 0, 0),
            (100, 500, -1),
            (100, 500, 500),
        ] {
            assert!(parse(&packet(values.0, values.1, values.2)).is_none());
        }
        for bytes in [
            b"{}".as_slice(),
            b"garbage",
            br#"{"protocol":"other","rpm":100,"redline":500,"idle":0}"#,
            br#"{"protocol":"omarchy-moza-ac/1","rpm":1.5,"redline":500,"idle":0}"#,
        ] {
            assert!(parse(bytes).is_none());
        }
    }

    #[test]
    fn a_flood_of_packets_retains_only_the_newest() {
        let port = UdpSocket::bind(("127.0.0.1", 0))
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        let latest = Latest::default();
        assert!(spawn(port, latest.clone()));
        let sender = UdpSocket::bind(("127.0.0.1", 0)).unwrap();
        // Nothing takes from the slot while the flood arrives.
        for rpm in 1..=20_000 {
            let _ = sender.send_to(&packet(rpm, 30_000, 100), ("127.0.0.1", port));
        }
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        loop {
            // A full socket buffer may drop packets, so repeat the final one.
            // The slot holds one sample however many packets arrived, so it
            // eventually holds exactly the final packet.
            let _ = sender.send_to(&packet(29_999, 30_000, 100), ("127.0.0.1", port));
            thread::sleep(std::time::Duration::from_millis(5));
            if latest.take().map(|t| t.engine.rpm) == Some(29_999) {
                break;
            }
            assert!(std::time::Instant::now() < deadline, "final packet lost");
        }
        // Only a repeat of the final packet can still arrive.
        thread::sleep(std::time::Duration::from_millis(20));
        assert!(latest.take().is_none_or(|t| t.engine.rpm == 29_999));
    }

    #[test]
    fn version_two_carries_haptic_inputs() {
        let t = parse(
            br#"{"protocol":"omarchy-moza-ac/2","rpm":7000,"redline":8000,"idle":900,
                "gear":3,"speed":41.5,"throttle":0.25,"brake":1.4,"clutch":0,
                "abs":true,"tc":false,"slip":[0.01,0.02,-0.4,0.3],"suspension":[0.05,0.05,0.06,0.06]}"#,
        )
        .unwrap();
        assert_eq!(t.gear, Some(3));
        assert_eq!(t.speed, Some(41.5));
        assert_eq!(
            (t.throttle, t.brake, t.clutch),
            (Some(0.25), Some(1.0), Some(0.0))
        );
        assert_eq!((t.abs, t.tc), (Some(true), Some(false)));
        assert_eq!(t.slip, Some([0.01, 0.02, -0.4, 0.3]));
        // Version 1 leaves every haptic input unknown.
        let v1 = parse(&packet(7000, 8000, 900)).unwrap();
        assert!(v1.gear.is_none() && v1.slip.is_none() && v1.abs.is_none());
        assert!(
            parse(br#"{"protocol":"omarchy-moza-ac/2","rpm":1,"redline":2,"idle":0,"boost":1}"#)
                .is_none()
        );
    }
}
