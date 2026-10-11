//! Refresh direct input only across renderer element-focus bookkeeping.
use serde_json::Value;

pub fn refresh(mut transaction: Value, baseline: &Value, current: &Value) -> Value {
    let Some(id) = baseline["workspace_id"].as_str() else {
        return transaction;
    };
    let operations = transaction["operations"].as_array();
    if !only_element_focus_changed(baseline, current)
        || transaction["expected_revisions"][id] != baseline["revision"]
        || !operations.is_some_and(|ops| {
            ops.len() == 1
                && ops[0]["op"] == "workspace.edit"
                && ops[0]["workspace_id"] == id
                && matches!(
                    ops[0]["edit"]["kind"].as_str(),
                    Some("float" | "maximize" | "restore" | "focus")
                )
        })
    {
        return transaction;
    }
    transaction["expected_revisions"][id] = current["revision"].clone();
    transaction
}

/// Revision advancement is safe only when all placement and policy data match.
/// Compare future fields too; only the renderer's element-level focus can differ.
pub fn only_element_focus_changed(baseline: &Value, current: &Value) -> bool {
    let (Some(before), Some(after)) = (baseline["revision"].as_u64(), current["revision"].as_u64())
    else {
        return false;
    };
    if after <= before || baseline["focus"]["surface_id"] != current["focus"]["surface_id"] {
        return false;
    }
    let (Some(mut old), Some(mut new)) =
        (baseline.as_object().cloned(), current.as_object().cloned())
    else {
        return false;
    };
    old.remove("revision");
    new.remove("revision");
    for document in [&mut old, &mut new] {
        if let Some(focus) = document.get_mut("focus").and_then(Value::as_object_mut) {
            focus.remove("element_id");
        }
    }
    old == new
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn element_focus_can_advance_without_replaying_or_overwriting_layout() {
        let base = json!({"workspace_id":"desktop","revision":3,"activity_id":"1","outputs":{"screen":{"tiles":null,"floating":[],"maximized":"editor"}},"constraints":[],"focus":{"surface_id":"editor","element_id":"text"}});
        let tx = json!({"op":"presentation.apply","expected_revisions":{"desktop":3},"operations":[{"op":"workspace.edit","workspace_id":"desktop","edit":{"kind":"float","surface_id":"editor","x":0,"y":0,"width":1260,"height":800}}]});
        let mut latest = base.clone();
        latest["revision"] = json!(4);
        latest["focus"]["element_id"] = Value::Null;
        assert_eq!(
            refresh(tx.clone(), &base, &latest)["expected_revisions"]["desktop"],
            4
        );
        for mutation in [
            json!({"outputs":{"screen":{"tiles":null,"floating":[],"maximized":null}}}),
            json!({"constraints":[{"surface_id":"editor"}]}),
            json!({"focus":{"surface_id":"other","element_id":null}}),
            json!({"activity_id":"2"}),
            json!({"future_policy":true}),
            json!({"revision":2}),
        ] {
            let mut changed = latest.clone();
            for (key, value) in mutation.as_object().unwrap() {
                changed[key] = value.clone();
            }
            assert_eq!(
                refresh(tx.clone(), &base, &changed),
                tx,
                "Unsafe input refresh: {mutation}"
            );
        }
        let mut unrelated = tx.clone();
        unrelated["operations"][0]["edit"]["kind"] = json!("remove");
        assert_eq!(refresh(unrelated.clone(), &base, &latest), unrelated);
        let mut stale = tx.clone();
        stale["expected_revisions"]["desktop"] = json!(1);
        assert_eq!(refresh(stale.clone(), &base, &latest), stale);
        let mut multiple = tx.clone();
        multiple["operations"]
            .as_array_mut()
            .unwrap()
            .push(tx["operations"][0].clone());
        assert_eq!(refresh(multiple.clone(), &base, &latest), multiple);
    }
}
