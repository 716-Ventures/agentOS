//! Bounded page navigation. Each page retains its source identity and byte offsets.
use serde_json::{json, Value};
use std::path::PathBuf;
#[derive(Clone, Debug)]
pub struct Page {
    pub text: String,
    pub source: String,
    pub job: Value,
    pub activity: i64,
    pub title: String,
    pub start: u64,
    pub end: u64,
    pub has_more: bool,
    pub has_previous: bool,
}
pub struct LogView {
    source: String,
    job: Value,
    activity: i64,
    title: String,
    offsets: Vec<u64>,
    position: usize,
    next: u64,
    more: bool,
}
impl LogView {
    pub fn new(source: String, job: Value, activity: i64, title: String) -> Result<Self, String> {
        if !["core", "broker"].contains(&source.as_str())
            || (source == "core" && job.as_i64().filter(|id| *id > 0).is_none())
            || (source == "broker" && super::broker_controls::job_id(&json!({"id":job})).is_err())
        {
            return Err("Invalid output source".into());
        }
        Ok(Self {
            source,
            job,
            activity,
            title,
            offsets: vec![0],
            position: 0,
            next: 0,
            more: false,
        })
    }
    pub fn start_at(&mut self, offset: u64) {
        self.offsets = if offset == 0 {
            vec![0]
        } else {
            vec![0, offset]
        };
        self.position = self.offsets.len() - 1;
        self.next = offset;
        self.more = false;
    }
    pub fn read(&mut self, core: &PathBuf, direction: i8) -> Result<Page, String> {
        let previous_position = self.position;
        if direction < 0 {
            self.position = self.position.saturating_sub(1);
        } else if direction > 0 {
            if self.position + 1 < self.offsets.len() {
                self.position += 1;
            } else if self.more && self.next > self.offsets[self.position] {
                self.offsets.push(self.next);
                self.position += 1;
            }
        }
        let offset = self.offsets[self.position];
        let response = super::transport::request(
            &if self.source == "core" {
                core.clone()
            } else {
                super::transport::broker_socket()
            },
            &json!({"op":if self.source=="core"{"log"}else{"poll"},"job_id":self.job,"offset":offset}),
        );
        let data = match response {
            Ok(data) => data,
            Err(e) => {
                self.position = previous_position;
                return Err(e);
            }
        };
        let end = data[if self.source == "core" {
            "offset"
        } else {
            "next_offset"
        }]
        .as_u64()
        .filter(|end| *end >= offset)
        .ok_or("Invalid output cursor")?;
        let text = data[if self.source == "core" {
            "text"
        } else {
            "output"
        }]
        .as_str()
        .ok_or("Output unavailable")?;
        if text.len() > 128 * 1024 {
            return Err("Output page exceeded its limit".into());
        }
        self.next = end;
        self.more = data["has_more"] == true;
        Ok(Page {
            text: text.into(),
            source: self.source.clone(),
            job: self.job.clone(),
            activity: self.activity,
            title: self.title.clone(),
            start: offset,
            end,
            has_more: self.more && end > offset,
            has_previous: self.position > 0,
        })
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{BufRead, BufReader, Write},
        os::unix::net::UnixListener,
        thread,
    };
    #[test]
    fn pages_keep_identity_and_retry_the_same_offset_after_disconnect() {
        let root = std::env::temp_dir().join(format!(
            "agentos-log-view-{}-{}",
            std::process::id(),
            super::super::nonce()
        ));
        std::fs::create_dir(&root).unwrap();
        let path = root.join("core.sock");
        let listener = UnixListener::bind(&path).unwrap();
        let server = thread::spawn(move || {
            for (index, expected) in [0, 10, 10, 0, 0].into_iter().enumerate() {
                let (mut conn, _) = listener.accept().unwrap();
                let mut line = String::new();
                BufReader::new(conn.try_clone().unwrap())
                    .read_line(&mut line)
                    .unwrap();
                let request: Value = serde_json::from_str(&line).unwrap();
                assert_eq!(request["offset"], expected);
                assert_eq!(request["job_id"], 7);
                let response = if index == 1 {
                    json!({"ok":false,"error":"Temporarily unavailable"})
                } else {
                    json!({"ok":true,"result":{"text":if expected==0{"first λ"}else{"second 日本語"},"offset":expected+10,"has_more":expected==0}})
                };
                writeln!(conn, "{response}").unwrap();
            }
        });
        let mut view = LogView::new("core".into(), json!(7), 3, "Selected work".into()).unwrap();
        let first = view.read(&path, 0).unwrap();
        assert_eq!(first.text, "first λ");
        assert!(first.has_more);
        assert!(!first.has_previous);
        assert!(view.read(&path, 1).is_err());
        let next = view.read(&path, 1).unwrap();
        assert_eq!(next.start, 10);
        assert_eq!(next.text, "second 日本語");
        assert_eq!(next.activity, 3);
        assert!(next.has_previous);
        assert!(!next.has_more);
        assert_eq!(view.read(&path, -1).unwrap().start, 0);
        assert_eq!(view.read(&path, 0).unwrap().text, "first λ");
        server.join().unwrap();
        std::fs::remove_dir_all(root).unwrap();
    }
}
