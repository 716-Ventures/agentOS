//! Resolve only declared literals and local text fields; strings are never evaluated.
use serde_json::{Map, Value};
pub fn resolve(
    definitions: &Value,
    schema: &Value,
    mut field: impl FnMut(&str) -> Option<String>,
) -> Result<Value, String> {
    let mut values = Map::new();
    if definitions.is_null() {
        return Ok(Value::Object(values));
    }
    let definitions = definitions
        .as_object()
        .ok_or("Invalid action parameter definitions")?;
    if definitions.len() > 16 {
        return Err("Too many action parameters".into());
    }
    for (key, definition) in definitions {
        let rule = &schema[key];
        if rule["type"] != "integer" {
            return Err(format!("Unsupported action parameter: {key}"));
        }
        let value = match definition["kind"].as_str() {
            Some("literal") => definition["value"].as_u64(),
            Some("field") => definition["element_id"]
                .as_str()
                .and_then(&mut field)
                .and_then(|text| text.trim().parse::<u64>().ok()),
            _ => None,
        }
        .ok_or_else(|| format!("{key}: enter a nonnegative whole number"))?;
        if value < rule["minimum"].as_u64().unwrap_or(0)
            || value > rule["maximum"].as_u64().unwrap_or(0)
        {
            return Err(format!("{key}: value is outside its supported range"));
        }
        values.insert(key.clone(), Value::from(value));
    }
    Ok(Value::Object(values))
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn edited_parameters_are_bounded_data_and_cannot_select_a_command_or_target() {
        let schema = json!({"offset":{"type":"integer","minimum":0,"maximum":1048676}});
        let fields = json!({"offset":{"kind":"field","element_id":"position"}});
        assert_eq!(
            resolve(&fields, &schema, |_| Some(" 42 ".into())).unwrap(),
            json!({"offset":42})
        );
        for text in ["-1", "2.5", "$(id)", "1048677"] {
            assert!(resolve(&fields, &schema, |_| Some(text.into())).is_err())
        }
        assert!(resolve(
            &json!({"argv":{"kind":"literal","value":42}}),
            &schema,
            |_| None
        )
        .is_err());
        assert!(resolve(&fields, &schema, |_| None).is_err());
    }
}
