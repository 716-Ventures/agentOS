//! Bounded, cancellable focus handoffs to the trusted desktop compositor.
use crate::gtk::{gio, glib};
use gio::prelude::{SocketExt, SocketExtManual};
use serde_json::{json, Value};
use std::{
    path::Path,
    sync::atomic::{AtomicBool, Ordering},
    thread,
    time::{Duration, Instant},
};

pub enum Target<'a> {
    Monitor,
    Settings,
    Terminal(&'a str),
    VoiceReview,
}

/// Only an acknowledged receipt completes a handoff. Connection pressure,
/// partial replies and retries share one two-second monotonic deadline.
pub fn present(path: &Path, target: Target<'_>, stop: &AtomicBool) -> Result<(), String> {
    let value = match target {
        Target::Monitor => json!({"op":"monitor.present"}),
        Target::Settings => json!({"op":"settings.present"}),
        Target::Terminal(identity) => json!({"op":"terminal.present","app_id":identity}),
        Target::VoiceReview => json!({"op":"voice_review.present"}),
    };
    let mut message = serde_json::to_vec(&value).map_err(|error| error.to_string())?;
    message.push(b'\n');
    if message.len() > 65536 {
        return Err("Control focus request exceeds its limit".into());
    }
    let deadline = Instant::now() + Duration::from_secs(2);
    let mut result = Err("Control unavailable".into());
    for _ in 0..40 {
        if stop.load(Ordering::Relaxed) {
            return Err("Control focus cancelled".into());
        }
        remaining(deadline)?;
        let attempt_deadline = deadline.min(Instant::now() + Duration::from_millis(250));
        result = attempt(path, &message, attempt_deadline);
        if stop.load(Ordering::Relaxed) {
            return Err("Control focus cancelled".into());
        }
        if result.is_ok() {
            return result;
        }
        thread::sleep(remaining(deadline)?.min(Duration::from_millis(25)));
    }
    result
}

