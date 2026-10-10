//! Live output observations are distinct from durable preferred workspace geometry.
use crate::presentation::Principal;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
type Result<T> = std::result::Result<T, String>;
fn error(kind: &str, detail: impl std::fmt::Display) -> String {
    json!({"code":kind,"detail":detail.to_string()}).to_string()
}
fn storage(e: impl std::fmt::Display) -> String {
    error("storage_error", e)
}
pub fn init(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS presentation_output_observations(id TEXT PRIMARY KEY,session TEXT NOT NULL,body TEXT NOT NULL,observed INTEGER NOT NULL)").map_err(storage)
}
fn number(
    value: &Value,
    key: &str,
    default: Option<f64>,
    minimum: f64,
    maximum: f64,
) -> Result<f64> {
    value
        .get(key)
        .map(Value::as_f64)
        .unwrap_or(default)
        .filter(|n| n.is_finite() && (minimum..=maximum).contains(n))
        .ok_or_else(|| error("invalid_output", format!("Invalid {key}")))
}
pub fn list(db: &Connection, value: &Value) -> Result<Value> {
    let after = value["after_id"].as_str().unwrap_or("");
    let connected_only = value
        .get("connected_only")
        .map(Value::as_bool)
        .unwrap_or(Some(false))
        .ok_or_else(|| error("invalid_output", "Connection filter must be boolean"))?;
    let limit = value
        .get("limit")
        .map(|v| v.as_u64().filter(|n| (1..=64).contains(n)))
        .unwrap_or(Some(16))
        .ok_or_else(|| error("invalid_output", "Page size must be between 1 and 64"))?;
    let mut q=db.prepare("SELECT o.id,o.width,o.height,o.connected,s.session,s.body,s.observed FROM presentation_outputs o LEFT JOIN presentation_output_observations s USING(id) WHERE o.id>?1 AND (?3=0 OR o.connected=1) ORDER BY o.id LIMIT ?2").map_err(storage)?;
    let mut rows = q
        .query_map(params![after, limit + 1, connected_only], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, f64>(1)?,
                r.get::<_, f64>(2)?,
                r.get::<_, bool>(3)?,
                r.get::<_, Option<String>>(4)?,
                r.get::<_, Option<String>>(5)?,
                r.get::<_, Option<i64>>(6)?,
            ))
        })
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    let more = rows.len() > limit as usize;
    rows.truncate(limit as usize);
    let next = if more {
        rows.last().map(|r| r.0.clone())
    } else {
        None
    };
    let outputs = rows
        .into_iter()
        .map(|(id, width, height, connected, session, body, observed)| {
            let mut output: Value = body
                .and_then(|s| serde_json::from_str(&s).ok())
                .unwrap_or_else(|| json!({"x":0,"y":0,"scale":1,"transform":"Normal"}));
            output["output_id"] = json!(id);
            output["width"] = json!(width);
            output["height"] = json!(height);
            output["connected"] = json!(connected);
            output["observed_at"] = json!(observed);
            output["availability"] = json!(if connected
                && session
                    .as_deref()
                    .is_some_and(crate::presentation_hosts::alive)
            {
                "available"
            } else {
                "unavailable"
            });
            output
        })
        .collect::<Vec<_>>();
    return Ok(json!({"outputs":outputs,"next_after_id":next}));
}
pub fn handle(db: &mut Connection, value: &Value, who: &Principal) -> Result<Value> {
    if value["op"] == "outputs.list" {
        return list(db, value);
    }
    if !crate::presentation_hosts::trusted(who) {
        return Err(error(
            "unauthorized",
            "Only the configured compositor may observe outputs",
        ));
    }
    let id = value["output_id"]
        .as_str()
        .filter(|s| {
            !s.is_empty()
                && s.len() <= 128
                && s.bytes()
                    .all(|c| c.is_ascii_alphanumeric() || b"_-:.".contains(&c))
        })
        .ok_or_else(|| error("invalid_output", "Output identity required"))?;
    let tx = db.transaction().map_err(storage)?;
    let owner: Option<String> = tx
        .query_row(
            "SELECT session FROM presentation_output_observations WHERE id=?",
            [id],
            |r| r.get(0),
        )
        .optional()
        .map_err(storage)?;
    if who.uid != 0
        && owner
            .as_deref()
            .is_some_and(|s| s != who.session && crate::presentation_hosts::alive(s))
    {
        return Err(error(
            "unauthorized",
            "Output belongs to another live compositor",
        ));
    }
    if value["op"] == "outputs.disconnect" {
        if tx
            .execute(
                "UPDATE presentation_outputs SET connected=0 WHERE id=?",
                [id],
            )
            .map_err(storage)?
            == 0
        {
            return Err(error("missing_reference", "Output unavailable"));
        }
        tx.commit().map_err(storage)?;
        return Ok(json!({"output_id":id,"connected":false}));
    }
    // Retire disconnected hardware left behind by crashed process identities.
    let sessions = {
        let mut q = tx
            .prepare("SELECT DISTINCT session FROM presentation_output_observations")
            .map_err(storage)?;
        let rows = q
            .query_map([], |r| r.get::<_, String>(0))
            .map_err(storage)?;
        rows.collect::<std::result::Result<Vec<_>, _>>()
            .map_err(storage)?
    };
    for session in sessions {
        if session
            .split_once(':')
            .is_some_and(|(pid, start)| pid.parse::<u32>().is_ok() && start.parse::<u64>().is_ok())
            && !crate::presentation_hosts::alive(&session)
        {
            tx.execute("UPDATE presentation_outputs SET connected=0 WHERE id IN (SELECT id FROM presentation_output_observations WHERE session=?)",[session]).map_err(storage)?;
        }
    }
    let connected: i64 = tx
        .query_row(
            "SELECT COUNT(*) FROM presentation_outputs WHERE connected=1 AND id!=?",
            [id],
            |r| r.get(0),
        )
        .map_err(storage)?;
    if connected >= 64 {
        return Err(error(
            "resource_limit",
            "At most 64 outputs may be connected",
        ));
    }
    let width = number(value, "width", None, 80., 32768.)?;
    let height = number(value, "height", None, 32., 32768.)?;
    let x = number(value, "x", Some(0.), -32768., 32768.)?;
    let y = number(value, "y", Some(0.), -32768., 32768.)?;
    let scale = number(value, "scale", Some(1.), 0.5, 4.)?;
    let transform = value
        .get("transform")
        .map(Value::as_str)
        .unwrap_or(Some("Normal"))
        .filter(|s| {
            [
                "Normal",
                "_90",
                "_180",
                "_270",
                "Flipped",
                "Flipped90",
                "Flipped180",
                "Flipped270",
            ]
            .contains(s)
        })
        .ok_or_else(|| error("invalid_output", "Invalid transform"))?;
    let body = json!({"x":x,"y":y,"scale":scale,"transform":transform});
    tx.execute("INSERT INTO presentation_outputs VALUES(?,?,?,1) ON CONFLICT(id) DO UPDATE SET width=excluded.width,height=excluded.height,connected=1",params![id,width,height]).map_err(storage)?;
    tx.execute("INSERT INTO presentation_output_observations VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET session=excluded.session,body=excluded.body,observed=excluded.observed",params![id,who.session,body.to_string(),crate::now()]).map_err(storage)?;
    tx.commit().map_err(storage)?;
    Ok(
        json!({"output_id":id,"width":width,"height":height,"x":x,"y":y,"scale":scale,"transform":transform,"connected":true}),
    )
}
