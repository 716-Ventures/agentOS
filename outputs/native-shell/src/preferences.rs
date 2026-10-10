use super::*;
use std::{
    fs::{self, OpenOptions},
    io::Write,
    os::unix::fs::OpenOptionsExt,
};
pub fn path() -> PathBuf {
    PathBuf::from(std::env::var_os("XDG_CONFIG_HOME").unwrap_or_else(|| {
        PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
            .join(".config")
            .into_os_string()
    }))
    .join("agent-os/desktop.json")
}
pub fn read() -> Value {
    fs::read_to_string(path())
        .ok()
        .filter(|s| s.len() <= 16384)
        .and_then(|s| serde_json::from_str(&s).ok())
        .filter(valid)
        .unwrap_or_else(|| json!({"appearance":"dark","text_scale":1.0,"reduced_motion":false}))
}
fn valid(value: &Value) -> bool {
    value.as_object().map(|m| m.len() == 3).unwrap_or(false)
        && matches!(value["appearance"].as_str(), Some("light" | "dark"))
        && value["text_scale"]
            .as_f64()
            .map(|n| n.is_finite() && (1.0..=3.0).contains(&n))
            .unwrap_or(false)
        && value["reduced_motion"].is_boolean()
}
pub fn save(value: &Value) -> Result<Value, String> {
    if !valid(value) {
        return Err("Invalid desktop preferences".into());
    }
    let path = path();
    let parent = path.parent().unwrap();
    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let temporary = parent.join(format!(".desktop-{}-{}", std::process::id(), nonce()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&temporary)?;
        file.write_all(value.to_string().as_bytes())?;
        file.sync_all()?;
        fs::rename(&temporary, &path)?;
        fs::File::open(parent)?.sync_all()
    })()
    .map_err(|e: std::io::Error| e.to_string());
    let _ = fs::remove_file(temporary);
    result.map(|_| json!({"status":"Desktop preferences saved"}))
}
