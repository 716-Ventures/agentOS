//! Fixed adapters for observed broker/file targets. Documents never provide executable code.
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
pub fn init(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS presentation_external_action_targets(reference TEXT PRIMARY KEY,source TEXT NOT NULL,operation TEXT NOT NULL);CREATE TABLE IF NOT EXISTS presentation_external_action_defaults(uid INTEGER NOT NULL,source TEXT NOT NULL,operation TEXT NOT NULL,reference TEXT NOT NULL,PRIMARY KEY(uid,source,operation));").map_err(storage)
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Ensure {
    op: String,
    activity_id: i64,
    sources: Vec<String>,
}
pub fn ensure(db: &mut Connection, value: &Value, who: &Principal) -> Result<Value> {
    if who.uid != 0 && who.uid < 1000 {
        return Err(error(
            "unauthorized",
            "Only a human host registers callbacks",
        ));
    }
    let req: Ensure =
        serde_json::from_value(value.clone()).map_err(|e| error("invalid_event", e))?;
    if req.op != "action.ensure_sources" || req.activity_id <= 0 || req.sources.len() > 64 {
        return Err(error(
            "invalid_event",
            "At most 64 sources in one activity are accepted",
        ));
    }
    let sources = req
        .sources
        .into_iter()
        .collect::<std::collections::BTreeSet<_>>();
    let active:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM activities WHERE id=? AND id NOT IN(SELECT activity_id FROM removed_activities))",[req.activity_id],|r|r.get(0)).map_err(storage)?;
    if !active {
        return Err(error("missing_reference", "Activity unavailable"));
    }
    for source in &sources {
        if !source.starts_with("broker:") && !source.starts_with("file:") {
            return Err(error(
                "unsupported_operation",
                "Only registered broker and file adapters exist",
            ));
        }
        if crate::presentation_sources::activity(db, source)?.as_deref()
            != Some(&req.activity_id.to_string())
        {
            return Err(error("unauthorized", "Source unavailable in this activity"));
        }
    }
    let tx = db.transaction().map_err(storage)?;
    let mut actions = Vec::new();
    for source in sources {
        let operations: &[&str] = if source.starts_with("broker:") {
            &["broker.inspect", "broker.cancel", "broker.read_output"]
        } else {
            &["file.inspect"]
        };
        for operation in operations {
            let previous:Option<String>=tx.query_row("SELECT reference FROM presentation_external_action_defaults WHERE uid=? AND source=? AND operation=?",params![who.uid,source,operation],|r|r.get(0)).optional().map_err(storage)?;
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
                    "INSERT INTO presentation_external_action_targets VALUES(?,?,?)",
                    params![reference, source, operation],
                )
                .map_err(storage)?;
                tx.execute(
                    "INSERT INTO presentation_external_action_defaults VALUES(?,?,?,?)",
                    params![who.uid, source, operation, reference],
                )
                .map_err(storage)?;
                reference
            };
            let mut info = metadata(&tx, &reference)?.unwrap();
            info.as_object_mut().unwrap().remove("observed_target");
            actions.push(info);
        }
    }
    tx.commit().map_err(storage)?;
    Ok(json!({"actions":actions}))
}
pub fn metadata(db: &Connection, reference: &str) -> Result<Option<Value>> {
    let row:Option<(String,u32,bool,String,String)>=db.query_row("SELECT a.activity,a.uid,a.revoked,t.source,t.operation FROM presentation_actions a JOIN presentation_external_action_targets t USING(reference) WHERE reference=?",[reference],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional().map_err(storage)?;
    let Some((activity, uid, revoked, source, operation)) = row else {
        return Ok(None);
    };
    let observed = crate::presentation_sources::observation(db, &source)?;
    let available = !revoked
        && observed.as_ref().is_some_and(|row| {
            row["availability"] == "available" && row["activity_id"] == activity
        });
    let revision = observed
        .as_ref()
        .map(|row| row["source_revision"].clone())
        .unwrap_or(Value::Null);
    Ok(Some(
        json!({"reference":reference,"activity_id":activity,"issuer_uid":uid,"revoked":revoked,"operation":operation,"target":{"source":source},"available":available,"source_revision":revision,"parameter_schema":crate::presentation_actions::parameter_schema(&operation),"observed_target":observed}),
    ))
}
pub fn run(
    db: Option<&Connection>,
    source: &str,
    operation: &str,
    activity: &str,
    revision: u64,
    parameters: &Value,
) -> Result<Value> {
    if operation == "file.inspect" && source.starts_with("file:") {
        let observed = crate::presentation_sources::observation(
            db.ok_or_else(|| error("source_unavailable", "File observation store unavailable"))?,
            source,
        )?
        .ok_or_else(|| error("missing_reference", "Observation unavailable"))?;
        if observed["source_revision"] != revision
            || observed["activity_id"] != activity
            || observed["availability"] != "available"
        {
            return Err(error(
                "stale_revision",
                "Refresh file observation before inspection",
            ));
        }
        return Ok(observed);
    }
    let job = source
        .strip_prefix("broker:")
        .filter(|id| {
            id.len() == 32
                && id
                    .bytes()
                    .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        })
        .ok_or_else(|| error("invalid_event", "Invalid broker identity"))?;
    let op = match operation {
        "broker.inspect" | "broker.read_output" => "poll",
        "broker.cancel" => "cancel",
        _ => return Err(error("unsupported_operation", "No such broker callback")),
    };
    use std::io::{BufRead, BufReader, Read, Write};
    let endpoint = std::env::var("AGENT_OS_BROKER_SOCKET")
        .unwrap_or_else(|_| "/run/agent-os-broker/api.sock".into());
    let mut stream = std::os::unix::net::UnixStream::connect(endpoint)
        .map_err(|e| error("source_unavailable", e))?;
    stream
        .set_read_timeout(Some(std::time::Duration::from_secs(2)))
        .map_err(storage)?;
    stream
        .set_write_timeout(Some(std::time::Duration::from_secs(2)))
        .map_err(storage)?;
    let activity = activity.parse::<i64>().map_err(storage)?;
    let request = json!({"op":op,"job_id":job,"expected_source_revision":revision,"expected_activity":activity,"offset":parameters["offset"].as_u64().unwrap_or(0)});
    writeln!(stream, "{request}").map_err(|e| error("source_unavailable", e))?;
    let mut line = String::new();
    BufReader::new(stream)
        .take(512 * 1024 + 1)
        .read_line(&mut line)
        .map_err(|e| error("source_unavailable", e))?;
    if line.len() > 512 * 1024 || !line.ends_with('\n') {
        return Err(error("source_unavailable", "Invalid broker response"));
    }
    let response: Value =
        serde_json::from_str(&line).map_err(|e| error("source_unavailable", e))?;
    if response["ok"] != true {
        return Err(error(
            "source_unavailable",
            response["error"]
                .as_str()
                .unwrap_or("Broker callback failed"),
        ));
    }
    let mut observed = response["result"].clone();
    if operation == "broker.inspect" {
        if let Some(fields) = observed.as_object_mut() {
            for key in ["output", "next_offset", "has_more"] {
                fields.remove(key);
            }
        }
    }
    Ok(observed)
}
#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> Connection {
        let db = Connection::open_in_memory().unwrap();
        db.execute_batch("CREATE TABLE activities(id INTEGER PRIMARY KEY);INSERT INTO activities VALUES(1),(2);CREATE TABLE removed_activities(activity_id INTEGER PRIMARY KEY);CREATE TABLE meta(key TEXT PRIMARY KEY,value INTEGER);INSERT INTO meta VALUES('revision',0);CREATE TABLE jobs(id INTEGER PRIMARY KEY,activity_id INTEGER,argv TEXT,status TEXT,exit_code INTEGER,created_at INTEGER,finished_at INTEGER,error TEXT);").unwrap();
        crate::presentation::init(&db).unwrap();
        db
    }
    #[test]
    fn fixed_adapters_are_scoped_user_owned_revocable_and_receipted() {
        let mut db = fixture();
        let human = Principal {
            uid: 1000,
            session: "human".into(),
        };
        let agent = Principal {
            uid: 999,
            session: "model".into(),
        };
        let session = std::fs::read_to_string("/proc/self/stat")
            .ok()
            .and_then(|stat| {
                stat.rsplit_once(')').map(|(_, tail)| {
                    format!(
                        "{}:{}",
                        std::process::id(),
                        tail.split_whitespace().nth(19).unwrap()
                    )
                })
            })
            .unwrap_or_else(|| "dead-fixture".into());
        let root = Principal { uid: 0, session };
        let source = format!("file:{}", "a".repeat(32));
        crate::presentation_sources::handle(&mut db,&json!({"op":"source.publish","source":source,"activity_id":"1","source_revision":1,"values":{"path":"/tmp/note","kind":"file","size_bytes":4,"mode":420,"modified_at":1,"measured_at":2}}),&root).unwrap();
        let ensure_request =
            json!({"op":"action.ensure_sources","activity_id":1,"sources":[source]});
        assert!(ensure(&mut db, &ensure_request, &agent)
            .unwrap_err()
            .contains("unauthorized"));
        let info = ensure(&mut db, &ensure_request, &human).unwrap()["actions"][0].clone();
        assert_eq!(
            ensure(&mut db, &ensure_request, &human).unwrap()["actions"][0],
            info
        );
        assert!(info.get("observed_target").is_none());
        assert_eq!(info["operation"], "file.inspect");
        let invoke = json!({"op":"action.invoke","reference":info["reference"],"request_id":"file-inspection","expected_source_revision":1});
        assert!(crate::presentation_actions::prepare(&mut db, &invoke, &agent).is_err());
        let mut foreign = ensure_request.clone();
        foreign["activity_id"] = json!(2);
        assert!(ensure(&mut db, &foreign, &human).is_err());
        let mut injected = ensure_request.clone();
        injected["operation"] = json!("shell.execute");
        assert!(ensure(&mut db, &injected, &human).is_err());
        if info["available"] == true {
            assert!(matches!(
                crate::presentation_actions::prepare(&mut db, &invoke, &human).unwrap(),
                crate::presentation_actions::Prepared::ExternalRun { .. }
            ));
            let result = run(Some(&db), &source, "file.inspect", "1", 1, &json!({})).unwrap();
            assert_eq!(result["values"]["size_bytes"], 4);
            assert!(result["values"].get("content").is_none());
            crate::presentation_actions::finish(
                &db,
                &human,
                "file-inspection",
                Ok(result),
                "file.inspect",
            )
            .unwrap();
            assert!(matches!(
                crate::presentation_actions::prepare(&mut db, &invoke, &human).unwrap(),
                crate::presentation_actions::Prepared::Cached(_)
            ));
            assert!(run(Some(&db), &source, "file.inspect", "1", 0, &json!({}))
                .unwrap_err()
                .contains("stale_revision"));
        }
        crate::presentation_actions::handle(
            &mut db,
            &json!({"op":"action.revoke","reference":info["reference"]}),
            &human,
        )
        .unwrap();
        let retained = ensure(&mut db, &ensure_request, &human).unwrap();
        assert_eq!(retained["actions"][0]["reference"], info["reference"]);
        assert_eq!(retained["actions"][0]["revoked"], true);
        assert!(crate::presentation_actions::validate_parameters(
            "broker.read_output",
            json!({"offset":262145}).as_object().unwrap()
        )
        .is_err());
    }
    #[test]
    fn broker_adapter_sends_fixed_target_revision_and_activity_only() {
        use std::{
            io::{BufRead, BufReader, Write},
            os::unix::net::UnixListener,
        };
        let root = std::env::temp_dir().join(format!(
            "agentos-callback-{}-{}",
            std::process::id(),
            crate::now()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("broker.sock");
        let listener = UnixListener::bind(&path).unwrap();
        let source = format!("broker:{}", "b".repeat(32));
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut line = String::new();
            BufReader::new(stream.try_clone().unwrap())
                .read_line(&mut line)
                .unwrap();
            let request: Value = serde_json::from_str(&line).unwrap();
            assert_eq!(request["op"], "poll");
            assert_eq!(request["expected_source_revision"], 7);
            assert_eq!(request["expected_activity"], 1);
            assert_eq!(request["offset"], 12);
            assert!(request.get("argv").is_none());
            writeln!(stream,"{}",json!({"ok":true,"result":{"id":"b".repeat(32),"status":"succeeded","output":"Observed 日本語","next_offset":30}})).unwrap();
        });
        std::env::set_var("AGENT_OS_BROKER_SOCKET", &path);
        let observed = run(
            None,
            &source,
            "broker.read_output",
            "1",
            7,
            &json!({"offset":12}),
        )
        .unwrap();
        assert_eq!(observed["output"], "Observed 日本語");
        std::env::remove_var("AGENT_OS_BROKER_SOCKET");
        server.join().unwrap();
        std::fs::remove_dir_all(root).unwrap();
    }
}
