//! Byte-bounded runtime history reads, reconciled against one state revision.
use serde_json::{json, Value};
pub fn read(
    mut request: impl FnMut(&Value) -> Result<Value, String>,
    activity: Option<i64>,
    stopped: impl Fn() -> bool,
) -> Result<Value, String> {
    for attempt in 0..3 {
        let result: Result<Value, String> = (|| {
            let mut state = json!({});
            let mut revision = None;
            for collection in ["activities", "jobs"] {
                let mut rows = Vec::<Value>::new();
                let mut before = None::<i64>;
                loop {
                    if stopped() {
                        return Err("Runtime read cancelled".into());
                    }
                    let mut query = json!({"op":"state.page","collection":collection,"limit":64,"before_id":before});
                    if collection == "jobs" {
                        if let Some(id) = activity {
                            query["activity_id"] = json!(id);
                        }
                    }
                    if let Some(revision) = revision {
                        query["expected_revision"] = json!(revision);
                    }
                    let page = request(&query)?;
                    let observed = page["revision"]
                        .as_i64()
                        .ok_or("Invalid runtime revision")?;
                    if revision.is_some_and(|expected| expected != observed) {
                        return Err("resync_required".into());
                    }
                    revision = Some(observed);
                    state["revision"] = json!(observed);
                    state["version"] = page["version"].clone();
                    let entries = page["rows"].as_array().ok_or("Invalid runtime page")?;
                    let mut previous = before.unwrap_or(i64::MAX);
                    for row in entries {
                        let id = row["id"]
                            .as_i64()
                            .filter(|id| *id > 0 && *id < previous)
                            .ok_or("Invalid runtime row cursor")?;
                        previous = id;
                    }
                    rows.extend(entries.iter().cloned());
                    match page["next_before_id"].as_i64() {
                        Some(next) if !entries.is_empty() && next == previous => {
                            before = Some(next)
                        }
                        None if page["next_before_id"].is_null() => break,
                        _ => return Err("Invalid runtime page cursor".into()),
                    }
                }
                state[collection] = json!(rows);
            }
            Ok(state)
        })();
        match result {
            Err(error) if error.contains("resync_required") && attempt < 2 => continue,
            other => return other,
        }
    }
    unreachable!()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn scopes_jobs_and_restarts_after_interleaved_changes() {
        let mut calls = 0;
        let state = read(
            |query| {
                calls += 1;
                match calls {
                    1 => Ok(json!({"revision":1,"rows":[{"id":2}],"next_before_id":2})),
                    2 => {
                        assert_eq!(query["before_id"], 2);
                        Err("resync_required".into())
                    }
                    3 => {
                        assert!(query.get("expected_revision").is_none());
                        Ok(json!({"revision":2,"rows":[{"id":3}],"next_before_id":null}))
                    }
                    4 => {
                        assert_eq!(query["collection"], "jobs");
                        assert_eq!(query["activity_id"], 3);
                        assert_eq!(query["expected_revision"], 2);
                        Ok(json!({"revision":2,"rows":[{"id":7}],"next_before_id":null}))
                    }
                    _ => panic!("Unexpected page"),
                }
            },
            Some(3),
            || false,
        )
        .unwrap();
        assert_eq!(state["activities"], json!([{"id":3}]));
        assert_eq!(state["jobs"], json!([{"id":7}]));
    }
    #[test]
    fn cancellation_and_invalid_cursors_stop_paging() {
        assert!(read(|_| panic!("Cancelled read"), None, || true)
            .unwrap_err()
            .contains("cancelled"));
        assert!(read(
            |_| Ok(json!({"revision":1,"rows":[],"next_before_id":2})),
            None,
            || false
        )
        .is_err());
    }
}
