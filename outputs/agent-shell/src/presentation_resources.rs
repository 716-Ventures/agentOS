//! Immutable activity-scoped image resources. Models can discover references, never publish bytes.
use crate::presentation::Principal;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
type Result<T> = std::result::Result<T, String>;
fn fail(kind: &str, detail: &str) -> String {
    json!({"code":kind,"detail":detail}).to_string()
}
fn storage(error: impl std::fmt::Display) -> String {
    fail("storage_error", &error.to_string())
}
fn reference(value: &str) -> bool {
    value.strip_prefix("resource-").is_some_and(|id| {
        id.len() == 32
            && id
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    })
}
pub fn init(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS presentation_resources(reference TEXT PRIMARY KEY,activity TEXT NOT NULL,uid INTEGER NOT NULL,label TEXT NOT NULL,body TEXT NOT NULL,width INTEGER NOT NULL,height INTEGER NOT NULL,created INTEGER NOT NULL); CREATE INDEX IF NOT EXISTS presentation_resources_activity ON presentation_resources(activity,reference);").map_err(storage)
}
pub fn activity(db: &Connection, id: &str) -> Result<Option<String>> {
    db.query_row(
        "SELECT activity FROM presentation_resources WHERE reference=?",
        [id],
        |r| r.get(0),
    )
    .optional()
    .map_err(storage)
}
pub fn handle(db: &mut Connection, value: &Value, who: &Principal) -> Result<Value> {
    let op = value["op"].as_str().unwrap_or("");
    if op != "resource.list" && !(who.uid == 0 || who.uid >= 1000) {
        return Err(fail(
            "unauthorized",
            "Resource bytes belong to human-owned native hosts",
        ));
    }
    let activity = value["activity_id"]
        .as_str()
        .filter(|v| v.parse::<u32>().is_ok_and(|n| n > 0))
        .ok_or_else(|| fail("invalid_resource", "Activity identity required"))?;
    let active:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM activities WHERE CAST(id AS TEXT)=? AND id NOT IN (SELECT activity_id FROM removed_activities))",[activity],|r|r.get(0)).map_err(storage)?;
    if !active {
        return Err(fail("missing_reference", "Activity unavailable"));
    }
    if op == "resource.list" {
        let after = match value.get("after") {
            None => "",
            Some(Value::String(id)) if id.is_empty() || reference(id) => id,
            _ => return Err(fail("invalid_resource", "Invalid resource cursor")),
        };
        let limit = match value.get("limit") {
            None => 32,
            Some(value) => value
                .as_u64()
                .filter(|v| (1..=64).contains(v))
                .ok_or_else(|| fail("invalid_resource", "Invalid resource page size"))?,
        };
        let mut query=db.prepare("SELECT reference,label,width,height,created FROM presentation_resources WHERE activity=? AND reference>? ORDER BY reference LIMIT ?").map_err(storage)?;
        let rows=query.query_map(params![activity,after,limit+1],|r|Ok(json!({"reference":r.get::<_,String>(0)?,"label":r.get::<_,String>(1)?,"width":r.get::<_,u32>(2)?,"height":r.get::<_,u32>(3)?,"created_at":r.get::<_,i64>(4)?,"mime":"image/png"}))).map_err(storage)?;
        let mut resources = rows
            .collect::<std::result::Result<Vec<_>, _>>()
            .map_err(storage)?;
        let more = resources.len() > limit as usize;
        resources.truncate(limit as usize);
        let next = if more {
            resources.last().map(|r| r["reference"].clone())
        } else {
            None
        };
        return Ok(json!({"activity_id":activity,"resources":resources,"next":next}));
    }
    let id = value["reference"]
        .as_str()
        .filter(|id| reference(id))
        .ok_or_else(|| fail("invalid_resource", "Invalid resource reference"))?;
    if op == "resource.publish" {
        let label = value["label"]
            .as_str()
            .filter(|v| !v.trim().is_empty() && v.len() <= 256 && !v.contains('\0'))
            .ok_or_else(|| fail("invalid_resource", "Bounded alternative label required"))?;
        let body = value["png_hex"]
            .as_str()
            .ok_or_else(|| fail("invalid_resource", "PNG bytes required"))?;
        let bytes = seven_sixteen_ui::content::image_hex(body)
            .map_err(|_| fail("invalid_resource", "Invalid bounded PNG encoding"))?;
        let (width, height) = seven_sixteen_ui::content::png_dimensions(&bytes)
            .map_err(|_| fail("invalid_resource", "Invalid bounded PNG image"))?;
        let tx = db.transaction().map_err(storage)?;
        let previous: Option<(String, u32, String, String)> = tx
            .query_row(
                "SELECT activity,uid,label,body FROM presentation_resources WHERE reference=?",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
            )
            .optional()
            .map_err(storage)?;
        if let Some((owned, uid, title, old)) = previous {
            if owned != activity || uid != who.uid || title != label || old != body {
                return Err(fail(
                    "immutable_resource",
                    "Resource references cannot be rebound",
                ));
            }
        } else {
            let count: i64 = tx
                .query_row(
                    "SELECT COUNT(*) FROM presentation_resources WHERE activity=?",
                    [activity],
                    |r| r.get(0),
                )
                .map_err(storage)?;
            if count >= 64 {
                return Err(fail(
                    "resource_limit",
                    "At most 64 immutable images per activity",
                ));
            }
            tx.execute("INSERT INTO presentation_resources(reference,activity,uid,label,body,width,height,created) VALUES(?,?,?,?,?,?,?,?)",params![id,activity,who.uid,label,body,width,height,crate::now()]).map_err(storage)?;
        }
        tx.commit().map_err(storage)?;
        return Ok(
            json!({"reference":id,"activity_id":activity,"width":width,"height":height,"mime":"image/png"}),
        );
    }
    if op != "resource.get" {
        return Err(fail("unsupported_operation", "Unknown resource operation"));
    }
    let row:Option<(String,String,u32,u32,u32)>=db.query_row("SELECT label,body,width,height,uid FROM presentation_resources WHERE reference=? AND activity=?",params![id,activity],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional().map_err(storage)?;
    let (label, body, width, height, uid) =
        row.ok_or_else(|| fail("missing_reference", "Resource unavailable in this activity"))?;
    if who.uid != 0 && uid != 0 && uid != who.uid {
        return Err(fail(
            "unauthorized",
            "Resource belongs to another local user",
        ));
    }
    Ok(
        json!({"reference":id,"activity_id":activity,"label":label,"png_hex":body,"width":width,"height":height,"mime":"image/png"}),
    )
}
