//! MOZA serial framing: `7e LEN GROUP DEVICE PAYLOAD CHECKSUM`.

/// Escape exactly like moza-rev: body 0x7e bytes are doubled on the wire and
/// both copies contribute to the checksum.
pub fn frame(group: u8, device: u8, payload: &[u8]) -> Vec<u8> {
    let mut frame = vec![0x7e, payload.len() as u8, group, device];
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
