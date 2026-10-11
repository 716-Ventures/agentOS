//! Resolve declared literals and local fields into typed data; never evaluate strings.
use serde_json::{Map, Value};
#[derive(Clone, Debug, PartialEq)]
pub struct Failure {
    pub message: String,
    // Present only when an existing editable value failed parse/range validation.
    pub field: Option<(String, String)>,
}
impl From<&str> for Failure {
    fn from(message: &str) -> Self {
        Self {
            message: message.into(),
            field: None,
        }
    }
}
#[derive(Clone, Debug)]
pub struct LocalFeedback {
    pub surface: String,
    pub element: String,
    pub revision: u64,
    pub value: String,
    pub message: String,
}
impl LocalFeedback {
    pub fn from_failure(surface: &str, revision: u64, failure: &Failure) -> Option<Self> {
        let (element, value) = failure.field.as_ref()?;
        Some(Self {
            surface: surface.into(),
            element: element.clone(),
            revision,
            value: value.clone(),
            message: failure.message.clone(),
        })
    }
    pub fn message(
        &self,
        surface: &str,
        element: &str,
        revision: u64,
        value: &str,
    ) -> Option<&str> {
        (self.surface == surface
            && self.element == element
            && self.revision == revision
            && self.value == value)
            .then_some(self.message.as_str())
    }
}
pub fn resolve(
    definitions: &Value,
    schema: &Value,
    mut field: impl FnMut(&str) -> Option<String>,
) -> Result<Value, Failure> {
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
            return Err(Failure {
                message: format!("Unsupported action parameter: {key}"),
                field: None,
            });
        }
        let submitted = match definition["kind"].as_str() {
            Some("field") => definition["element_id"]
                .as_str()
                .and_then(|id| field(id).map(|value| (id.to_string(), value))),
            _ => None,
        };
        let failure = |message| Failure {
            message,
            field: submitted.clone(),
        };
        let value = match definition["kind"].as_str() {
            Some("literal") => definition["value"].as_u64(),
            Some("field") => submitted
                .as_ref()
                .and_then(|(_, text)| text.trim().parse::<u64>().ok()),
            _ => None,
        }
        .ok_or_else(|| failure(format!("{key}: enter a nonnegative whole number")))?;
        let minimum = rule["minimum"].as_u64().unwrap_or(0);
        let maximum = rule["maximum"].as_u64().unwrap_or(0);
        if value < minimum || value > maximum {
            return Err(failure(format!(
                "{key}: enter a whole number from {minimum} to {maximum}"
            )));
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
        let bounded = resolve(
            &fields,
            &json!({"offset":{"type":"integer","minimum":5,"maximum":10}}),
            |_| Some("3".into()),
        )
        .unwrap_err();
        assert_eq!(bounded.message, "offset: enter a whole number from 5 to 10");
        for text in ["-1", "2.5", "$(id)", "1048677", "日本語"] {
            let failure = resolve(&fields, &schema, |_| Some(text.into())).unwrap_err();
            assert_eq!(failure.field, Some(("position".into(), text.into())));
            let feedback = LocalFeedback::from_failure("view", 4, &failure).unwrap();
            assert_eq!(
                feedback.message("view", "position", 4, text),
                Some(failure.message.as_str())
            );
            for (surface, element, revision, value) in [
                ("other", "position", 4, text),
                ("view", "other", 4, text),
                ("view", "position", 5, text),
                ("view", "position", 4, "42"),
            ] {
                assert!(feedback
                    .message(surface, element, revision, value)
                    .is_none());
            }
        }
        for definitions in [
            json!({"argv":{"kind":"literal","value":42}}),
            json!({"offset":{"kind":"literal","value":-1}}),
            fields.clone(),
        ] {
            let failure = resolve(&definitions, &schema, |_| None).unwrap_err();
            assert!(
                failure.field.is_none(),
                "Missing fields/literals/schema errors must not attach to an unrelated input"
            );
        }
    }
}
