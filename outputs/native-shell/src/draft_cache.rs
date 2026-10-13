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
fn decode(bytes: &[u8]) -> Option<Drafts> {
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
            acknowledged: None,
        };
        if drafts
            .insert((surface.into(), element.into()), draft)
            .is_some()
        {
            return None;
        }
    }
    Some(drafts)
}
fn read(path: &Path) -> std::io::Result<Option<Drafts>> {
    let file = fs::File::open(path)?;
    let mut bytes = Vec::new();
    file.take(LIMIT + 1).read_to_end(&mut bytes)?;
    Ok(decode(&bytes))
}
fn preserve_invalid(path: &Path) -> std::io::Result<()> {
    let backup = path.with_file_name(format!(
        "native-drafts.corrupt-{}-{}.json",
        std::process::id(),
        super::nonce()
    ));
    fs::rename(path, backup)?;
    fs::File::open(path.parent().unwrap())?.sync_all()
}
pub fn load(path: &Path) -> Drafts {
    match read(path) {
        Ok(Some(drafts)) => drafts,
        Ok(None) => {
            let _ = preserve_invalid(path);
            Drafts::new()
        }
        Err(_) => Drafts::new(),
    }
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
/// Compare durable fields before allocating or serializing recovery JSON.
/// A failed write never advances the checkpoint, so the next tick retries it.
#[derive(Default)]
pub struct Checkpoint {
    saved: Option<Drafts>,
}
impl Checkpoint {
    pub fn persist(&mut self, path: &Path, drafts: &Drafts) -> Result<bool, String> {
        let unchanged = self.saved.as_ref().is_some_and(|saved| {
            saved.len() == drafts.len()
                && saved.iter().zip(drafts).all(|((key, a), (next, b))| {
                    key == next
                        && a.text == b.text
                        && a.expected == b.expected
                        && a.dirty == b.dirty
                        && a.resolved == b.resolved
                })
        });
        if unchanged {
            return Ok(false);
        }
        save(path, &encode(drafts)?)?;
        self.saved = Some(
            drafts
                .iter()
                .map(|(key, draft)| {
                    (
                        key.clone(),
                        Draft {
                            text: draft.text.clone(),
                            expected: draft.expected,
                            dirty: draft.dirty,
                            resolved: draft.resolved,
                            acknowledged: None,
                        },
                    )
                })
                .collect(),
        );
        Ok(true)
    }
}

pub fn save(path: &Path, bytes: &[u8]) -> Result<(), String> {
    if decode(bytes).is_none() {
        return Err("Invalid local draft recovery payload".into());
    }
    if path.exists() {
        // An unreadable or invalid previous recovery file must survive replacement.
        if read(path).map_err(|e| e.to_string())?.is_none() {
            preserve_invalid(path).map_err(|e| e.to_string())?;
        }
    }
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
                acknowledged: Some((3, "Previously saved".into())),
            },
        );
        save(&file, &encode(&drafts).unwrap()).unwrap();
        let loaded = load(&file);
        assert_eq!(
            loaded[&("surface-a".into(), "field".into())].text,
            "Unsaved λ 日本語"
        );
        assert_eq!(loaded.values().next().unwrap().expected, 7);
        assert!(
            loaded.values().next().unwrap().acknowledged.is_none(),
            "Recovery files must not grant in-process commit authority"
        );
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
        let backups = fs::read_dir(&root)
            .unwrap()
            .map(|e| e.unwrap().path())
            .collect::<Vec<_>>();
        assert_eq!(backups.len(), 2);
        assert!(backups.iter().any(|p| fs::read(p).unwrap() == b"truncated"));
        save(&file, &encode(&Drafts::new()).unwrap()).unwrap();
        assert_eq!(fs::read_dir(&root).unwrap().count(), 3);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn unchanged_checkpoint_preserves_file_and_failed_changes_retry() {
        use std::os::unix::fs::MetadataExt;
        let root = std::env::temp_dir().join(format!(
            "agentos-draft-checkpoint-{}-{}",
            std::process::id(),
            super::super::nonce()
        ));
        let path = root.join("drafts.json");
        let key = ("notes".into(), "editor".into());
        let mut drafts = Drafts::from([(
            key.clone(),
            Draft {
                text: "Unsaved λ 日本語".into(),
                expected: 7,
                dirty: true,
                resolved: None,
                acknowledged: None,
            },
        )]);
        let mut checkpoint = Checkpoint::default();
        assert!(checkpoint.persist(&path, &drafts).unwrap());
        let inode = fs::metadata(&path).unwrap().ino();
        drafts.get_mut(&key).unwrap().acknowledged = Some((8, "In-process authority only".into()));
        assert!(!checkpoint.persist(&path, &drafts).unwrap());
        assert_eq!(fs::metadata(&path).unwrap().ino(), inode);
        assert!(load(&path)[&key].acknowledged.is_none());
        // Each durable change must reach disk, including metadata-only changes.
        for field in 0..4 {
            let draft = drafts.get_mut(&key).unwrap();
            match field {
                0 => draft.text.push_str(" changed"),
                1 => draft.expected += 1,
                2 => draft.dirty = false,
                _ => draft.resolved = Some(9),
            }
            assert!(checkpoint.persist(&path, &drafts).unwrap());
            assert_eq!(encode(&load(&path)).unwrap(), encode(&drafts).unwrap());
            assert!(!checkpoint.persist(&path, &drafts).unwrap());
        }
        fs::remove_file(&path).unwrap();
        fs::create_dir(&path).unwrap();
        drafts.get_mut(&key).unwrap().text = "Retry this change".into();
        assert!(checkpoint.persist(&path, &drafts).is_err());
        fs::remove_dir(&path).unwrap();
        assert!(checkpoint.persist(&path, &drafts).unwrap());
        assert_eq!(load(&path)[&key].text, "Retry this change");
        drafts.clear();
        assert!(checkpoint.persist(&path, &drafts).unwrap());
        assert!(load(&path).is_empty());
        fs::remove_dir_all(root).unwrap();
    }
}
