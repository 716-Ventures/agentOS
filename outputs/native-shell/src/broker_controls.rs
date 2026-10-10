//! Human-only broker approval and conventional terminal attachment.
use serde_json::{json, Value};
use std::{
    io::Read,
    os::unix::process::CommandExt,
    path::PathBuf,
    process::{Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread,
    time::{Duration, Instant},
};
pub fn job_id(job: &Value) -> Result<&str, String> {
    job["id"]
        .as_str()
        .filter(|id| {
            id.len() == 32
                && id
                    .bytes()
                    .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
        })
        .ok_or("Invalid broker job identity".into())
}
pub fn unchanged(proposal: &Value, current: &Value) -> bool {
    current["status"] == "approval_required"
        && [
            "id",
            "argv",
            "activity",
            "scope",
            "cwd",
            "stdin_sha256",
            "terminal",
        ]
        .iter()
        .all(|key| proposal[key] == current[key])
}
pub fn approve(socket: PathBuf, proposal: Value, stop: Arc<AtomicBool>) -> Result<Value, String> {
    let id = job_id(&proposal)?;
    let current = super::transport::request(&socket, &json!({"op":"poll","job_id":id}))?;
    if !unchanged(&proposal, &current) {
        return Err("The proposal changed or was already handled; review it again".into());
    }
    if stop.load(Ordering::Relaxed) {
        return Err("Approval cancelled before dispatch".into());
    }
    let mut child = Command::new("/usr/bin/sudo")
        .args(["-n", "/usr/local/bin/agent-os-broker", "approve", id])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0)
        .spawn()
        .map_err(|e| e.to_string())?;
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();
    let out = thread::spawn(move || {
        let mut bytes = Vec::new();
        let result = stdout.take(1024 * 1024 + 1).read_to_end(&mut bytes);
        (result, bytes)
    });
    let err = thread::spawn(move || {
        let mut bytes = Vec::new();
        let result = stderr.take(65537).read_to_end(&mut bytes);
        (result, bytes)
    });
    let deadline = Instant::now() + Duration::from_secs(15);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) => {}
            Err(e) => break Err(e.to_string()),
        }
        if stop.load(Ordering::Relaxed) || Instant::now() >= deadline {
            unsafe {
                libc::kill(-(child.id() as i32), libc::SIGTERM);
            }
            let _ = child.kill();
            let _ = child.wait();
            break Err(
                "Approval acknowledgement unavailable; inspect this existing job before retrying"
                    .into(),
            );
        }
        thread::sleep(Duration::from_millis(20));
    };
    let (read, bytes) = out.join().map_err(|_| "Approval output unavailable")?;
    let (_, errors) = err.join().map_err(|_| "Approval error unavailable")?;
    if !status?.success() {
        return Err(format!(
            "Approval failed: {}",
            String::from_utf8_lossy(&errors)
                .chars()
                .take(2000)
                .collect::<String>()
        ));
    }
    read.map_err(|e| e.to_string())?;
    if bytes.len() > 1024 * 1024 {
        return Err("Approval response exceeded its limit".into());
    }
    serde_json::from_slice(&bytes).map_err(|e| e.to_string())
}
pub fn attach(job: &Value) -> Result<Value, String> {
    let id = job_id(job)?;
    if job["terminal"] != true || job["status"] != "running" {
        return Err("This work has no running interactive terminal".into());
    }
    let mut child = Command::new("weston-terminal")
        .args([
            "--shell",
            &format!("/usr/local/bin/agent-os attach broker:{id}"),
        ])
        .spawn()
        .map_err(|e| e.to_string())?;
    thread::spawn(move || {
        let _ = child.wait();
    });
    Ok(json!({"status":"Terminal opened · Ctrl-] detaches without stopping work"}))
}

pub fn open_terminal() -> Result<Value, String> {
    let mut child = Command::new("weston-terminal")
        .args(["--shell", "/bin/bash"])
        .spawn()
        .map_err(|e| e.to_string())?;
    thread::spawn(move || {
        let _ = child.wait();
    });
    Ok(json!({"status":"Local terminal opened"}))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stale_review_cannot_authorize_changed_command_or_input() {
        let proposal = json!({"id":"0123456789abcdef0123456789abcdef","status":"approval_required","argv":["/bin/rm","/tmp/example"],"activity":1,"scope":"system","cwd":"/tmp","stdin_sha256":"abc","terminal":false});
        assert!(unchanged(&proposal, &proposal));
        for key in [
            "argv",
            "activity",
            "scope",
            "cwd",
            "stdin_sha256",
            "terminal",
            "status",
        ] {
            let mut changed = proposal.clone();
            changed[key] = json!("changed");
            assert!(!unchanged(&proposal, &changed), "{key}");
        }
        assert!(job_id(&proposal).is_ok());
        assert!(job_id(&json!({"id":"; injected"})).is_err());
    }
}
