//! Private local recovery when the core is unavailable. Cached text is never an action.
use super::transport::Draft;
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    fs::{self, OpenOptions},
    io::{Read, Write},
    os::unix::fs::{DirBuilderExt, OpenOptionsExt},
    path::{Path, PathBuf},
};
pub type Drafts = BTreeMap<(String, String), Draft>;
const LIMIT: u64 = 16 * 1024 * 1024;
pub fn path() -> PathBuf {
    PathBuf::from(std::env::var_os("XDG_STATE_HOME").unwrap_or_else(|| {
        PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
            .join(".local/state")
            .into_os_string()
    }))
    .join("agent-os/native-drafts.json")
}
fn identifier(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 128
        && s.bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"_-:.".contains(&c))
}
pub fn load(path: &Path) -> Drafts {
    let read = (|| -> Option<Drafts> {
        let file = fs::File::open(path).ok()?;
        let mut bytes = Vec::new();
        file.take(LIMIT + 1).read_to_end(&mut bytes).ok()?;
        if bytes.len() as u64 > LIMIT {
            return None;
        }
        let value: Value = serde_json::from_slice(&bytes).ok()?;
        if value["format"] != 1 {
            return None;
        }
        let rows = value["drafts"].as_array()?;
        let mut drafts = Drafts::new();
        for row in rows {
            let surface = row["surface"].as_str()?;
            let element = row["element"].as_str()?;
            let text = row["text"].as_str()?;
            if !identifier(surface) || !identifier(element) || text.len() > 65536 {
                return None;
            }
            let draft = Draft {
                text: text.into(),
                expected: row["expected"].as_u64()?,
                dirty: row["dirty"].as_bool()?,
                resolved: if row["resolved"].is_null() {
                    None
                } else {
                    Some(row["resolved"].as_u64()?)
                },
            };
            if drafts
                .insert((surface.into(), element.into()), draft)
                .is_some()
            {
                return None;
            }
        }
        Some(drafts)
    })();
    read.unwrap_or_default()
}
pub fn encode(drafts: &Drafts) -> Result<Vec<u8>, String> {
    let rows=drafts.iter().map(|((surface,element),d)|json!({"surface":surface,"element":element,"text":d.text,"expected":d.expected,"dirty":d.dirty,"resolved":d.resolved})).collect::<Vec<_>>();
    let bytes =
        serde_json::to_vec(&json!({"format":1,"drafts":rows})).map_err(|e| e.to_string())?;
    if bytes.len() as u64 > LIMIT {
        return Err(
            "Local draft recovery reached its 16 MiB limit; save or discard drafts before closing"
                .into(),
        );
    }
    Ok(bytes)
}
pub fn save(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let parent = path.parent().ok_or("Invalid local draft path")?;
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(parent)
        .map_err(|e| e.to_string())?;
    let temporary = parent.join(format!(".drafts-{}-{}", std::process::id(), super::nonce()));
    let result = (|| -> std::io::Result<()> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&temporary)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        fs::rename(&temporary, path)?;
        fs::File::open(parent)?.sync_all()
    })();
    let _ = fs::remove_file(temporary);
    result.map_err(|e| e.to_string())
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    #[test]
    fn private_recovery_roundtrip_preserves_revision_and_unicode() {
        let root = std::env::temp_dir().join(format!(
            "agentos-draft-cache-{}-{}",
            std::process::id(),
            super::super::nonce()
        ));
        let file = root.join("drafts.json");
        let mut drafts = Drafts::new();
        drafts.insert(
            ("surface-a".into(), "field".into()),
            Draft {
                text: "Unsaved λ 日本語".into(),
                expected: 7,
                dirty: true,
                resolved: None,
            },
        );
        save(&file, &encode(&drafts).unwrap()).unwrap();
        let loaded = load(&file);
        assert_eq!(
            loaded[&("surface-a".into(), "field".into())].text,
            "Unsaved λ 日本語"
        );
        assert_eq!(loaded.values().next().unwrap().expected, 7);
        assert_eq!(
            fs::metadata(&file).unwrap().permissions().mode() & 0o777,
            0o600
        );
        save(&file, &encode(&Drafts::new()).unwrap()).unwrap();
        assert!(load(&file).is_empty());
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn corrupt_or_oversized_fields_do_not_become_recovered_edits() {
        let root = std::env::temp_dir().join(format!(
            "agentos-draft-corrupt-{}-{}",
            std::process::id(),
            super::super::nonce()
        ));
        fs::create_dir(&root).unwrap();
        let file = root.join("drafts.json");
        fs::write(&file,br#"{"format":1,"drafts":[{"surface":"a","element":"field","text":"x","expected":-1,"dirty":true,"resolved":null}]}"#).unwrap();
        assert!(load(&file).is_empty());
        fs::write(&file, b"truncated").unwrap();
        assert!(load(&file).is_empty());
        fs::remove_dir_all(root).unwrap();
    }
}