fn remaining(deadline: Instant) -> Result<Duration, String> {
    let duration = deadline.saturating_duration_since(Instant::now());
    if duration.is_zero() {
        Err("Control focus timed out".into())
    } else {
        Ok(duration)
    }
}
fn wait(
    socket: &gio::Socket,
    condition: glib::IOCondition,
    deadline: Instant,
) -> Result<(), String> {
    let timeout = remaining(deadline)?.as_micros().min(i64::MAX as u128) as i64;
    socket
        .condition_timed_wait(condition, timeout, None::<&gio::Cancellable>)
        .map_err(|error| error.to_string())
}
fn attempt(path: &Path, message: &[u8], deadline: Instant) -> Result<(), String> {
    let socket = gio::Socket::new(
        gio::SocketFamily::Unix,
        gio::SocketType::Stream,
        gio::SocketProtocol::Default,
    )
    .map_err(|error| error.to_string())?;
    socket.set_blocking(false);
    remaining(deadline)?;
    match socket.connect(
        &gio::UnixSocketAddress::new(path),
        None::<&gio::Cancellable>,
    ) {
        Ok(()) => {}
        Err(error)
            if error.matches(gio::IOErrorEnum::Pending)
                || error.matches(gio::IOErrorEnum::WouldBlock) =>
        {
            wait(&socket, glib::IOCondition::OUT, deadline)?;
            socket
                .check_connect_result()
                .map_err(|error| error.to_string())?;
        }
        Err(error) => return Err(error.to_string()),
    }
    let mut written = 0;
    while written < message.len() {
        remaining(deadline)?;
        match socket.send(&message[written..], None::<&gio::Cancellable>) {
            Ok(0) => return Err("Control focus connection closed".into()),
            Ok(count) => written += count,
            Err(error) if error.matches(gio::IOErrorEnum::WouldBlock) => {
                wait(&socket, glib::IOCondition::OUT, deadline)?
            }
            Err(error) => return Err(error.to_string()),
        }
    }
    let mut response = Vec::new();
    let mut buffer = [0u8; 1024];
    loop {
        remaining(deadline)?;
        match socket.receive(&mut buffer, None::<&gio::Cancellable>) {
            Ok(0) => return Err("Control focus connection closed".into()),
            Ok(count) => {
                response.extend_from_slice(&buffer[..count]);
                if response.len() > 16384 {
                    return Err("Control focus reply exceeds its limit".into());
                }
                if let Some(end) = response.iter().position(|byte| *byte == b'\n') {
                    let reply: Value = serde_json::from_slice(&response[..end])
                        .map_err(|error| error.to_string())?;
                    remaining(deadline)?;
                    return if reply["ok"] == true && reply["result"].is_object() {
                        Ok(())
                    } else {
                        Err(reply["error"]
                            .as_str()
                            .unwrap_or("Invalid control focus receipt")
                            .into())
                    };
                }
            }
            Err(error) if error.matches(gio::IOErrorEnum::WouldBlock) => {
                wait(&socket, glib::IOCondition::IN, deadline)?
            }
            Err(error) => return Err(error.to_string()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{BufRead, BufReader, Write},
        os::unix::net::{UnixListener, UnixStream},
        path::PathBuf,
    };
    fn listener() -> (PathBuf, UnixListener) {
        let path = std::env::temp_dir().join(format!(
            "agentos-focus-{}-{}.sock",
            std::process::id(),
            crate::nonce()
        ));
        let listener = UnixListener::bind(&path).unwrap();
        listener.set_nonblocking(true).unwrap();
        (path, listener)
    }
    fn accept(listener: &UnixListener) -> UnixStream {
        let deadline = Instant::now() + Duration::from_secs(4);
        loop {
            match listener.accept() {
                Ok((stream, _)) => {
                    stream
                        .set_read_timeout(Some(Duration::from_secs(1)))
                        .unwrap();
                    return stream;
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    assert!(
                        Instant::now() < deadline,
                        "Focus test client did not connect"
                    );
                    thread::sleep(Duration::from_millis(5));
                }
                Err(error) => panic!("Focus test accept failed: {error}"),
            }
        }
    }
    #[test]
    fn waits_for_a_focus_receipt_and_preserves_the_exact_target() {
        let (path, listener) = listener();
        let value = json!({"op":"terminal.present","app_id":"agentos.local-terminal.00000000000000000000000000000001"});
        let expected = value.clone();
        let server = thread::spawn(move || {
            for attempt in 0..3 {
                let mut stream = accept(&listener);
                let mut line = String::new();
                BufReader::new(&mut stream).read_line(&mut line).unwrap();
                assert_eq!(serde_json::from_str::<Value>(&line).unwrap(), expected);
                writeln!(
                    stream,
                    "{}",
                    if attempt < 2 {
                        json!({"ok":false,"error":"Control focus pending"})
                    } else {
                        json!({"ok":true,"result":{"focused":true}})
                    }
                )
                .unwrap();
            }
        });
        let result = present(
            &path,
            Target::Terminal(value["app_id"].as_str().unwrap()),
            &AtomicBool::new(false),
        );
        let joined = server.join();
        std::fs::remove_file(path).unwrap();
        joined.unwrap();
        result.unwrap();
    }
    #[test]
    fn stalled_replies_cannot_extend_the_whole_focus_handoff() {
        let (path, listener) = listener();
        let server = thread::spawn(move || {
            let mut stream = accept(&listener);
            let mut line = String::new();
            BufReader::new(&mut stream).read_line(&mut line).unwrap();
            // Hold the real socket open without acknowledging any request.
            thread::sleep(Duration::from_millis(2300));
            drop(stream);
            drop(listener);
        });
        let started = Instant::now();
        let result = present(&path, Target::Settings, &AtomicBool::new(false));
        let elapsed = started.elapsed();
        let joined = server.join();
        std::fs::remove_file(path).unwrap();
        joined.unwrap();
        println!("Stalled focus handoff: {elapsed:?}");
        assert!(result.is_err(), "Stalled focus falsely completed");
        assert!(
            elapsed < Duration::from_millis(2800),
            "Stalled replies exceeded the handoff deadline: {elapsed:?}"
        );
    }
    #[test]
    fn cancelled_focus_does_not_enqueue_a_late_request() {
        let (path, listener) = listener();
        let result = present(&path, Target::VoiceReview, &AtomicBool::new(true));
        let connected = listener.accept().is_ok();
        drop(listener);
        std::fs::remove_file(path).unwrap();
        assert!(result.is_err());
        assert!(!connected, "Cancellation still enqueued a focus request");
    }
    #[test]
    fn partial_reply_progress_does_not_reset_the_focus_deadline() {
        let (path, listener) = listener();
        let server = thread::spawn(move || {
            let mut stream = accept(&listener);
            let mut line = String::new();
            BufReader::new(&mut stream).read_line(&mut line).unwrap();
            for _ in 0..40 {
                if stream.write_all(b" ").is_err() {
                    break;
                }
                thread::sleep(Duration::from_millis(100));
            }
        });
        let started = Instant::now();
        let result = present(&path, Target::Monitor, &AtomicBool::new(false));
        let elapsed = started.elapsed();
        let joined = server.join();
        std::fs::remove_file(path).unwrap();
        joined.unwrap();
        println!("Partial-reply focus handoff: {elapsed:?}");
        assert!(
            result.is_err(),
            "An incomplete reply falsely completed focus"
        );
        assert!(
            elapsed < Duration::from_millis(2800),
            "Partial bytes reset the deadline: {elapsed:?}"
        );
    }
    #[test]
    #[cfg(target_os = "linux")]
    fn full_connection_queue_cannot_block_focus_past_its_deadline() {
        use std::os::fd::AsRawFd;
        let (path, listener) = listener();
        // Linux allows the first pending connection at backlog zero. The next
        // blocking connect then waits for accept or listener shutdown.
        assert_eq!(unsafe { libc::listen(listener.as_raw_fd(), 0) }, 0);
        let queued = UnixStream::connect(&path).unwrap();
        let server = thread::spawn(move || {
            thread::sleep(Duration::from_millis(3500));
            drop(listener);
        });
        let started = Instant::now();
        let result = present(&path, Target::Settings, &AtomicBool::new(false));
        let elapsed = started.elapsed();
        let joined = server.join();
        drop(queued);
        std::fs::remove_file(path).unwrap();
        joined.unwrap();
        println!("Full-queue focus handoff: {elapsed:?}");
        assert!(result.is_err());
        assert!(
            elapsed < Duration::from_millis(2800),
            "Connect blocked beyond the deadline: {elapsed:?}"
        );
    }
}
