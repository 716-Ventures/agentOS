//! Observed broker state is published by its root service, never by presentation patches.
use crate::presentation::Principal;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
type Result<T> = std::result::Result<T, String>;
fn error(code: &str, detail: &str) -> String {
    json!({"code":code,"detail":detail}).to_string()
}
fn storage(e: impl std::fmt::Display) -> String {
    error("storage_error", &e.to_string())
}
fn valid(source: &str) -> bool {
    source
        .strip_prefix("broker:")
        .or_else(|| source.strip_prefix("file:"))
        .map(|id| {
            id.len() == 32
                && id
                    .bytes()
                    .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        })
        .unwrap_or(false)
}
pub fn init(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS presentation_external_sources(source TEXT PRIMARY KEY,activity TEXT NOT NULL,revision INTEGER NOT NULL,body TEXT NOT NULL,session TEXT NOT NULL,observed INTEGER NOT NULL);CREATE TABLE IF NOT EXISTS presentation_source_owners(session TEXT PRIMARY KEY,observed INTEGER NOT NULL);").map_err(storage)
}
pub fn activity(db: &Connection, source: &str) -> Result<Option<String>> {
    db.query_row(
        "SELECT activity FROM presentation_external_sources WHERE source=?",
        [source],
        |r| r.get(0),
    )
    .optional()
    .map_err(storage)
}
fn observed(db: &Connection, source: &str) -> Result<Option<Value>> {
    let row:Option<(String,i64,String,String,i64,i64)>=db.query_row("SELECT s.activity,s.revision,s.body,s.session,s.observed,COALESCE(o.observed,s.observed) FROM presentation_external_sources s LEFT JOIN presentation_source_owners o USING(session) WHERE source=?",[source],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?))).optional().map_err(storage)?;
    row.map(|(activity,revision,body,session,at,heartbeat)| {
        let mut body:Value=serde_json::from_str(&body).map_err(storage)?;
        let file=source.starts_with("file:");
        if file {
            body["size_text"]=json!(body["size_bytes"].as_u64().map(|n|format!("{n} bytes")).unwrap_or_else(||"Unavailable".into()));
            body["mode_text"]=json!(body["mode"].as_u64().map(|n|format!("{n:04o}")).unwrap_or_else(||"Unavailable".into()));
            body["modified_text"]=json!(body["modified_at"].as_f64().map(|n|format!("{n} Unix seconds")).unwrap_or_else(||"Unavailable".into()));
        }
        let available=(!file || body["kind"]!="unavailable") && crate::presentation_hosts::alive(&session) && heartbeat>=crate::now()-15;
        Ok(json!({"source":source,"activity_id":activity,"source_revision":revision,"observed_at":if file {body["measured_at"].clone()} else {json!(at)},"availability":if available {"available"} else {"unavailable"},"values":body}))
    }).transpose()
}
pub fn binding(db: &Connection, source: &str, activity: &str, path: &str) -> Result<Value> {
    let mut value = (if let Some(id) = source.strip_prefix("window:") {
        crate::presentation_hosts::source(db, id)?
    } else {
        observed(db, source)?
    })
    .filter(|v| v["activity_id"] == activity)
    .ok_or_else(|| error("missing_reference", "Source unavailable in this activity"))?;
    value["value"] = value["values"]
        .pointer(path)
        .cloned()
        .unwrap_or(Value::Null);
    value.as_object_mut().unwrap().remove("values");
    Ok(value)
}
pub fn handle(db: &mut Connection, value: &Value, who: &Principal) -> Result<Value> {
    match value["op"].as_str().unwrap_or("") {
        "source.publish" => {
            if who.uid != 0 {
                return Err(error(
                    "unauthorized",
                    "Only the broker service can publish observed domain state",
                ));
            }
            let source = value["source"]
                .as_str()
                .filter(|s| valid(s))
                .ok_or_else(|| error("invalid_event", "Invalid broker source identity"))?;
            let activity = value["activity_id"]
                .as_str()
                .filter(|s| s.parse::<u32>().ok().filter(|n| *n > 0).is_some())
                .ok_or_else(|| error("invalid_event", "Activity required"))?;
            let revision = value["source_revision"]
                .as_i64()
                .filter(|r| *r >= 0)
                .ok_or_else(|| error("invalid_event", "Nonnegative source revision required"))?;
            let values = value["values"]
                .as_object()
                .ok_or_else(|| error("invalid_event", "Observed values required"))?;
            let file = source.starts_with("file:");
            let bad = if file {
                values.len() != 6
                    || values.iter().any(|(key, v)| match key.as_str() {
                        "path" => !v.as_str().is_some_and(|s| {
                            s.starts_with('/') && s.len() <= 4096 && !s.contains('\0')
                        }),
                        "kind" => !v.as_str().is_some_and(|s| {
                            [
                                "file",
                                "directory",
                                "symlink",
                                "missing",
                                "other",
                                "unavailable",
                            ]
                            .contains(&s)
                        }),
                        "size_bytes" => !v.is_null() && !v.as_i64().is_some_and(|n| n >= 0),
                        "mode" => !v.is_null() && !v.as_u64().is_some_and(|n| n <= 0o7777),
                        "modified_at" => !v.is_null() && !v.as_f64().is_some_and(f64::is_finite),
                        "measured_at" => !v.as_f64().is_some_and(|n| n.is_finite() && n >= 0.),
                        _ => true,
                    })
            } else {
                values.len() != 5
                    || values.iter().any(|(key, v)| match key.as_str() {
                        "status" => !v
                            .as_str()
                            .map(|s| !s.is_empty() && s.len() <= 128)
                            .unwrap_or(false),
                        "error" => {
                            !v.is_null() && !v.as_str().map(|s| s.len() <= 16384).unwrap_or(false)
                        }
                        "exit_code" => !v.is_null() && v.as_i64().is_none(),
                        "created_at" | "finished_at" => {
                            !v.is_null()
                                && !v
                                    .as_f64()
                                    .map(|n| n.is_finite() && n >= 0.0)
                                    .unwrap_or(false)
                        }
                        _ => true,
                    })
            };
            if bad {
                return Err(error(
                    "invalid_event",
                    "Unsupported or invalid observed field",
                ));
            }
            let tx = db.transaction().map_err(storage)?;
            let known: bool = tx
                .query_row(
                    "SELECT EXISTS(SELECT 1 FROM activities WHERE CAST(id AS TEXT)=?)",
                    [activity],
                    |r| r.get(0),
                )
                .map_err(storage)?;
            if !known {
                return Err(error("missing_reference", "Activity is unavailable"));
            }
            let previous:Option<(String,i64,String,String)>=tx.query_row("SELECT activity,revision,body,session FROM presentation_external_sources WHERE source=?",[source],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?))).optional().map_err(storage)?;
            let body = json!(values).to_string();
            if let Some((owned, old, raw, session)) = previous {
                if owned != activity
                    || (file
                        && serde_json::from_str::<Value>(&raw).map_err(storage)?["path"]
                            != values["path"])
                    || (session != who.session && crate::presentation_hosts::alive(&session))
                {
                    return Err(error("unauthorized", "Source ownership cannot be rebound"));
                }
                if revision < old || (revision == old && raw != body) {
                    return Err(error("stale_revision", "Observed source revision changed"));
                }
            }
            tx.execute("INSERT INTO presentation_external_sources VALUES(?,?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET revision=excluded.revision,body=excluded.body,session=excluded.session,observed=excluded.observed",params![source,activity,revision,body,who.session,crate::now()]).map_err(storage)?;
            tx.execute("INSERT INTO presentation_source_owners VALUES(?,?) ON CONFLICT(session) DO UPDATE SET observed=excluded.observed",params![who.session,crate::now()]).map_err(storage)?;
            tx.commit().map_err(storage)?;
            Ok(json!({"source":source,"source_revision":revision}))
        }
        "source.heartbeat" => {
            if who.uid != 0 {
                return Err(error(
                    "unauthorized",
                    "Only the broker service owns source availability",
                ));
            }
            db.execute("INSERT INTO presentation_source_owners VALUES(?,?) ON CONFLICT(session) DO UPDATE SET observed=excluded.observed",params![who.session,crate::now()]).map_err(storage)?;
            Ok(json!({"observed_at":crate::now()}))
        }
        "source.list" => {
            let activity = value["activity_id"]
                .as_str()
                .ok_or_else(|| error("invalid_event", "Activity required"))?;
            let after = value["after"].as_str().unwrap_or("");
            let limit = value["limit"].as_u64().unwrap_or(64).clamp(1, 128);
            let mut query=db.prepare("SELECT source FROM (SELECT source,activity FROM presentation_external_sources UNION ALL SELECT 'window:'||id AS source,activity FROM presentation_host_surfaces UNION ALL SELECT 'job:'||id AS source,CAST(activity_id AS TEXT) AS activity FROM jobs) WHERE activity=? AND source>? ORDER BY source LIMIT ?").map_err(storage)?;
            let sources = query
                .query_map(params![activity, after, limit + 1], |r| {
                    r.get::<_, String>(0)
                })
                .map_err(storage)?
                .collect::<std::result::Result<Vec<_>, _>>()
                .map_err(storage)?;
            let more = sources.len() > limit as usize;
            let mut rows = Vec::new();
            for source in sources.iter().take(limit as usize) {
                let value = if let Some(id) = source.strip_prefix("window:") {
                    crate::presentation_hosts::source(db, id)?
                } else if source.starts_with("job:") {
                    let revision: i64 = db
                        .query_row("SELECT value FROM meta WHERE key='revision'", [], |r| {
                            r.get(0)
                        })
                        .map_err(storage)?;
                    Some(
                        json!({"source":source,"activity_id":activity,"source_revision":revision,"observed_at":crate::now(),"availability":"available","values":{}}),
                    )
                } else {
                    observed(db, source)?
                };
                if let Some(mut row) = value {
                    row.as_object_mut().unwrap().remove("values");
                    row["paths"] = if source.starts_with("file:") {
                        json!([
                            "/path",
                            "/kind",
                            "/size_bytes",
                            "/modified_at",
                            "/mode",
                            "/measured_at",
                            "/size_text",
                            "/modified_text",
                            "/mode_text"
                        ])
                    } else if source.starts_with("window:") {
                        json!(["/title", "/app_id", "/availability"])
                    } else {
                        json!([
                            "/status",
                            "/error",
                            "/exit_code",
                            "/created_at",
                            "/finished_at"
                        ])
                    };
                    rows.push(row)
                }
            }
            Ok(
                json!({"sources":rows,"has_more":more,"next":sources.get((limit as usize).min(sources.len()).saturating_sub(1))}),
            )
        }
        _ => Err(error("unsupported_operation", "Unknown source operation")),
    }
}
