//! Finds MOZA serial devices. The wheelbase follows Boxflat's own base
//! pattern, so Rust never claims a port that Boxflat treats as something else.
use std::{fs, path::Path};

pub const VENDOR: u16 = 0x346e;
pub const PEDAL_HAPTICS: u16 = 0x002f;

/// Boxflat's `MozaHidDevice.BASE`, applied to a `/dev/serial/by-id` name:
/// `gudsen (moza )?r[0-9]{1,2} (pro base|ultra base|base|racing wheel and pedals)`.
pub fn is_wheelbase(name: &str) -> bool {
    let name = name.to_lowercase().replace('_', " ");
    let Some(start) = name.find("gudsen ") else {
        return false;
    };
    let rest = &name[start + "gudsen ".len()..];
    let rest = rest.strip_prefix("moza ").unwrap_or(rest);
    let Some(rest) = rest.strip_prefix('r') else {
        return false;
    };
    let digits = rest.bytes().take_while(u8::is_ascii_digit).count();
    (1..=2).contains(&digits)
        && ["pro base", "ultra base", "base", "racing wheel and pedals"]
            .iter()
            .any(|model| rest[digits..].starts_with(&format!(" {model}")))
}

pub fn find_wheelbase() -> Option<String> {
    let dir = Path::new("/dev/serial/by-id");
    let mut names: Vec<_> = fs::read_dir(dir)
        .ok()?
        .filter_map(Result::ok)
        .filter_map(|entry| entry.file_name().into_string().ok())
        .filter(|name| is_wheelbase(name))
        .collect();
    names.sort();
    names
        .first()
        .map(|name| dir.join(name).to_string_lossy().into_owned())
}

/// Pedal haptic modules plugged straight into the computer, by USB ID.
pub fn find_pedal_haptics() -> Option<String> {
    let mut ports: Vec<_> = serialport::available_ports()
        .ok()?
        .into_iter()
        .filter(|port| {
            matches!(&port.port_type, serialport::SerialPortType::UsbPort(usb)
                if usb.vid == VENDOR && usb.pid == PEDAL_HAPTICS)
        })
        .map(|port| port.port_name)
        .collect();
    ports.sort();
    ports.into_iter().next()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_boxflat_base_names() {
        for name in [
            "usb-Gudsen_MOZA_R12_Base_0123-if00",
            "usb-Gudsen_R5_Base_0123-if00",
            "usb-Gudsen_MOZA_R9_Pro_Base_0123-if00",
            "usb-Gudsen_MOZA_R21_Ultra_Base_0123-if00",
            "usb-Gudsen_MOZA_R3_Racing_Wheel_and_Pedals_0123-if00",
        ] {
            assert!(is_wheelbase(name), "{name}");
        }
    }

    #[test]
    fn never_claims_other_moza_devices() {
        for name in [
            "usb-Gudsen_Pedal_Haptic_Feedback_Module_629138001040B10B33313532-if00",
            "usb-Gudsen_MOZA_SRP_Pedals_0123-if00",
            "usb-Gudsen_Universal_Hub_0123-if00",
            "usb-Gudsen_E-Stop_0123-if00",
            "usb-Gudsen_HBP_Handbrake_0123-if00",
            "usb-Gudsen_MOZA_R123_Base_0123-if00",
            "usb-Gudsen_MOZA_Rx_Base_0123-if00",
            "usb-Other_R12_Base_0123-if00",
        ] {
            assert!(!is_wheelbase(name), "{name}");
        }
    }
}
