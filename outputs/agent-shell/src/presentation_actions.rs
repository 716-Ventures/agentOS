//! Host-issued callbacks. A document can reference an action, but cannot define code.
use crate::presentation::Principal;
use rusqlite::{params, Connection, OptionalExtension};
use serde::Deserialize;
use serde_json::{json, Value};
type Result<T> = std::result::Result<T, String>;
fn error(code: &str, detail: impl std::fmt::Display) -> String {
    json!({"code":code,"detail":detail.to_string()}).to_string()
}
fn storage(e: impl std::fmt::Display) -> String {
    error("storage_error", e)
}
fn human(who: &Principal) -> Result<()> {
    if who.uid == 0 || who.uid >= 1000 {
        Ok(())
    } else {
        Err(error(
            "unauthorized",
            "Action events require authenticated native user input",
        ))
    }
}
fn identity(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"-_:".contains(&c))
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Issue {
    op: String,
    activity_id: i64,
    job_id: i64,
    operation: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Invoke {
    op: String,
    reference: String,
    request_id: String,
    expected_source_revision: u64,
}
#[derive(Debug)]
pub enum Prepared {
    Cached(Value),
    Run {
        request_id: String,
        job: i64,
        operation: String,
    },
}

pub fn init(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS presentation_action_targets(reference TEXT PRIMARY KEY,operation TEXT NOT NULL,job INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS presentation_action_invocations(uid INTEGER NOT NULL,request TEXT NOT NULL,payload TEXT NOT NULL,reference TEXT NOT NULL,job INTEGER NOT NULL,operation TEXT NOT NULL,receipt TEXT NOT NULL,PRIMARY KEY(uid,request));").map_err(storage)?;
    // A lost in-flight response is reconciled from observed target state, never replayed.
    let mut q = db
        .prepare("SELECT uid,request,receipt FROM presentation_action_invocations")
        .map_err(storage)?;
    let rows = q
        .query_map([], |r| {
            Ok((
                r.get::<_, u32>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    drop(q);
    for (uid, key, raw) in rows {
        let mut receipt: Value = serde_json::from_str(&raw).map_err(storage)?;
        if receipt["status"] == "accepted" {
            receipt["status"] = json!("unknown");
            receipt["detail"] = json!(
                "Service restarted before callback completion; inspect the target before retrying"
            );
            db.execute(
                "UPDATE presentation_action_invocations SET receipt=? WHERE uid=? AND request=?",
                params![receipt.to_string(), uid, key],
            )
            .map_err(storage)?;
        }
    }
    Ok(())
}
fn job(db: &Connection, id: i64) -> Result<Value> {
    db.query_row("SELECT id,activity_id,argv,status,exit_code,created_at,finished_at,error FROM jobs WHERE id=?",[id],super::job_value).map_err(|_|error("missing_reference","Job is unavailable"))
}
pub fn metadata(db: &Connection, reference: &str) -> Result<Value> {
    let row:Option<(String,u32,bool,String,i64)>=db.query_row("SELECT a.activity,a.uid,a.revoked,t.operation,t.job FROM presentation_actions a JOIN presentation_action_targets t USING(reference) WHERE reference=?",[reference],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional().map_err(storage)?;
    let (activity, uid, revoked, operation, id) =
        row.ok_or_else(|| error("missing_reference", "Action is unavailable"))?;
    let source = job(db, id).ok();
    let revision: u64 = db
        .query_row("SELECT value FROM meta WHERE key='revision'", [], |r| {
            r.get(0)
        })
        .map_err(storage)?;
    Ok(
        json!({"reference":reference,"activity_id":activity,"issuer_uid":uid,"operation":operation,
        "target":{"source":"core","job_id":id},"revoked":revoked,"available":!revoked && source.is_some(),
        "source_revision":revision,"observed_target":source}),
    )
}
pub fn handle(db: &mut Connection, value: &Value, who: &Principal) -> Result<Value> {
    match value["op"].as_str().unwrap_or("") {
        "action.issue" => {
            human(who)?;
            let req: Issue =
                serde_json::from_value(value.clone()).map_err(|e| error("invalid_event", e))?;
            if req.op != "action.issue"
                || !["job.inspect", "job.cancel"].contains(&req.operation.as_str())
            {
                return Err(error(
                    "unsupported_operation",
                    "Only registered core-job inspection and stop callbacks exist",
                ));
            }
            let source = job(db, req.job_id)?;
            if source["activity_id"] != req.activity_id {
                return Err(error("unauthorized", "Target is in another activity"));
            }
            let active:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM activities WHERE id=? AND id NOT IN(SELECT activity_id FROM removed_activities))",[req.activity_id],|r|r.get(0)).map_err(storage)?;
            if !active {
                return Err(error("missing_reference", "Activity is unavailable"));
            }
            let tx = db.transaction().map_err(storage)?;
            let id: i64 = tx
                .query_row(
                    "SELECT COALESCE(MAX(rowid),0)+1 FROM presentation_actions",
                    [],
                    |r| r.get(0),
                )
                .map_err(storage)?;
            let reference = format!("action:{id}");
            tx.execute(
                "INSERT INTO presentation_actions VALUES(?,?,?,0)",
                params![reference, who.uid, req.activity_id.to_string()],
            )
            .map_err(storage)?;
            tx.execute(
                "INSERT INTO presentation_action_targets VALUES(?,?,?)",
                params![reference, req.operation, req.job_id],
            )
            .map_err(storage)?;
            tx.commit().map_err(storage)?;
            metadata(db, &reference)
        }
        "action.metadata" => metadata(
            db,
            value["reference"]
                .as_str()
                .ok_or_else(|| error("invalid_event", "Missing action reference"))?,
        ),
        "action.revoke" => {
            human(who)?;
            let reference = value["reference"]
                .as_str()
                .ok_or_else(|| error("invalid_event", "Missing action reference"))?;
            let changed = db
                .execute(
                    "UPDATE presentation_actions SET revoked=1 WHERE reference=? AND uid=?",
                    params![reference, who.uid],
                )
                .map_err(storage)?;
            if changed == 0 {
                return Err(error(
                    "unauthorized",
                    "Action is absent or owned by another principal",
                ));
            }
            metadata(db, reference)
        }
        "action.status" => {
            let key = value["request_id"]
                .as_str()
                .ok_or_else(|| error("invalid_event", "Missing request identity"))?;
            let row:Option<(String,i64,String)>=db.query_row("SELECT receipt,job,operation FROM presentation_action_invocations WHERE uid=? AND request=?",params![who.uid,key],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional().map_err(storage)?;
            let (raw, target, operation) = row.ok_or_else(|| {
                error(
                    "missing_reference",
                    "No callback receipt for this principal",
                )
            })?;
            let mut receipt: Value = serde_json::from_str(&raw).map_err(storage)?;
            if operation == "job.cancel"
                && ["running", "unknown"].contains(&receipt["status"].as_str().unwrap_or(""))
            {
                if let Ok(observed) = job(db, target) {
                    if !["starting", "running", "cancelling"]
                        .contains(&observed["status"].as_str().unwrap_or(""))
                    {
                        receipt["status"] = json!("succeeded");
                        receipt["observed_target"] = observed;
                        receipt["detail"]=json!("Target is no longer running; this does not assert that a lost callback caused its exit");
                        db.execute("UPDATE presentation_action_invocations SET receipt=? WHERE uid=? AND request=?",params![receipt.to_string(),who.uid,key]).map_err(storage)?;
                    }
                }
            }
            Ok(receipt)
        }
        _ => Err(error("unsupported_operation", "Unknown action operation")),
    }
}
pub fn prepare(db: &mut Connection, value: &Value, who: &Principal) -> Result<Prepared> {
    human(who)?;
    let req: Invoke =
        serde_json::from_value(value.clone()).map_err(|e| error("invalid_event", e))?;
    if req.op != "action.invoke" || !identity(&req.request_id) {
        return Err(error("invalid_event", "Invalid callback identity"));
    }
    let payload = value.to_string();
    let tx = db.transaction().map_err(storage)?;
    let old: Option<(String, String)> = tx
        .query_row(
            "SELECT payload,receipt FROM presentation_action_invocations WHERE uid=? AND request=?",
            params![who.uid, req.request_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .map_err(storage)?;
    if let Some((previous, receipt)) = old {
        if previous != payload {
            return Err(error(
                "idempotency_conflict",
                "Callback key reused with changed payload",
            ));
        }
        return Ok(Prepared::Cached(
            serde_json::from_str(&receipt).map_err(storage)?,
        ));
    }
    let info = metadata(&tx, &req.reference)?;
    if info["issuer_uid"] != who.uid || info["available"] != true {
        return Err(error(
            "unauthorized",
            "Callback is unavailable, revoked or scoped to another principal",
        ));
    }
    if info["source_revision"] != req.expected_source_revision {
        return Err(error(
            "stale_revision",
            "Refresh the action's source state before invoking",
        ));
    }
    let target = info["target"]["job_id"].as_i64().unwrap();
    let operation = info["operation"].as_str().unwrap().to_string();
    let receipt = json!({"request_id":req.request_id,"reference":req.reference,"status":"accepted","observed_target":info["observed_target"]});
    tx.execute(
        "INSERT INTO presentation_action_invocations VALUES(?,?,?,?,?,?,?)",
        params![
            who.uid,
            req.request_id,
            payload,
            req.reference,
            target,
            operation,
            receipt.to_string()
        ],
    )
    .map_err(storage)?;
    tx.commit().map_err(storage)?;
    Ok(Prepared::Run {
        request_id: req.request_id,
        job: target,
        operation,
    })
}
pub fn finish(
    db: &Connection,
    who: &Principal,
    key: &str,
    result: Result<Value>,
    operation: &str,
) -> Result<Value> {
    let raw: String = db
        .query_row(
            "SELECT receipt FROM presentation_action_invocations WHERE uid=? AND request=?",
            params![who.uid, key],
            |r| r.get(0),
        )
        .map_err(storage)?;
    let mut receipt: Value = serde_json::from_str(&raw).map_err(storage)?;
    match result {
        Ok(observed) => {
            receipt["status"] = json!(if operation == "job.cancel"
                && ["starting", "running", "cancelling"]
                    .contains(&observed["status"].as_str().unwrap_or(""))
            {
                "running"
            } else {
                "succeeded"
            });
            receipt["observed_target"] = observed;
        }
        Err(detail) => {
            receipt["status"] = json!("failed");
            receipt["detail"] = json!(detail);
        }
    }
    db.execute(
        "UPDATE presentation_action_invocations SET receipt=? WHERE uid=? AND request=?",
        params![receipt.to_string(), who.uid, key],
    )
    .map_err(storage)?;
    Ok(receipt)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> Connection {
        let db = Connection::open_in_memory().unwrap();
        db.execute_batch("CREATE TABLE activities(id INTEGER PRIMARY KEY); INSERT INTO activities VALUES(1);
            CREATE TABLE removed_activities(activity_id INTEGER PRIMARY KEY);
            CREATE TABLE meta(key TEXT PRIMARY KEY,value INTEGER); INSERT INTO meta VALUES('revision',0);
            CREATE TABLE jobs(id INTEGER PRIMARY KEY,activity_id INTEGER,argv TEXT,status TEXT,exit_code INTEGER,created_at INTEGER,finished_at INTEGER,error TEXT);
            INSERT INTO jobs VALUES(1,1,'[\"/bin/sleep\",\"60\"]','running',NULL,1,NULL,NULL);").unwrap();
        crate::presentation::init(&db).unwrap();
        db
    }
    fn human() -> Principal {
        Principal {
            uid: 1000,
            session: "native".into(),
        }
    }
    fn issue(db: &mut Connection) -> Value {
        handle(
            db,
            &json!({"op":"action.issue","activity_id":1,"job_id":1,"operation":"job.cancel"}),
            &human(),
        )
        .unwrap()
    }
    fn invoke(info: &Value, key: &str) -> Value {
        json!({"op":"action.invoke","reference":info["reference"],"request_id":key,"expected_source_revision":info["source_revision"]})
    }
    #[test]
    fn only_core_issued_scoped_callbacks_are_available() {
        let mut db = fixture();
        let agent = Principal {
            uid: 999,
            session: "agent".into(),
        };
        assert!(handle(
            &mut db,
            &json!({"op":"action.issue","activity_id":1,"job_id":1,"operation":"job.cancel"}),
            &agent
        )
        .unwrap_err()
        .contains("unauthorized"));
        assert!(handle(
            &mut db,
            &json!({"op":"action.issue","activity_id":1,"job_id":1,"operation":"shell.execute"}),
            &human()
        )
        .is_err());
        assert!(handle(
            &mut db,
            &json!({"op":"action.issue","activity_id":2,"job_id":1,"operation":"job.cancel"}),
            &human()
        )
        .is_err());
        let action = issue(&mut db);
        let foreign = Principal {
            uid: 1001,
            session: "other user".into(),
        };
        assert!(prepare(&mut db, &invoke(&action, "foreign"), &foreign).is_err());
        let mut forged = invoke(&action, "forged");
        forged["actor"] = json!("human");
        assert!(prepare(&mut db, &forged, &human()).is_err());
    }
    #[test]
    fn stale_or_revoked_callbacks_do_not_allocate_execution_receipts() {
        let mut db = fixture();
        let action = issue(&mut db);
        db.execute("UPDATE meta SET value=1", []).unwrap();
        assert!(prepare(&mut db, &invoke(&action, "stale"), &human())
            .unwrap_err()
            .contains("stale_revision"));
        let current = metadata(&db, action["reference"].as_str().unwrap()).unwrap();
        handle(
            &mut db,
            &json!({"op":"action.revoke","reference":action["reference"]}),
            &human(),
        )
        .unwrap();
        assert!(prepare(&mut db, &invoke(&current, "revoked"), &human()).is_err());
        assert_eq!(
            db.query_row(
                "SELECT COUNT(*) FROM presentation_action_invocations",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
            0
        );
    }
    #[test]
    fn retries_never_execute_a_callback_twice_and_changed_payloads_fail() {
        let mut db = fixture();
        let action = issue(&mut db);
        let request = invoke(&action, "click");
        assert!(matches!(
            prepare(&mut db, &request, &human()).unwrap(),
            Prepared::Run { .. }
        ));
        assert!(matches!(
            prepare(&mut db, &request, &human()).unwrap(),
            Prepared::Cached(_)
        ));
        let mut changed = request.clone();
        changed["expected_source_revision"] = json!(1);
        assert!(prepare(&mut db, &changed, &human()).is_err());
        let receipt = finish(
            &db,
            &human(),
            "click",
            Ok(json!({"id":1,"status":"cancelling"})),
            "job.cancel",
        )
        .unwrap();
        assert_eq!(receipt["status"], "running");
        db.execute(
            "UPDATE jobs SET status='cancelled',finished_at=2 WHERE id=1",
            [],
        )
        .unwrap();
        let status = handle(
            &mut db,
            &json!({"op":"action.status","request_id":"click"}),
            &human(),
        )
        .unwrap();
        assert_eq!(status["status"], "succeeded");
        assert_eq!(status["observed_target"]["status"], "cancelled");
        match prepare(&mut db, &request, &human()).unwrap() {
            Prepared::Cached(saved) => assert_eq!(saved, status),
            _ => panic!("replayed callback"),
        }
    }
    #[test]
    fn interrupted_callback_stays_unknown_until_observed_and_is_never_replayed() {
        let mut db = fixture();
        let action = issue(&mut db);
        let request = invoke(&action, "lost");
        prepare(&mut db, &request, &human()).unwrap();
        init(&db).unwrap();
        match prepare(&mut db, &request, &human()).unwrap() {
            Prepared::Cached(saved) => assert_eq!(saved["status"], "unknown"),
            _ => panic!("replayed callback"),
        }
        assert_eq!(job(&db, 1).unwrap()["status"], "running");
        let status = handle(
            &mut db,
            &json!({"op":"action.status","request_id":"lost"}),
            &human(),
        )
        .unwrap();
        assert_eq!(status["status"], "unknown");
    }
}
