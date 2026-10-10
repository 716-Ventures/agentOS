//! Host-observed conventional surfaces. Models cannot advertise windows or outputs.
use crate::presentation::Principal;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
type Result<T> = std::result::Result<T, String>;
pub fn trusted(who: &Principal) -> bool {
    who.uid == 0
        || std::env::var("AGENT_OS_COMPOSITOR_UID")
            .ok()
            .and_then(|s| s.parse::<u32>().ok())
            .filter(|uid| *uid >= 1000)
            .map(|uid| uid == who.uid)
            .unwrap_or(false)
}
pub fn init(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS presentation_host_surfaces(id TEXT PRIMARY KEY,activity TEXT NOT NULL,uid INTEGER NOT NULL,session TEXT NOT NULL,title TEXT NOT NULL,app_id TEXT NOT NULL,connected INTEGER NOT NULL,observed_at INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS presentation_renderers(surface TEXT PRIMARY KEY,uid INTEGER NOT NULL,session TEXT NOT NULL);").map_err(|e|e.to_string())
}
fn ident(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
}
pub fn register(db: &mut Connection, v: &Value, who: &Principal) -> Result<Value> {
    if !trusted(who) {
        return Err(
            "unauthorized: Only the configured compositor host can register conventional surfaces"
                .into(),
        );
    }
    let id = v["surface_id"]
        .as_str()
        .filter(|s| ident(s))
        .ok_or("invalid_document: Invalid host surface identity")?;
    let activity = v["activity_id"]
        .as_str()
        .ok_or("invalid_document: Missing activity")?;
    let connected = v["connected"]
        .as_bool()
        .ok_or("invalid_document: Missing connection state")?;
    let title = v["title"]
        .as_str()
        .filter(|s| s.len() <= 1024)
        .ok_or("resource_limit: Invalid title")?;
    let app_id = v["app_id"]
        .as_str()
        .filter(|s| s.len() <= 256)
        .ok_or("resource_limit: Invalid application identity")?;
    let tx = db.transaction().map_err(|e| e.to_string())?;
    let valid:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM activities WHERE CAST(id AS TEXT)=? AND id NOT IN (SELECT activity_id FROM removed_activities))",[activity],|r|r.get(0)).map_err(|e|e.to_string())?;
    if !valid {
        return Err("missing_reference: Activity unavailable".into());
    }
    let previous: Option<(u32, String, String)> = tx
        .query_row(
            "SELECT uid,session,activity FROM presentation_host_surfaces WHERE id=?",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    if let Some((uid, session, owned)) = previous {
        if uid != who.uid || session != who.session || owned != activity {
            return Err("unauthorized: Host surface identity cannot be rebound to another session or activity".into());
        }
    } else {
        // A crashed compositor cannot publish disconnects. Retire only the
        // connection flag of dead process identities, preserving restore metadata.
        let stale = {
            let mut q = tx
                .prepare(
                    "SELECT DISTINCT session FROM presentation_host_surfaces WHERE connected=1",
                )
                .map_err(|e| e.to_string())?;
            let rows = q
                .query_map([], |r| r.get::<_, String>(0))
                .map_err(|e| e.to_string())?;
            rows.collect::<std::result::Result<Vec<_>, _>>()
                .map_err(|e| e.to_string())?
        };
        for session in stale.into_iter().filter(|s| !alive(s)) {
            tx.execute(
                "UPDATE presentation_host_surfaces SET connected=0 WHERE session=?",
                [session],
            )
            .map_err(|e| e.to_string())?;
        }
        let count: i64 = tx
            .query_row(
                "SELECT COUNT(*) FROM presentation_host_surfaces WHERE connected=1",
                [],
                |r| r.get(0),
            )
            .map_err(|e| e.to_string())?;
        if count >= 1024 {
            return Err("resource_limit: Too many connected conventional surfaces".into());
        }
        tx.execute(
            "INSERT INTO presentation_identities(id,revision) VALUES(?,0)",
            [id],
        )
        .map_err(|_| "invalid_document: Surface identity is already used")?;
    }
    tx.execute("INSERT INTO presentation_host_surfaces(id,activity,uid,session,title,app_id,connected,observed_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,app_id=excluded.app_id,connected=excluded.connected,observed_at=excluded.observed_at",params![id,activity,who.uid,who.session,title,app_id,connected,crate::now()]).map_err(|e|e.to_string())?;
    tx.commit().map_err(|e| e.to_string())?;
    Ok(json!({"surface_id":id,"connected":connected}))
}
pub fn activity(db: &Connection, id: &str) -> Result<Option<String>> {
    db.query_row(
        "SELECT activity FROM presentation_host_surfaces WHERE id=?",
        [id],
        |r| r.get(0),
    )
    .optional()
    .map_err(|e| e.to_string())
}
pub fn alive(session: &str) -> bool {
    let Some((pid, start)) = session.split_once(':') else {
        return false;
    };
    if pid.parse::<u32>().is_err() {
        return false;
    }
    std::fs::read_to_string(format!("/proc/{pid}/stat"))
        .ok()
        .and_then(|s| {
            s.rsplit_once(')')
                .and_then(|(_, tail)| tail.split_whitespace().nth(19))
                .map(String::from)
        })
        .map(|observed| observed == start)
        .unwrap_or(false)
}
pub fn snapshot(db: &Connection, referenced: &BTreeSet<String>) -> Result<Value> {
    let mut query=db.prepare("SELECT id,activity,session,title,app_id,connected,observed_at FROM presentation_host_surfaces ORDER BY id").map_err(|e|e.to_string())?;
    let rows = query
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, String>(4)?,
                r.get::<_, bool>(5)?,
                r.get::<_, i64>(6)?,
            ))
        })
        .map_err(|e| e.to_string())?;
    let mut result = BTreeMap::new();
    for row in rows {
        let (id, activity, session, title, app_id, connected, observed_at) =
            row.map_err(|e| e.to_string())?;
        let available = connected && alive(&session);
        if !available && !referenced.contains(&id) {
            continue;
        }
        result.insert(id,json!({"activity_id":activity,"title":title,"app_id":app_id,"availability":if available{"available"}else{"unavailable"},"observed_at":observed_at}));
    }
    Ok(json!(result))
}

