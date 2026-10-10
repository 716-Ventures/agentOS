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
            "stdin_bytes",
            "terminal",
        ]
        .iter()
        .all(|key| proposal[key] == current[key])
}
pub fn continuation_request(job: &Value) -> Option<Value> {
    let id = job_id(job).ok()?;
    let activity = job["activity"].as_i64().filter(|id| *id > 0)?;
    let origin = job["origin"]["conversation_id"].as_str()?;
    if !["starting", "running", "succeeded", "failed", "interrupted"]
        .contains(&job["status"].as_str().unwrap_or(""))
    {
        return None;
    }
    if origin.len() != 32
        || !origin
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        || job["approved_by_uid"] != 0
        || !job["approved_at"]
            .as_f64()
            .is_some_and(|n| n.is_finite() && n >= 0.)
    {
        return None;
    }
    Some(
        json!({"op":"run","activity_id":activity,"argv":["/usr/bin/python3","-u","/usr/local/lib/agent-os/services/worker.py","resume",activity.to_string(),id]}),
    )
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
    privileged("approve", id, stop)
}
pub fn input(socket: PathBuf, proposal: Value, stop: Arc<AtomicBool>) -> Result<Value, String> {
    let id = job_id(&proposal)?;
    let current = super::transport::request(&socket, &json!({"op":"poll","job_id":id}))?;
    if !unchanged(&proposal, &current) {
        return Err("The proposal changed; review it again".into());
    }
    let value = privileged("input", id, stop)?;
    validate_input(&proposal, &value)?;
    Ok(value)
}
fn validate_input(proposal: &Value, value: &Value) -> Result<(), String> {
    if value["stdin_sha256"] != proposal["stdin_sha256"]
        || value["stdin_bytes"].as_u64().unwrap_or(0)
            != proposal["stdin_bytes"].as_u64().unwrap_or(0)
    {
        return Err("Stored input no longer matches the reviewed proposal".into());
    }
    let text = value["stdin"].as_str().ok_or("Stored input must be text")?;
    if text.len() > 65536 || Some(text.len() as u64) != value["stdin_bytes"].as_u64() {
        return Err("Stored input size mismatch".into());
    }
    Ok(())
}
fn privileged(operation: &str, id: &str, stop: Arc<AtomicBool>) -> Result<Value, String> {
    if !matches!(operation, "approve" | "input") {
        return Err("Unsupported broker review operation".into());
    }
    run_helper(
        "/usr/bin/sudo",
        &["-n", "/usr/local/bin/agent-os-broker", operation, id],
        stop,
    )
}
pub(crate) fn run_helper(
    program: &str,
    args: &[&str],
    stop: Arc<AtomicBool>,
) -> Result<Value, String> {
    if stop.load(Ordering::Relaxed) {
        return Err("Local action cancelled before dispatch".into());
    }
    let mut child = Command::new(program)
        .args(args)
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
                "Local action acknowledgement unavailable; inspect the existing job before retrying"
                    .into(),
            );
        }
        thread::sleep(Duration::from_millis(20));
    };
    let (read, bytes) = out.join().map_err(|_| "Local action output unavailable")?;
    let (_, errors) = err.join().map_err(|_| "Local action error unavailable")?;
    if !status?.success() {
        return Err(format!(
            "Local action failed: {}",
            String::from_utf8_lossy(&errors)
                .chars()
                .take(2000)
                .collect::<String>()
        ));
    }
    read.map_err(|e| e.to_string())?;
    if bytes.len() > 1024 * 1024 {
        return Err("Local action response exceeded its limit".into());
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
    #[test]
    fn continuation_is_a_typed_existing_job_reference_without_command_text() {
        let job = json!({"id":"a".repeat(32),"activity":1,"origin":{"conversation_id":"b".repeat(32)},"status":"succeeded","approved_by_uid":0,"approved_at":1,"argv":["/bin/echo","Untrusted command text"]});
        let request = continuation_request(&job).unwrap();
        assert_eq!(request["op"], "run");
        assert_eq!(request["argv"][3], "resume");
        assert_eq!(request["argv"][5], "a".repeat(32));
        assert!(!request.to_string().contains("Untrusted command text"));
        for change in [
            json!({"status":"cancelled"}),
            json!({"status":"cancelling"}),
            json!({"approved_by_uid":false}),
            json!({"activity":-1}),
            json!({"origin":{"conversation_id":"../escape"}}),
        ] {
            let mut invalid = job.clone();
            for (key, value) in change.as_object().unwrap() {
                invalid[key] = value.clone();
            }
            assert!(continuation_request(&invalid).is_none());
        }
    }
    use super::*;
    #[test]
    fn stored_input_preview_matches_the_frozen_proposal_and_byte_count() {
        let proposal = json!({"stdin_sha256":"abc","stdin_bytes":3});
        let value = json!({"stdin_sha256":"abc","stdin_bytes":3,"stdin":"λ!"});
        assert!(validate_input(&proposal, &value).is_ok());
        for key in ["stdin_sha256", "stdin_bytes", "stdin"] {
            let mut changed = value.clone();
            changed[key] = json!("changed");
            assert!(validate_input(&proposal, &changed).is_err());
        }
    }
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
            "stdin_bytes",
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
