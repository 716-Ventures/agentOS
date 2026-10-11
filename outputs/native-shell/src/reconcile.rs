//! Text-only revisions can advance without rebuilding an actively edited tree.
use serde_json::Value;
pub fn acknowledged_values(
    before: &Value,
    after: &Value,
    acknowledged: &std::collections::BTreeMap<String, (u64, String)>,
) -> bool {
    let mut projected = before.clone();
    for (id, (revision, text)) in acknowledged {
        let node = &after["elements"][id];
        if after["revision"].as_u64().is_some_and(|current| current >= *revision)
            && matches!(node["type"].as_str(), Some("TextField@1" | "DocumentEditor@1" | "Choice@1" | "Toggle@1"))
            && (node["props"]["value"].as_str() == Some(text.as_str())
                || node["props"]["value"].as_bool().is_some_and(|value| value.to_string() == *text))
            && projected["elements"][id]["props"].is_object()
        {
            projected["elements"][id]["props"]["value"] = node["props"]["value"].clone();
        }
    }
    text_only(&projected, after)
}
pub fn text_only(before: &Value, after: &Value) -> bool {
    let (Some(old), Some(new)) = (
        before["elements"].as_object(),
        after["elements"].as_object(),
    ) else {
        return false;
    };
    if old.len() != new.len() {
        return false;
    }
    let mut projected = before.clone();
    projected["revision"] = after["revision"].clone();
    for (id, node) in new {
        let Some(previous) = old.get(id) else {
            return false;
        };
        if previous == node {
            continue;
        }
        if !matches!(node["type"].as_str(), Some("Text@1" | "Status@1"))
            || previous["type"] != node["type"]
            || previous["props"]["role"] != node["props"]["role"]
        {
            return false;
        }
        projected["elements"][id]["props"] = node["props"].clone();
    }
    projected == *after
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn confirmed_local_values_advance_without_granting_other_mutations() {
        let before=json!({"revision":0,"root":"field","elements":{"field":{"type":"TextField@1","props":{"value":"Before","label":"Draft"}}},"actions":{},"bindings":{}});
        let mut after=before.clone();after["revision"]=json!(1);after["elements"]["field"]["props"]["value"]=json!("Saved λ");
        let proof=std::collections::BTreeMap::from([("field".into(),(1,"Saved λ".into()))]);
        assert!(!text_only(&before,&after));
        assert!(acknowledged_values(&before,&after,&proof));
        assert!(!acknowledged_values(&before,&after,&Default::default()));
        for (path,value) in [("/elements/field/props/value",json!("Agent overwrite")),("/elements/field/props/label",json!("Different")),("/actions",json!({"injected":{}})),("/bindings",json!({"new":{}})),("/revision",json!(0))] {
            let mut changed=after.clone();*changed.pointer_mut(path).unwrap()=value;
            assert!(!acknowledged_values(&before,&changed,&proof),"{path}");
        }
    }
    #[test]
    fn unrelated_text_can_advance_but_fields_structure_and_authority_stay_frozen() {
        let before = json!({"revision":0,"root":"root","elements":{"root":{"type":"Stack@1","slots":{"children":["status","field"]}},"status":{"type":"Status@1","props":{"value":"Before"}},"field":{"type":"TextField@1","props":{"value":"Original"}}},"actions":{},"bindings":{}});
        let mut after = before.clone();
        after["revision"] = json!(1);
        after["elements"]["status"]["props"]["value"] = json!("After");
        assert!(text_only(&before, &after));
        for (path, value) in [
            ("/elements/field/props/value", json!("Overwrite")),
            ("/root", json!("field")),
            ("/elements/root/slots/children", json!(["field", "status"])),
            ("/actions", json!({"new":{"ref":"different"}})),
            ("/bindings", json!({"new":{"source":"different"}})),
            ("/elements/status/type", json!("Text@1")),
        ] {
            let mut changed = after.clone();
            *changed.pointer_mut(path).unwrap() = value;
            assert!(!text_only(&before, &changed), "{path}");
        }
    }
}