/// Bind a native surface to the authenticated renderer process, never to an app-id claim.
pub fn renderer(db: &Connection, v: &Value, who: &Principal) -> Result<Value> {
    if who.uid != 0 && who.uid < 1000 {
        return Err("unauthorized: Native renderer registration requires a user session".into());
    }
    let id = v["surface_id"]
        .as_str()
        .ok_or("missing_reference: Surface required")?;
    let body: Option<String> = db
        .query_row(
            "SELECT body FROM presentation_documents WHERE id=?",
            [id],
            |r| r.get(0),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    let document: Value =
        serde_json::from_str(&body.ok_or("missing_reference: Surface unavailable")?)
            .map_err(|e| e.to_string())?;
    if document["surface_id"].as_str() != Some(id) {
        return Err("missing_reference: Native surface required".into());
    }
    let previous: Option<(u32, String)> = db
        .query_row(
            "SELECT uid,session FROM presentation_renderers WHERE surface=?",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    if let Some((uid, session)) = previous {
        if (uid != who.uid || session != who.session) && alive(&session) {
            return Err("interaction_conflict: Surface already has a live renderer".into());
        }
    }
    db.execute("INSERT INTO presentation_renderers VALUES(?,?,?) ON CONFLICT(surface) DO UPDATE SET uid=excluded.uid,session=excluded.session",params![id,who.uid,who.session]).map_err(|e|e.to_string())?;
    Ok(json!({"surface_id":id}))
}
pub fn renderers(db: &Connection) -> Result<Value> {
    let mut q = db.prepare("SELECT surface,uid,session FROM presentation_renderers WHERE surface IN (SELECT id FROM presentation_documents)").map_err(|e|e.to_string())?;
    let rows = q
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, u32>(1)?,
                r.get::<_, String>(2)?,
            ))
        })
        .map_err(|e| e.to_string())?;
    let mut result = BTreeMap::new();
    for row in rows {
        let (id, uid, session) = row.map_err(|e| e.to_string())?;
        if alive(&session) {
            result.insert(id, json!({"uid":uid,"session":session}));
        }
    }
    Ok(json!(result))
}
