//! Byte-bounded runtime history reads, reconciled against one state revision.
use serde_json::{json, Value};
use std::sync::Arc;
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

/// Poll one bounded row to discover revision changes; retain the complete,
/// consistent history until that revision or the selected activity changes.
#[derive(Default)]
pub struct Cache { state: Option<Arc<Value>>, activity: Option<i64> }
impl Cache {
    pub fn read(&mut self, mut request: impl FnMut(&Value)->Result<Value,String>, activity:Option<i64>, stopped:impl Fn()->bool)->Result<Arc<Value>,String> {
        if stopped() { return Err("Runtime read cancelled".into()); }
        if self.activity == activity {
            if let Some(state) = &self.state {
                let probe=request(&json!({"op":"state.page","collection":"activities","limit":1}))?;
                if probe["revision"].as_i64().is_some() && probe["revision"]==state["revision"] {return Ok(state.clone());}
            }
        }
        let state=Arc::new(read(&mut request,activity,stopped)?);
        self.state=Some(state.clone());self.activity=activity;Ok(state)
    }
}

#[cfg(test)]
mod cache_tests {
    use super::*;
    #[test]
    fn idle_history_uses_one_probe_and_activity_changes_invalidate() {
        let mut cache=Cache::default();let mut calls=Vec::new();
        let mut request=|q:&Value| {calls.push(q.clone());Ok(json!({"revision":7,"rows":[],"next_before_id":null}))};
        let first=cache.read(&mut request,Some(1),||false).unwrap();
        let idle=cache.read(&mut request,Some(1),||false).unwrap();
        assert!(Arc::ptr_eq(&first,&idle),"Idle history must share its immutable snapshot");
        let switched=cache.read(&mut request,Some(2),||false).unwrap();
        assert!(!Arc::ptr_eq(&first,&switched),"Activity changes require a new snapshot");
        assert_eq!(calls.len(),5);assert_eq!(calls[2]["limit"],1);
        assert_eq!(calls[4]["activity_id"],2);
    }
    #[test]
    fn changed_revision_refreshes_all_pages() {
        let mut cache=Cache::default();
        cache.read(|_|Ok(json!({"revision":1,"rows":[],"next_before_id":null})),None,||false).unwrap();
        let mut calls=0;
        let state=cache.read(|_|{calls+=1;Ok(json!({"revision":2,"rows":[],"next_before_id":null}))},None,||false).unwrap();
        assert_eq!(calls,3);assert_eq!(state["revision"],2);
    }
}
