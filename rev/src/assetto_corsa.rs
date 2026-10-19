//! Exact AC telemetry from the companion CSP app, never an observed RPM peak.
use moza_rev::listeners::{EngineState, GameId, Update};
use serde::Deserialize;
use std::{io, net::UdpSocket, sync::mpsc, thread};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Packet {
    protocol: String,
    rpm: i32,
    redline: i32,
    idle: i32,
}

fn parse(bytes: &[u8]) -> Option<EngineState> {
    let p: Packet = serde_json::from_slice(bytes).ok()?;
    if p.protocol != "omarchy-moza-ac/1" || p.rpm < 0 || p.idle < 0 || p.redline <= p.idle {
        return None;
    }
    Some(EngineState {
        rpm: p.rpm,
        rpm_redline: p.redline,
        rpm_idle: p.idle,
    })
}

pub fn spawn(port: u16, tx: mpsc::Sender<Update>) -> bool {
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
                if let Some(engine) = parse(&buffer[..n])
                    && tx
                        .send(Update {
                            game: GameId::AssettoCorsa,
                            engine,
                        })
                        .is_err()
                {
                    break;
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
            let engine = parse(&packet(rpm, redline, idle)).unwrap();
            assert_eq!(engine.rpm_redline, redline);
            assert_eq!(engine.rpm, rpm);
            assert_eq!(engine.rpm_idle, idle);
        }
        // Over-revving on a downshift must not move the reported limit.
        assert_eq!(parse(&packet(7200, 6500, 1250)).unwrap().rpm_redline, 6500);
        assert_eq!(parse(&packet(0, 500, 100)).unwrap().rpm, 0);
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
}
