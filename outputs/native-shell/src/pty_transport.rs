//! A human attachment owns one broker PTY token; no token enters shared documents.
use base64::{engine::general_purpose::STANDARD, Engine};
use serde_json::{json, Value};
use std::{
    collections::VecDeque,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Receiver, SyncSender},
        Arc, Mutex,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};
#[derive(Default)]
pub struct Display {
    pub chunks: VecDeque<(Vec<u8>, bool)>,
    pub attached: bool,
    pub finished: bool,
    pub notice: String,
}
pub struct Session {
    pub display: Arc<Mutex<Display>>,
    input: SyncSender<Vec<u8>>,
    size: Arc<Mutex<(u32, u32)>>,
    stop: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
}
impl Session {
    pub fn start(
        socket: PathBuf,
        job: String,
        activity: String,
        size: (u32, u32),
    ) -> Result<Self, String> {
        super::broker_controls::job_id(&json!({"id":job}))?;
        if !valid_size(size) {
            return Err("Invalid terminal grid".into());
        }
        let display = Arc::new(Mutex::new(Display {
            notice: "Attaching terminal…".into(),
            ..Display::default()
        }));
        let (input, receive) = mpsc::sync_channel(32);
        let size = Arc::new(Mutex::new(size));
        let stop = Arc::new(AtomicBool::new(false));
        let (output, grid, cancel) = (display.clone(), size.clone(), stop.clone());
        let worker =
            thread::spawn(move || run(socket, job, activity, output, grid, cancel, receive));
        Ok(Self {
            display,
            input,
            size,
            stop,
            worker: Some(worker),
        })
    }
    pub fn write(&self, bytes: Vec<u8>) -> Result<(), String> {
        if bytes.len() > 65536 {
            return Err("Terminal input exceeds 64 KiB".into());
        }
        if !self.display.lock().unwrap().attached {
            return Err("Terminal is detached".into());
        }
        self.input
            .try_send(bytes)
            .map_err(|_| "Terminal input queue is full or closed; input was not queued".into())
    }
    pub fn cancel(&self) {
        self.stop.store(true, Ordering::Relaxed);
    }
    pub fn cancelled(&self) -> bool {
        self.stop.load(Ordering::Relaxed)
    }
    pub fn resize(&self, size: (u32, u32)) {
        if valid_size(size) {
            *self.size.lock().unwrap() = size;
        }
    }
}
impl Drop for Session {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}
fn valid_size((rows, cols): (u32, u32)) -> bool {
    (1..=500).contains(&rows) && (1..=1000).contains(&cols)
}
fn decode_page(page: &Value, cursor: u64) -> Result<(Vec<u8>, bool, u64, bool), String> {
    let encoded = page["data"]
        .as_str()
        .filter(|v| v.len() <= 21848)
        .ok_or("Invalid terminal display encoding")?;
    let bytes = STANDARD
        .decode(encoded)
        .map_err(|_| "Invalid terminal display bytes")?;
    if bytes.len() > 16384 {
        return Err("Terminal display exceeds 16 KiB".into());
    }
    let reset = page["reset"]
        .as_bool()
        .ok_or("Invalid terminal reset state")?;
    let next = page["cursor"]
        .as_u64()
        .ok_or("Invalid terminal display cursor")?;
    if next
        != if reset {
            bytes.len() as u64
        } else {
            cursor
                .checked_add(bytes.len() as u64)
                .ok_or("Terminal cursor overflow")?
        }
    {
        return Err("Terminal display cursor does not match bytes".into());
    }
    let closed = page["closed"]
        .as_bool()
        .ok_or("Invalid terminal close state")?;
    Ok((bytes, reset, next, closed))
}
fn run(
    socket: PathBuf,
    job: String,
    activity: String,
    display: Arc<Mutex<Display>>,
    size: Arc<Mutex<(u32, u32)>>,
    stop: Arc<AtomicBool>,
    input: Receiver<Vec<u8>>,
) {
    let mut token = None;
    let result = (|| -> Result<(), String> {
        let current = super::transport::request(&socket, &json!({"op":"poll","job_id":job}))?;
        if current["id"] != job
            || current["activity"]
                .as_i64()
                .map(|v| v.to_string())
                .as_deref()
                != Some(activity.as_str())
            || current["terminal"] != true
            || current["status"] != "running"
        {
            return Err("This activity has no running PTY for the referenced work".into());
        }
        if stop.load(Ordering::Relaxed) {
            return Ok(());
        }
        let mut grid = *size.lock().unwrap();
        let attached = super::transport::request(
            &socket,
            &json!({"op":"terminal_attach","job_id":job,"rows":grid.0,"cols":grid.1}),
        )?;
        let owned = attached["token"]
            .as_str()
            .filter(|v| v.len() == 32 && v.bytes().all(|b| b.is_ascii_hexdigit()))
            .ok_or("Invalid terminal attachment token")?
            .to_string();
        token = Some(owned.clone());
        {
            let mut state = display.lock().unwrap();
            state.attached = true;
            state.notice = "Attached · input goes directly to this running terminal".into();
        }
        let mut cursor = 0;
        let mut pending = VecDeque::new();
        let mut resized = Instant::now();
        while !stop.load(Ordering::Relaxed) {
            // At most one pending input chunk; partial writes retry exactly the suffix.
            if pending.is_empty() {
                if let Ok(bytes) = input.try_recv() {
                    pending.extend(bytes);
                }
            }
            if !pending.is_empty() {
                let bytes = pending.iter().take(4096).copied().collect::<Vec<_>>();
                let response = super::transport::request(
                    &socket,
                    &json!({"op":"terminal_write","job_id":job,"token":owned,"data":STANDARD.encode(&bytes)}),
                ).map_err(|error|format!("Input delivery is uncertain; inspect the terminal before typing again: {error}"))?;
                let written = response["written"]
                    .as_u64()
                    .filter(|n| *n <= bytes.len() as u64)
                    .ok_or("Invalid terminal input acknowledgement")?
                    as usize;
                pending.drain(..written);
            }
            let wanted = *size.lock().unwrap();
            if wanted != grid && resized.elapsed() >= Duration::from_millis(200) {
                super::transport::request(
                    &socket,
                    &json!({"op":"terminal_resize","job_id":job,"token":owned,"rows":wanted.0,"cols":wanted.1}),
                )?;
                grid = wanted;
                resized = Instant::now();
            }
            if display.lock().unwrap().chunks.len() < 8 {
                let page = super::transport::request(
                    &socket,
                    &json!({"op":"terminal_read","job_id":job,"token":owned,"cursor":cursor}),
                )?;
                let (bytes, reset, next, closed) = decode_page(&page, cursor)?;
                cursor = next;
                if !bytes.is_empty() || reset {
                    display.lock().unwrap().chunks.push_back((bytes, reset));
                }
                if closed {
                    return Ok(());
                }
            }
            thread::sleep(Duration::from_millis(20));
        }
        Ok(())
    })();
    if let Some(owned) = token {
        let _ = super::transport::request(
            &socket,
            &json!({"op":"terminal_detach","job_id":job,"token":owned}),
        );
    }
    let mut state = display.lock().unwrap();
    state.attached = false;
    state.finished = true;
    state.notice = match result {
        Ok(()) => "Terminal detached or exited · saved output remains available in Work".into(),
        Err(error) => format!("Terminal unavailable: {error}"),
    };
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn attachment_retries_only_unwritten_input_and_detaches_on_drop() {
        use std::{
            io::{BufRead, BufReader, Write},
            os::unix::net::UnixListener,
        };
        let path = std::env::temp_dir().join(format!(
            "agentos-pty-{}-{}.sock",
            std::process::id(),
            super::super::nonce()
        ));
        let listener = UnixListener::bind(&path).unwrap();
        let written = Arc::new(Mutex::new(Vec::<u8>::new()));
        let received = written.clone();
        let observed = Arc::new(Mutex::new(Vec::<String>::new()));
        let calls = observed.clone();
        let id = "a".repeat(32);
        let job = id.clone();
        let server = thread::spawn(move || {
            let mut cursor = 0;
            loop {
                let (mut conn, _) = listener.accept().unwrap();
                conn.set_read_timeout(Some(Duration::from_secs(3))).unwrap();
                let mut raw = String::new();
                BufReader::new(conn.try_clone().unwrap())
                    .read_line(&mut raw)
                    .unwrap();
                let query: Value = serde_json::from_str(&raw).unwrap();
                let op = query["op"].as_str().unwrap();
                calls.lock().unwrap().push(op.into());
                let result = match op {
                    "poll" => json!({"id":job,"activity":1,"terminal":true,"status":"running"}),
                    "terminal_attach" => json!({"token":"b".repeat(32),"cursor":0}),
                    "terminal_read" => {
                        let bytes = if cursor == 0 {
                            b"\x1b[32mready\r\n".to_vec()
                        } else {
                            vec![]
                        };
                        cursor += bytes.len();
                        json!({"data":STANDARD.encode(bytes),"cursor":cursor,"reset":false,"closed":false})
                    }
                    "terminal_write" => {
                        let bytes = STANDARD.decode(query["data"].as_str().unwrap()).unwrap();
                        let count = bytes.len().min(2);
                        received.lock().unwrap().extend(&bytes[..count]);
                        json!({"written":count})
                    }
                    "terminal_resize" => json!({"resized":true}),
                    "terminal_detach" => json!({"detached":true}),
                    _ => panic!("Unexpected PTY operation"),
                };
                writeln!(conn, "{}", json!({"ok":true,"result":result})).unwrap();
                if op == "terminal_detach" {
                    break;
                }
            }
        });
        let session = Session::start(path.clone(), id, "1".into(), (24, 80)).unwrap();
        let deadline = Instant::now() + Duration::from_secs(3);
        while !session.display.lock().unwrap().attached {
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(10));
        }
        assert!(session.write(vec![0; 65537]).is_err());
        session.write(b"x\n\x03z".to_vec()).unwrap();
        session.resize((30, 100));
        while written.lock().unwrap().len() != 4
            || !observed
                .lock()
                .unwrap()
                .iter()
                .any(|op| op == "terminal_resize")
        {
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(10));
        }
        assert_eq!(*written.lock().unwrap(), b"x\n\x03z");
        assert!(session
            .display
            .lock()
            .unwrap()
            .chunks
            .iter()
            .any(|(bytes, _)| bytes == b"\x1b[32mready\r\n"));
        drop(session);
        server.join().unwrap();
        std::fs::remove_file(path).unwrap();
        let calls = observed.lock().unwrap();
        assert_eq!(calls.iter().filter(|op| *op == "terminal_write").count(), 2);
        assert_eq!(calls.last().unwrap(), "terminal_detach");
    }
    #[test]
    fn terminal_pages_preserve_raw_bytes_and_require_exact_cursor_boundaries() {
        let mut page = json!({"data":STANDARD.encode([0,0xff,b'\n']),"cursor":10,"reset":false,"closed":false});
        assert_eq!(decode_page(&page, 7).unwrap().0, vec![0, 0xff, b'\n']);
        assert!(decode_page(&page, 6).is_err());
        page["reset"] = json!(true);
        page["cursor"] = json!(3);
        assert!(decode_page(&page, 999).unwrap().1);
        page["data"] = json!(STANDARD.encode(vec![0; 16385]));
        assert!(decode_page(&page, 0).is_err());
        page["data"] = json!("!!!");
        assert!(decode_page(&page, 0).is_err());
        assert!(!valid_size((0, 80)));
        assert!(!valid_size((24, 1001)));
        assert!(valid_size((500, 1000)));
    }
}
