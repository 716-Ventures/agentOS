//! Read bounded pages without combining different presentation journal revisions.
use serde_json::{json, Value};
pub fn read(
    mut request: impl FnMut(&Value) -> Result<Value, String>,
    activity: Option<&str>,
    stopped: impl Fn() -> bool,
) -> Result<Value, String> {
    for attempt in 0..3 {
        let result: Result<Value, String> = (|| {
            let mut documents = serde_json::Map::new();
            let mut after = String::new();
            let mut cursor = None;
            loop {
                if stopped() {
                    return Err("Presentation read cancelled".into());
                }
                let mut query = json!({"op":"presentation.page","after_id":after,"limit":16});
                if let Some(id) = activity {
                    query["activity_id"] = json!(id);
                }
                if let Some(revision) = cursor {
                    query["expected_cursor"] = json!(revision);
                }
                let page = request(&query)?;
                cursor = Some(
                    page["event_cursor"]
                        .as_i64()
                        .ok_or("Invalid presentation journal cursor")?,
                );
                documents.extend(
                    page["documents"]
                        .as_object()
                        .ok_or("Invalid presentation page")?
                        .clone(),
                );
                match page["next_after_id"].as_str() {
                    None if page["next_after_id"].is_null() => break,
                    Some(next) if next > after.as_str() => after = next.into(),
                    _ => return Err("Invalid presentation page cursor".into()),
                }
            }
            if stopped() {
                return Err("Presentation read cancelled".into());
            }
            let mut query = json!({"op":"presentation.metadata","expected_cursor":cursor});
            if let Some(id) = activity {
                query["activity_id"] = json!(id);
            }
            let mut state = request(&query)?;
            state["documents"] = json!(documents);
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
    fn retries_from_scratch_after_interleaved_edits() {
        let mut calls = 0;
        let state = read(
            |query| {
                calls += 1;
                match calls {
                    1 => Ok(json!({"event_cursor":1,"documents":{"old":{}},"next_after_id":"old"})),
                    2 => {
                        assert_eq!(query["expected_cursor"], 1);
                        Err("resync_required".into())
                    }
                    3 => {
                        assert_eq!(query["after_id"], "");
                        Ok(json!({"event_cursor":2,"documents":{"new":{}},"next_after_id":null}))
                    }
                    4 => {
                        assert_eq!(query["op"], "presentation.metadata");
                        assert_eq!(query["expected_cursor"], 2);
                        Ok(json!({"event_cursor":2}))
                    }
                    _ => panic!("Unexpected request"),
                }
            },
            Some("1"),
            || false,
        )
        .unwrap();
        assert!(state["documents"]["old"].is_null());
        assert!(state["documents"]["new"].is_object());
    }
    #[test]
    fn cancellation_and_nonprogressing_cursors_stop_reads() {
        assert!(read(|_| panic!("No request after cancellation"), None, || true).is_err());
        assert!(read(
            |_| Ok(json!({"event_cursor":0,"documents":{},"next_after_id":""})),
            None,
            || false
        )
        .is_err());
    }
}

/// Retain the last consistent documents while refreshing live metadata separately.
#[derive(Default)]
pub struct Cache {
    scope: Option<String>,
    state: Option<Value>,
}
impl Cache {
    pub fn read(
        &mut self,
        mut request: impl FnMut(&Value) -> Result<Value, String>,
        activity: Option<&str>,
        stopped: impl Fn() -> bool,
    ) -> Result<Value, String> {
        if self.state.is_none() || self.scope.as_deref() != activity {
            let state = read(&mut request, activity, &stopped)?;
            self.scope = activity.map(str::to_owned);
            self.state = Some(state.clone());
            return Ok(state);
        }
        for attempt in 0..3 {
            let result = (|| -> Result<Value, String> {
                let old = self.state.as_ref().unwrap();
                let mut documents = old["documents"]
                    .as_object()
                    .ok_or("Invalid cached documents")?
                    .clone();
                let mut after = old["event_cursor"]
                    .as_i64()
                    .ok_or("Invalid cached cursor")?;
                let mut target = None;
                let mut changed = std::collections::BTreeMap::<String, Value>::new();
                loop {
                    if stopped() {
                        return Err("Presentation read cancelled".into());
                    }
                    let mut query =
                        json!({"op":"presentation.changes","after_cursor":after,"limit":64});
                    if let Some(target) = target {
                        query["expected_cursor"] = json!(target);
                    }
                    let page = request(&query)?;
                    let latest = page["latest_cursor"]
                        .as_i64()
                        .filter(|n| *n >= after)
                        .ok_or("Invalid change journal cursor")?;
                    if target.is_some_and(|n| n != latest) {
                        return Err("resync_required".into());
                    }
                    target = Some(latest);
                    let events = page["events"]
                        .as_array()
                        .ok_or("Invalid change journal page")?;
                    for event in events {
                        let cursor = event["event_cursor"]
                            .as_i64()
                            .filter(|n| *n > after && *n <= latest)
                            .ok_or("Invalid change journal order")?;
                        let revisions = event["revisions"]
                            .as_object()
                            .ok_or("Invalid change revisions")?;
                        for (id, revision) in revisions {
                            if !revision.is_null() && revision.as_u64().is_none() {
                                return Err("Invalid changed revision".into());
                            }
                            changed.insert(id.clone(), revision.clone());
                        }
                        after = cursor;
                    }
                    if page["next_cursor"].as_i64() != Some(after) {
                        return Err("Invalid change journal continuation".into());
                    }
                    match page["has_more"].as_bool() {
                        Some(false) if after == latest => break,
                        Some(true) if !events.is_empty() && after < latest => {}
                        _ => return Err("Invalid change journal continuation".into()),
                    }
                }
                for (id, revision) in changed {
                    if stopped() {
                        return Err("Presentation read cancelled".into());
                    }
                    if revision.is_null() {
                        documents.remove(&id);
                        continue;
                    }
                    let mut query =
                        json!({"op":"presentation.get","document_id":id,"expected_cursor":target});
                    if let Some(activity) = activity {
                        query["activity_id"] = json!(activity);
                    }
                    match request(&query) {
                        Ok(doc) => {
                            documents.insert(id, doc);
                        }
                        Err(error) if error.contains("missing_reference") => {
                            documents.remove(&id);
                        }
                        Err(error) => return Err(error),
                    }
                }
                if stopped() {
                    return Err("Presentation read cancelled".into());
                }
                let mut query = json!({"op":"presentation.metadata","expected_cursor":target});
                if let Some(activity) = activity {
                    query["activity_id"] = json!(activity);
                }
                let mut state = request(&query)?;
                if state["event_cursor"].as_i64() != target {
                    return Err("resync_required".into());
                }
                state["documents"] = json!(documents);
                Ok(state)
            })();
            match result {
                Ok(state) => {
                    self.state = Some(state.clone());
                    return Ok(state);
                }
                Err(error) if error.contains("resync_required") => {
                    if attempt < 2 {
                        continue;
                    }
                    // A restored database can have an earlier cursor. Rebuild the cache
                    // only from a complete consistent scan, never from partial changes.
                    let state = read(&mut request, activity, &stopped)?;
                    self.state = Some(state.clone());
                    return Ok(state);
                }
                Err(error) => return Err(error),
            }
        }
        unreachable!()
    }
}

#[cfg(test)]
mod cache_tests {
    use super::*;
    #[test]
    fn unchanged_documents_are_not_refetched_and_tombstones_remove_old_views() {
        let mut cache = Cache {
            scope: Some("1".into()),
            state: Some(
                json!({"event_cursor":1,"documents":{"a":{"revision":0},"gone":{"revision":0}}}),
            ),
        };
        let mut calls = Vec::new();
        let state = cache.read(|q| {
            calls.push(q["op"].as_str().unwrap().to_string());
            match q["op"].as_str().unwrap() {
                "presentation.changes" => Ok(json!({"events":[{"event_cursor":2,"revisions":{"a":1,"gone":null}}],"latest_cursor":2,"next_cursor":2,"has_more":false})),
                "presentation.get" => { assert_eq!(q["document_id"],"a"); assert_eq!(q["expected_cursor"],2); assert_eq!(q["activity_id"],"1"); Ok(json!({"revision":1})) },
                "presentation.metadata" => Ok(json!({"event_cursor":2,"host_surfaces":[]})),
                _ => panic!("Unexpected full scan"),
            }
        },Some("1"),||false).unwrap();
        assert_eq!(state["documents"]["a"]["revision"], 1);
        assert!(state["documents"].get("gone").is_none());
        assert_eq!(
            calls,
            vec![
                "presentation.changes",
                "presentation.get",
                "presentation.metadata"
            ]
        );
        let state = cache
            .read(
                |q| match q["op"].as_str().unwrap() {
                    "presentation.changes" => {
                        Ok(json!({"events":[],"latest_cursor":2,"next_cursor":2,"has_more":false}))
                    }
                    "presentation.metadata" => {
                        Ok(json!({"event_cursor":2,"host_surfaces":["new live metadata"]}))
                    }
                    _ => panic!("Unchanged document was transferred"),
                },
                Some("1"),
                || false,
            )
            .unwrap();
        assert_eq!(state["documents"]["a"]["revision"], 1);
        assert_eq!(state["host_surfaces"][0], "new live metadata");
    }
    #[test]
    fn errors_keep_the_previous_consistent_cache_and_cancellation_sends_nothing() {
        let mut cache = Cache {
            scope: None,
            state: Some(json!({"event_cursor":1,"documents":{"a":{}}})),
        };
        let old = cache.state.clone();
        assert!(cache
            .read(|_| panic!("Cancelled request"), None, || true)
            .is_err());
        assert_eq!(cache.state, old);
        assert!(cache
            .read(
                |_| Ok(json!({"events":[],"latest_cursor":2,"next_cursor":1,"has_more":true})),
                None,
                || false
            )
            .is_err());
        assert_eq!(cache.state, old);
    }
}
