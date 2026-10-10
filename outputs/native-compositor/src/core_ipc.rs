//! One request per connection. A slow reply is never a reason to replay a mutation.
use std::{
    io::{Read, Write},
    os::unix::net::UnixStream,
    time::{Duration, Instant},
};

pub const RESPONSE_TIMEOUT: Duration = Duration::from_secs(2);
const MAX_RESPONSE: usize = 4 * 1024 * 1024;

pub fn exchange(mut stream: UnixStream, request: &[u8]) -> Result<Vec<u8>, String> {
    // Configure before sending: some Unix implementations reject timeout changes
    // after the peer closes. Short reads bound deadline overshoot to 50 ms.
    stream
        .set_read_timeout(Some(Duration::from_millis(50)))
        .map_err(|e| e.to_string())?;
    stream
        .set_write_timeout(Some(Duration::from_millis(200)))
        .map_err(|e| e.to_string())?;
    stream.write_all(request).map_err(|e| e.to_string())?;
    let deadline = Instant::now() + RESPONSE_TIMEOUT;
    let mut response = Vec::new();
    loop {
        if Instant::now() >= deadline {
            return Err("Core response timed out; outcome may be unknown".into());
        }
        let mut bytes = [0u8; 8192];
        let count = match stream.read(&mut bytes) {
            Ok(count) => count,
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(e)
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                ) =>
            {
                continue
            }
            Err(e) => return Err(e.to_string()),
        };
        if count == 0 {
            return Err("Incomplete core response; outcome may be unknown".into());
        }
        let end = bytes[..count]
            .iter()
            .position(|b| *b == b'\n')
            .map(|p| p + 1);
        response.extend_from_slice(&bytes[..end.unwrap_or(count)]);
        if response.len() > MAX_RESPONSE {
            return Err("Invalid core response".into());
        }
        if end.is_some() {
            return Ok(response);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn incomplete_and_oversized_responses_are_rejected() {
        for oversized in [false, true] {
            let (client, mut server) = UnixStream::pair().unwrap();
            let worker = std::thread::spawn(move || {
                let mut request = [0; 4];
                server.read_exact(&mut request).unwrap();
                if oversized {
                    let _ = server.write_all(&vec![b' '; MAX_RESPONSE + 1]);
                    let _ = server.write_all(b"\n");
                } else {
                    server.write_all(b"{\"ok\":true}").unwrap();
                }
            });
            let error = exchange(client, b"put\n").unwrap_err();
            assert!(
                error.contains(if oversized {
                    "Invalid core response"
                } else {
                    "Incomplete core response"
                }),
                "{error}"
            );
            worker.join().unwrap();
        }
    }
    #[test]
    fn delayed_fragmented_reply_does_not_resend_request() {
        let (client, mut server) = UnixStream::pair().unwrap();
        let worker = std::thread::spawn(move || {
            let mut request = [0; 4];
            server.read_exact(&mut request).unwrap();
            assert_eq!(&request, b"put\n");
            server.write_all(b"{\"ok\":").unwrap();
            std::thread::sleep(Duration::from_millis(300));
            server.write_all(b"true}\n").unwrap();
            let mut unexpected = [0];
            assert_eq!(
                server.read(&mut unexpected).unwrap(),
                0,
                "Request was replayed"
            );
        });
        assert_eq!(exchange(client, b"put\n").unwrap(), b"{\"ok\":true}\n");
        worker.join().unwrap();
    }
    #[test]
    fn partial_reply_has_one_total_deadline() {
        let (client, mut server) = UnixStream::pair().unwrap();
        let worker = std::thread::spawn(move || {
            let mut request = [0; 4];
            server.read_exact(&mut request).unwrap();
            // Keep delivering bytes faster than a per-read timeout. The total
            // deadline still bounds shutdown and reports an uncertain outcome.
            for _ in 0..30 {
                if server.write_all(b" ").is_err() {
                    break;
                }
                std::thread::sleep(Duration::from_millis(100));
            }
        });
        let started = Instant::now();
        assert!(exchange(client, b"put\n")
            .unwrap_err()
            .contains("outcome may be unknown"));
        assert!(started.elapsed() < Duration::from_secs(3));
        worker.join().unwrap();
    }
}
