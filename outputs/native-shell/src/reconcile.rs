//! Text-only revisions can advance without rebuilding an actively edited tree.
use serde_json::Value;
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
