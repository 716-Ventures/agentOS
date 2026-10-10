//! Complete broker metadata over bounded pages with a process-epoch revision ticket.
use serde_json::{json, Value};
pub fn read(
    mut request: impl FnMut(&Value) -> Result<Value, String>,
    activity: Option<i64>,
    stopped: impl Fn() -> bool,
) -> Result<Value, String> {
    for attempt in 0..3 {
        let result: Result<Value, String> = (|| {
            let mut jobs = Vec::<Value>::new();
            let mut before = None::<(f64, String)>;
            let mut revision = None::<String>;
            loop {
                if stopped() {
                    return Err("Broker read cancelled".into());
                }
                let mut query = json!({"op":"list.page","limit":32,"before":before});
                if let Some(activity) = activity {
                    query["activity"] = json!(activity);
                }
                if let Some(revision) = &revision {
                    query["expected_revision"] = json!(revision);
                }
                let page = request(&query)?;
                let observed = page["revision"]
                    .as_str()
                    .filter(|s| !s.is_empty())
                    .ok_or("Invalid broker revision")?;
                if revision
                    .as_ref()
                    .is_some_and(|revision| revision != observed)
                {
                    return Err("resync_required".into());
                }
                revision = Some(observed.into());
                let rows = page["jobs"]
                    .as_array()
                    .ok_or("Invalid broker metadata page")?;
                let mut previous = before.clone();
                for row in rows {
                    let at = row["created_at"]
                        .as_f64()
                        .filter(|at| at.is_finite() && *at >= 0.)
                        .ok_or("Invalid broker timestamp")?;
                    let id = row["id"]
                        .as_str()
                        .filter(|id| {
                            id.len() == 32
                                && id
                                    .bytes()
                                    .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
                        })
                        .ok_or("Invalid broker job identity")?;
                    let key = (at, id.to_string());
                    if previous.as_ref().is_some_and(|previous| key >= *previous) {
                        return Err("Invalid broker row cursor".into());
                    }
                    previous = Some(key);
                }
                jobs.extend(rows.iter().cloned());
                if page["next_before"].is_null() {
                    return Ok(json!(jobs));
                }
                let next: (f64, String) = serde_json::from_value(page["next_before"].clone())
                    .map_err(|_| "Invalid broker page cursor")?;
                if rows.is_empty() || previous.as_ref() != Some(&next) {
                    return Err("Invalid broker page cursor".into());
                }
                before = Some(next);
            }
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
    fn pages_scope_and_epoch_restarts_preserve_one_consistent_history() {
        let mut calls = 0;
        let id = "a".repeat(32);
        let jobs=read(|query|{calls+=1;assert_eq!(query["activity"],1);match calls{
            1=>Ok(json!({"revision":"old:1","jobs":[{"id":id,"created_at":2}],"next_before":[2,id]})),
            2=>{assert_eq!(query["expected_revision"],"old:1");Err("resync_required".into())},
            3=>{assert!(query.get("expected_revision").is_none());Ok(json!({"revision":"new:0","jobs":[{"id":id,"created_at":3}],"next_before":null}))},_=>panic!("Extra request")
        }},Some(1),||false).unwrap();
        assert_eq!(jobs[0]["created_at"], 3);
        assert_eq!(jobs.as_array().unwrap().len(), 1);
        assert!(read(|_| panic!("Cancelled read"), None, || true).is_err());
    }
}
