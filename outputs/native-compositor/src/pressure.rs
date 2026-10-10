//! Preserve preferred placement when client minimum sizes require a view overview.
use crate::{bridge::Observed, policy::Rect};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
pub fn project(
    rectangles: &mut BTreeMap<String, Rect>,
    windows: &[Observed],
    floating: &BTreeSet<String>,
    focus: Option<&String>,
    area: Rect,
) -> Value {
    let pressured = windows
        .iter()
        .filter(|w| {
            rectangles
                .get(&w.id)
                .map(|r| {
                    r.width < w.min_width
                        || r.height < w.min_height
                        || r.x < area.x
                        || r.y < area.y
                        || r.x + r.width > area.x + area.width
                        || r.y + r.height > area.y + area.height
                })
                .unwrap_or(false)
        })
        .map(|w| w.id.clone())
        .collect::<BTreeSet<_>>();
    if pressured.is_empty() {
        return Value::Null;
    }
    let ids = rectangles.keys().cloned().collect::<Vec<_>>();
    let selected = focus
        .filter(|id| rectangles.contains_key(*id) && !floating.contains(*id))
        .cloned()
        .or_else(|| ids.iter().find(|id| !floating.contains(*id)).cloned());
    for id in &ids {
        if floating.contains(id) {
            if let Some(window) = windows.iter().find(|w| &w.id == id) {
                let rect = rectangles.get_mut(id).unwrap();
                rect.width = rect.width.max(window.min_width);
                rect.height = rect.height.max(window.min_height);
                rect.x = rect
                    .x
                    .clamp(area.x, (area.x + area.width - rect.width).max(area.x));
                rect.y = rect
                    .y
                    .clamp(area.y, (area.y + area.height - rect.height).max(area.y));
            }
        } else if selected.as_ref() == Some(id) {
            let window = windows.iter().find(|w| &w.id == id);
            rectangles.insert(
                id.clone(),
                Rect {
                    width: area.width.max(window.map(|w| w.min_width).unwrap_or(80)),
                    height: area.height.max(window.map(|w| w.min_height).unwrap_or(32)),
                    ..area
                },
            );
        } else {
            rectangles.remove(id);
        }
    }
    json!({"reason":"Client minimum sizes exceed the current arrangement. Preferred placement is retained. Switch views with Ctrl+Alt+Tab or Agent Monitor.","selected":selected,"views":ids,"constrained":pressured})
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn pressure_keeps_floating_work_and_does_not_shrink_clients() {
        let area = Rect {
            x: 0,
            y: 0,
            width: 800,
            height: 600,
        };
        let observed = |id: &str, min_width| Observed {
            id: id.into(),
            title: id.into(),
            app_id: "".into(),
            uid: 1000,
            session: "1:1".into(),
            min_width,
            min_height: 100,
        };
        let windows = vec![
            observed("a", 500),
            observed("b", 900),
            observed("float", 80),
        ];
        let base = BTreeMap::from([
            ("a".into(), Rect { width: 400, ..area }),
            (
                "b".into(),
                Rect {
                    x: 400,
                    width: 400,
                    ..area
                },
            ),
            (
                "float".into(),
                Rect {
                    x: 20,
                    y: 20,
                    width: 320,
                    height: 240,
                },
            ),
        ]);
        let mut scene = base.clone();
        let floating = BTreeSet::from(["float".into()]);
        let overview = project(&mut scene, &windows, &floating, Some(&"b".into()), area);
        assert_eq!(overview["views"].as_array().unwrap().len(), 3);
        assert!(!scene.contains_key("a"));
        assert_eq!(scene["b"].width, 900);
        assert_eq!(scene["float"], base["float"]);
        // A larger area restores the same preferred rectangles, without a journal rewrite.
        let mut restored = base;
        restored.get_mut("a").unwrap().width = 500;
        restored.get_mut("b").unwrap().width = 900;
        restored.get_mut("b").unwrap().x = 500;
        assert!(project(
            &mut restored,
            &windows,
            &floating,
            None,
            Rect {
                width: 1600,
                ..area
            }
        )
        .is_null());
    }
}
