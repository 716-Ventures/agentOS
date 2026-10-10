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
struct Ensure {
    op: String,
    activity_id: i64,
    job_ids: Vec<i64>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Invoke {
    op: String,
    reference: String,
    request_id: String,
    expected_source_revision: u64,
    #[serde(default)]
    parameters: serde_json::Map<String, Value>,
    surface_id: Option<String>,
    expected_surface_revision: Option<u64>,
    action_id: Option<String>,
}
#[derive(Debug)]
pub enum Prepared {
    Cached(Value),
    Run {
        request_id: String,
        job: i64,
        operation: String,
        parameters: Value,
    },
}

pub fn init(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS presentation_action_targets(reference TEXT PRIMARY KEY,operation TEXT NOT NULL,job INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS presentation_action_defaults(uid INTEGER NOT NULL,job INTEGER NOT NULL,operation TEXT NOT NULL,reference TEXT NOT NULL,PRIMARY KEY(uid,job,operation));
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
        "source_revision":revision,"parameter_schema":parameter_schema(&operation),"observed_target":source}),
    )
}
fn discovery(db: &Connection, reference: &str) -> Result<Value> {
    let mut value = metadata(db, reference)?;
    value.as_object_mut().unwrap().remove("observed_target");
    Ok(value)
}
pub fn parameter_schema(operation: &str) -> Value {
    if operation == "job.read_output" {
        json!({"offset":{"type":"integer","minimum":0,"maximum":1048676}})
    } else {
        json!({})
    }
}
pub fn validate_parameters(
    operation: &str,
    parameters: &serde_json::Map<String, Value>,
) -> Result<()> {
    let schema = parameter_schema(operation);
    for (key, value) in parameters {
        let rule = &schema[key];
        let valid = rule["type"] == "integer"
            && value
                .as_u64()
                .map(|n| {
                    n >= rule["minimum"].as_u64().unwrap_or(0)
                        && n <= rule["maximum"].as_u64().unwrap_or(0)
                })
                .unwrap_or(false);
        if !valid {
            return Err(error(
                "invalid_event",
                format!("Unsupported or invalid callback parameter: {key}"),
            ));
        }
    }
    Ok(())
}
pub fn handle(db: &mut Connection, value: &Value, who: &Principal) -> Result<Value> {
    match value["op"].as_str().unwrap_or("") {
        "action.ensure" => {
            human(who)?;
            let req: Ensure =
                serde_json::from_value(value.clone()).map_err(|e| error("invalid_event", e))?;
            if req.op != "action.ensure"
                || req.job_ids.len() > 64
                || req.activity_id <= 0
                || req.job_ids.iter().any(|id| *id <= 0)
            {
                return Err(error(
                    "resource_limit",
                    "At most 64 valid job identities are accepted",
                ));
            }
            let active:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM activities WHERE id=? AND id NOT IN(SELECT activity_id FROM removed_activities))",[req.activity_id],|r|r.get(0)).map_err(storage)?;
            if !active {
                return Err(error("missing_reference", "Activity unavailable"));
            }
            let jobs = req
                .job_ids
                .into_iter()
                .collect::<std::collections::BTreeSet<_>>();
            for id in &jobs {
                if job(db, *id)?["activity_id"] != req.activity_id {
                    return Err(error("unauthorized", "Target is in another activity"));
                }
            }
            let tx = db.transaction().map_err(storage)?;
            let mut actions = Vec::new();
            for job in jobs {
                for operation in ["job.inspect", "job.cancel", "job.read_output"] {
                    let previous:Option<String>=tx.query_row("SELECT reference FROM presentation_action_defaults WHERE uid=? AND job=? AND operation=?",params![who.uid,job,operation],|r|r.get(0)).optional().map_err(storage)?;
                    let reference = if let Some(reference) = previous {
                        reference
                    } else {
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
                            params![reference, operation, job],
                        )
                        .map_err(storage)?;
                        tx.execute(
                            "INSERT INTO presentation_action_defaults VALUES(?,?,?,?)",
                            params![who.uid, job, operation, reference],
                        )
                        .map_err(storage)?;
                        reference
                    };
                    actions.push(discovery(&tx, &reference)?);
                }
            }
            tx.commit().map_err(storage)?;
            Ok(json!({"actions":actions}))
        }
        "action.list" => {
            let activity = value["activity_id"]
                .as_str()
                .filter(|s| s.parse::<i64>().is_ok_and(|n| n > 0))
                .ok_or_else(|| error("invalid_event", "Activity identity required"))?;
            let after = value["after"].as_str().unwrap_or("");
            let limit = value
                .get("limit")
                .map(|v| v.as_u64().filter(|n| (1..=128).contains(n)))
                .unwrap_or(Some(32))
                .ok_or_else(|| error("invalid_event", "Page size must be between 1 and 128"))?;
            let mut q=db.prepare("SELECT reference FROM presentation_actions WHERE activity=? AND reference>? ORDER BY reference LIMIT ?").map_err(storage)?;
            let mut refs = q
                .query_map(params![activity, after, limit + 1], |r| {
                    r.get::<_, String>(0)
                })
                .map_err(storage)?
                .collect::<std::result::Result<Vec<_>, _>>()
                .map_err(storage)?;
            let more = refs.len() > limit as usize;
            refs.truncate(limit as usize);
            let next = if more { refs.last().cloned() } else { None };
            let actions = refs
                .iter()
                .map(|reference| discovery(db, reference))
                .collect::<Result<Vec<_>>>()?;
            Ok(json!({"actions":actions,"next":next}))
        }
        "action.issue" => {
            human(who)?;
            let req: Issue =
                serde_json::from_value(value.clone()).map_err(|e| error("invalid_event", e))?;
            if req.op != "action.issue"
                || !["job.inspect", "job.cancel", "job.read_output"]
                    .contains(&req.operation.as_str())
            {
                return Err(error(
                    "unsupported_operation",
                    "Only registered core-job inspection, output and stop callbacks exist",
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
    validate_parameters(info["operation"].as_str().unwrap_or(""), &req.parameters)?;
    if req.surface_id.is_some()
        || req.expected_surface_revision.is_some()
        || req.action_id.is_some()
    {
        let surface = req
            .surface_id
            .as_deref()
            .ok_or_else(|| error("invalid_event", "Surface identity required"))?;
        let action = req
            .action_id
            .as_deref()
            .ok_or_else(|| error("invalid_event", "Action identity required"))?;
        let body: Option<String> = tx
            .query_row(
                "SELECT body FROM presentation_documents WHERE id=?",
                [surface],
                |r| r.get(0),
            )
            .optional()
            .map_err(storage)?;
        let document: Value = serde_json::from_str(
            &body.ok_or_else(|| error("missing_reference", "Surface unavailable"))?,
        )
        .map_err(storage)?;
        if document["revision"].as_u64() != req.expected_surface_revision
            || document["actions"][action]["ref"] != req.reference
        {
            return Err(error(
                "stale_revision",
                "The presented action changed before submission",
            ));
        }
        if document["activity_id"] != info["activity_id"] {
            return Err(error("unauthorized", "Action belongs to another activity"));
        }
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
        parameters: json!(req.parameters),
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
    fn defaults_are_stable_user_scoped_discoverable_and_keep_revocation() {
        let mut db = fixture();
        let agent = Principal {
            uid: 999,
            session: "model".into(),
        };
        let ensure = json!({"op":"action.ensure","activity_id":1,"job_ids":[1,1]});
        assert!(handle(&mut db, &ensure, &agent).is_err());
        let first = handle(&mut db, &ensure, &human()).unwrap();
        assert_eq!(first["actions"].as_array().unwrap().len(), 3);
        assert_eq!(first, handle(&mut db, &ensure, &human()).unwrap());
        let listed = handle(
            &mut db,
            &json!({"op":"action.list","activity_id":"1","limit":2}),
            &agent,
        )
        .unwrap();
        assert_eq!(listed["actions"].as_array().unwrap().len(), 2);
        assert!(listed["actions"][0].get("observed_target").is_none());
        let last = handle(
            &mut db,
            &json!({"op":"action.list","activity_id":"1","limit":2,"after":listed["next"]}),
            &agent,
        )
        .unwrap();
        assert_eq!(last["actions"].as_array().unwrap().len(), 1);
        assert!(last["next"].is_null());
        let reference = first["actions"][0]["reference"].clone();
        handle(
            &mut db,
            &json!({"op":"action.revoke","reference":reference}),
            &human(),
        )
        .unwrap();
        let retained = handle(&mut db, &ensure, &human()).unwrap();
        assert_eq!(retained["actions"][0]["reference"], reference);
        assert_eq!(retained["actions"][0]["revoked"], true);
        let other = Principal {
            uid: 1001,
            session: "another-human".into(),
        };
        let separate = handle(&mut db, &ensure, &other).unwrap();
        assert_ne!(separate["actions"][0]["reference"], reference);
        let count: i64 = db
            .query_row(
                "SELECT COUNT(*) FROM presentation_action_invocations",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(count, 0);
        let invalid = json!({"op":"action.ensure","activity_id":1,"job_ids":[1,999]});
        assert!(handle(&mut db, &invalid, &human()).is_err());
        let count: i64 = db
            .query_row(
                "SELECT COUNT(*) FROM presentation_action_defaults",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(count, 6);
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
    fn output_parameters_are_typed_bounded_and_cannot_change_the_target() {
        let mut db = fixture();
        let action = handle(
            &mut db,
            &json!({"op":"action.issue","activity_id":1,"job_id":1,"operation":"job.read_output"}),
            &human(),
        )
        .unwrap();
        let mut request = invoke(&action, "output-click");
        request["parameters"] = json!({"offset":42});
        match prepare(&mut db, &request, &human()).unwrap() {
            Prepared::Run {
                job, parameters, ..
            } => {
                assert_eq!(job, 1);
                assert_eq!(parameters["offset"], 42)
            }
            _ => panic!("Expected output callback"),
        }
        assert!(matches!(
            prepare(&mut db, &request, &human()).unwrap(),
            Prepared::Cached(_)
        ));
        for (index, params) in [
            json!({"offset":-1}),
            json!({"offset":"42"}),
            json!({"offset":1048677}),
            json!({"job_id":2}),
            json!({"argv":["/bin/sh"]}),
        ]
        .into_iter()
        .enumerate()
        {
            let mut invalid = invoke(&action, &format!("bad-{index}"));
            invalid["parameters"] = params;
            assert!(prepare(&mut db, &invalid, &human())
                .unwrap_err()
                .contains("invalid_event"));
        }
        let mut stale = request.clone();
        stale["request_id"] = json!("stale-form");
        stale["surface_id"] = json!("missing");
        stale["action_id"] = json!("read");
        stale["expected_surface_revision"] = json!(0);
        assert!(prepare(&mut db, &stale, &human())
            .unwrap_err()
            .contains("missing_reference"));
        assert_eq!(
            db.query_row(
                "SELECT COUNT(*) FROM presentation_action_invocations",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
            1
        );
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
