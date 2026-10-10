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
    db.execute_batch("CREATE TABLE IF NOT EXISTS presentation_host_surfaces(id TEXT PRIMARY KEY,activity TEXT NOT NULL,uid INTEGER NOT NULL,session TEXT NOT NULL,title TEXT NOT NULL,app_id TEXT NOT NULL,connected INTEGER NOT NULL,observed_at INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS presentation_host_revisions(id TEXT PRIMARY KEY,revision INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS presentation_renderers(surface TEXT PRIMARY KEY,uid INTEGER NOT NULL,session TEXT NOT NULL); CREATE TABLE IF NOT EXISTS presentation_host_peers(id TEXT PRIMARY KEY,client_uid INTEGER NOT NULL,client_session TEXT NOT NULL); CREATE TABLE IF NOT EXISTS presentation_host_reconnections(request_id TEXT PRIMARY KEY,uid INTEGER NOT NULL,body TEXT NOT NULL,result TEXT NOT NULL); CREATE TABLE IF NOT EXISTS presentation_host_aliases(id TEXT PRIMARY KEY,target TEXT NOT NULL); CREATE INDEX IF NOT EXISTS presentation_host_peer_lookup ON presentation_host_peers(client_uid,client_session);").map_err(|e|e.to_string())
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
    let proposed_id = v["surface_id"]
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
    let peer = match (v.get("client_uid"), v.get("client_session")) {
        (None, None) => None,
        (Some(uid), Some(session)) => {
            let uid = uid
                .as_u64()
                .filter(|uid| *uid <= u32::MAX as u64)
                .ok_or("invalid_document: Invalid client UID")? as u32;
            let session = session
                .as_str()
                .filter(|s| {
                    s.len() <= 128
                        && s.split_once(':').is_some_and(|(pid, start)| {
                            pid.parse::<u32>().is_ok() && start.parse::<u64>().is_ok()
                        })
                })
                .ok_or("invalid_document: Invalid authenticated client session")?;
            Some((uid, session))
        }
        _ => {
            return Err("invalid_document: Client UID and session must be supplied together".into())
        }
    };
    let tx = db.transaction().map_err(|e| e.to_string())?;
    let valid:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM activities WHERE CAST(id AS TEXT)=? AND id NOT IN (SELECT activity_id FROM removed_activities))",[activity],|r|r.get(0)).map_err(|e|e.to_string())?;
    if !valid {
        return Err("missing_reference: Activity unavailable".into());
    }
    let alias: Option<String> = tx
        .query_row(
            "SELECT target FROM presentation_host_aliases WHERE id=?",
            [proposed_id],
            |r| r.get(0),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    let proposed_id = alias.as_deref().unwrap_or(proposed_id);
    let mut recovered = None;
    let exists: bool = tx
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM presentation_host_surfaces WHERE id=?)",
            [proposed_id],
            |r| r.get(0),
        )
        .map_err(|e| e.to_string())?;
    if !exists && connected {
        if let Some((uid, session)) = peer {
            // A live authenticated application process may reconnect after its compositor dies.
            // Never guess from an app-id/title or pick one of several windows from the same process.
            let mut query=tx.prepare("SELECT h.id,h.session,h.uid FROM presentation_host_surfaces h JOIN presentation_host_peers p USING(id) WHERE p.client_uid=? AND p.client_session=? AND h.activity=? AND h.app_id=? ORDER BY h.id LIMIT 2").map_err(|e|e.to_string())?;
            let candidates = query
                .query_map(params![uid, session, activity, app_id], |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, String>(1)?,
                        r.get::<_, u32>(2)?,
                    ))
                })
                .map_err(|e| e.to_string())?
                .collect::<std::result::Result<Vec<_>, _>>()
                .map_err(|e| e.to_string())?;
            if candidates.len() == 1 {
                let (identity, old_host, host_uid) = &candidates[0];
                if *host_uid == who.uid && old_host != &who.session && !alive(old_host) {
                    recovered = Some(identity.clone());
                }
            }
        }
    }
    let id = recovered.as_deref().unwrap_or(proposed_id);
    let previous: Option<(u32, String, String)> = tx
        .query_row(
            "SELECT uid,session,activity FROM presentation_host_surfaces WHERE id=?",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    if let Some((uid, session, owned)) = previous {
        if uid != who.uid || (session != who.session && recovered.is_none()) || owned != activity {
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
    if let Some((uid, session)) = peer {
        let previous: Option<(u32, String)> = tx
            .query_row(
                "SELECT client_uid,client_session FROM presentation_host_peers WHERE id=?",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()
            .map_err(|e| e.to_string())?;
        if previous
            .as_ref()
            .is_some_and(|(old_uid, old_session)| *old_uid != uid || old_session != session)
        {
            return Err("unauthorized: A conventional identity cannot change its authenticated client process".into());
        }
        tx.execute(
            "INSERT INTO presentation_host_peers VALUES(?,?,?) ON CONFLICT(id) DO NOTHING",
            params![id, uid, session],
        )
        .map_err(|e| e.to_string())?;
    }
    let previous: Option<(String, String, bool)> = tx
        .query_row(
            "SELECT title,app_id,connected FROM presentation_host_surfaces WHERE id=?",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    let changed = previous
        .as_ref()
        .is_none_or(|(old_title, old_app, old_connected)| {
            old_title != title
                || old_app != app_id
                || *old_connected != connected
                || recovered.is_some()
        });
    tx.execute("INSERT INTO presentation_host_revisions VALUES(?,1) ON CONFLICT(id) DO UPDATE SET revision=revision+?",params![id,changed as i64]).map_err(|e|e.to_string())?;
    tx.execute("INSERT INTO presentation_host_surfaces(id,activity,uid,session,title,app_id,connected,observed_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET session=excluded.session,title=excluded.title,app_id=excluded.app_id,connected=excluded.connected,observed_at=excluded.observed_at",params![id,activity,who.uid,who.session,title,app_id,connected,crate::now()]).map_err(|e|e.to_string())?;
    tx.commit().map_err(|e| e.to_string())?;
    Ok(json!({"surface_id":id,"connected":connected,"reconciled":recovered.is_some()}))
}
/// Explicit human association of a returning process with a missing logical window.
/// Layout removal and metadata association share one guarded SQLite transaction.
pub fn reconnect(db: &mut Connection, v: &Value, who: &Principal) -> Result<Value> {
    if who.uid != 0 && who.uid < 1000 {
        return Err("unauthorized: Only a human may associate returning applications".into());
    }
    let old = v["missing_surface"]
        .as_str()
        .filter(|s| ident(s))
        .ok_or("invalid_document: Missing window identity")?;
    let new = v["live_surface"]
        .as_str()
        .filter(|s| ident(s) && *s != old)
        .ok_or("invalid_document: Returning window identity required")?;
    let tx = db.transaction().map_err(|e| e.to_string())?;
    let request_id = v["request_id"]
        .as_str()
        .filter(|s| ident(s))
        .ok_or("invalid_document: Reconnection request identity required")?;
    let previous: Option<(u32, String, String)> = tx
        .query_row(
            "SELECT uid,body,result FROM presentation_host_reconnections WHERE request_id=?",
            [request_id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    if let Some((uid, body, result)) = previous {
        if uid != who.uid || body != v.to_string() {
            return Err("invalid_document: Reconnection request identity was already used".into());
        }
        return serde_json::from_str(&result).map_err(|e| e.to_string());
    }
    let row = |id: &str| -> Result<(String, u32, String, bool, i64)> {
        tx.query_row("SELECT h.activity,h.uid,h.session,h.connected,r.revision FROM presentation_host_surfaces h JOIN presentation_host_revisions r USING(id) WHERE h.id=?",[id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).map_err(|_|"missing_reference: Conventional window unavailable".into())
    };
    let (activity, owner, session, connected, revision) = row(old)?;
    let (next_activity, next_owner, next_session, next_connected, next_revision) = row(new)?;
    if (who.uid != 0 && who.uid != owner) || owner != next_owner || activity != next_activity {
        return Err("unauthorized: Returning and missing windows must belong to the same human and activity".into());
    }
    if v["missing_revision"].as_i64() != Some(revision)
        || v["live_revision"].as_i64() != Some(next_revision)
    {
        return Err("stale_revision: Window metadata changed; review the association again".into());
    }
    if (connected && alive(&session)) || !next_connected || !alive(&next_session) {
        return Err(
            "invalid_document: Select a missing window and an available returning window".into(),
        );
    }
    let alias: bool = tx
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM presentation_host_aliases WHERE id=? OR id=?)",
            params![old, new],
            |r| r.get(0),
        )
        .map_err(|e| e.to_string())?;
    if alias {
        return Err("invalid_document: Use the current logical window identities".into());
    }
    let active:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM activities WHERE CAST(id AS TEXT)=? AND id NOT IN (SELECT activity_id FROM removed_activities))",[&activity],|r|r.get(0)).map_err(|e|e.to_string())?;
    if !active {
        return Err("missing_reference: Activity unavailable".into());
    }
    let layout = crate::presentation::reconnect_placement(&tx, v, who, new, &activity)?;
    let peer: (u32, String) = tx
        .query_row(
            "SELECT client_uid,client_session FROM presentation_host_peers WHERE id=?",
            [new],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .map_err(|_| "unauthorized: Returning window lacks an authenticated client identity")?;
    tx.execute("UPDATE presentation_host_surfaces SET session=?,title=(SELECT title FROM presentation_host_surfaces WHERE id=?),app_id=(SELECT app_id FROM presentation_host_surfaces WHERE id=?),connected=1,observed_at=? WHERE id=?",params![next_session,new,new,crate::now(),old]).map_err(|e|e.to_string())?;
    tx.execute("INSERT INTO presentation_host_peers VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET client_uid=excluded.client_uid,client_session=excluded.client_session",params![old,peer.0,peer.1]).map_err(|e|e.to_string())?;
    tx.execute(
        "UPDATE presentation_host_surfaces SET connected=0 WHERE id=?",
        [new],
    )
    .map_err(|e| e.to_string())?;
    tx.execute(
        "UPDATE presentation_host_revisions SET revision=revision+1 WHERE id=? OR id=?",
        params![old, new],
    )
    .map_err(|e| e.to_string())?;
    tx.execute(
        "INSERT INTO presentation_host_aliases VALUES(?,?)",
        params![new, old],
    )
    .map_err(|e| e.to_string())?;
    let result = json!({"surface_id":old,"previous_live_surface":new,"layout_receipt":layout,"status":"Returning application associated with its saved view"});
    tx.execute(
        "INSERT INTO presentation_host_reconnections VALUES(?,?,?,?)",
        params![request_id, who.uid, v.to_string(), result.to_string()],
    )
    .map_err(|e| e.to_string())?;
    tx.commit().map_err(|e| e.to_string())?;
    Ok(result)
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
pub fn source(db: &Connection, id: &str) -> Result<Option<Value>> {
    let row:Option<(String,String,String,bool,String,i64,i64)>=db.query_row("SELECT h.activity,h.title,h.app_id,h.connected,h.session,h.observed_at,COALESCE(r.revision,0) FROM presentation_host_surfaces h LEFT JOIN presentation_host_revisions r USING(id) WHERE h.id=?",[id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?,r.get(6)?))).optional().map_err(|e|e.to_string())?;
    Ok(row.map(|(activity,title,app,connected,session,observed,revision)| {
        let availability=if connected && alive(&session) {"available"} else {"unavailable"};
        json!({"source":format!("window:{id}"),"activity_id":activity,"source_revision":revision,"observed_at":observed,"availability":availability,"values":{"title":title,"app_id":app,"availability":availability}})
    }))
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
            s.rsplit_once(')').and_then(|(_, tail)| {
                let fields = tail.split_whitespace().collect::<Vec<_>>();
                if matches!(fields.first(), Some(&"Z") | Some(&"X")) {
                    None
                } else {
                    fields.get(19).map(|s| s.to_string())
                }
            })
        })
        .map(|observed| observed == start)
        .unwrap_or(false)
}
pub fn snapshot(db: &Connection, referenced: &BTreeSet<String>) -> Result<Value> {
    snapshot_for(db, referenced, None)
}
pub fn snapshot_for(
    db: &Connection,
    referenced: &BTreeSet<String>,
    filter: Option<&str>,
) -> Result<Value> {
    let mut query=db.prepare("SELECT h.id,h.activity,h.session,h.title,h.app_id,h.connected,h.observed_at,COALESCE(r.revision,0) FROM presentation_host_surfaces h LEFT JOIN presentation_host_revisions r USING(id) ORDER BY h.id").map_err(|e|e.to_string())?;
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
                r.get::<_, i64>(7)?,
            ))
        })
        .map_err(|e| e.to_string())?;
    let mut result = BTreeMap::new();
    for row in rows {
        let (id, activity, session, title, app_id, connected, observed_at, revision) =
            row.map_err(|e| e.to_string())?;
        if filter.is_some_and(|wanted| wanted != activity) {
            continue;
        }
        let available = connected && alive(&session);
        if !available && !referenced.contains(&id) {
            continue;
        }
        result.insert(id,json!({"activity_id":activity,"title":title,"app_id":app_id,"availability":if available{"available"}else{"unavailable"},"observed_at":observed_at,"source_revision":revision}));
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
    renderers_for(db, None)
}
pub fn renderers_for(db: &Connection, activity: Option<&str>) -> Result<Value> {
    let mut q = db.prepare("SELECT surface,uid,session FROM presentation_renderers WHERE surface IN (SELECT id FROM presentation_documents WHERE ?1 IS NULL OR json_extract(body,'$.activity_id')=?1)").map_err(|e|e.to_string())?;
    let rows = q
        .query_map([activity], |r| {
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
