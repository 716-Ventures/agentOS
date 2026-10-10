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
