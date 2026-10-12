//! Temporary output routing, independent of the durable preferred arrangement.
//! A returned display is offered for explicit restoration; it never moves work
//! merely because connector discovery noticed that the display is available.
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, PartialEq)]
struct Entry {
    activity: String,
    destination: String,
    placements: BTreeMap<String, Value>,
}

#[derive(Default)]
pub struct Recovery {
    entries: BTreeMap<(String, String), Entry>,
    available: BTreeSet<String>,
    active: String,
    generation: u64,
}

fn placements(layout: &Value) -> BTreeMap<String, Value> {
    fn tiles(node: &Value, maximized: &Value, rows: &mut BTreeMap<String, Value>) {
        if let Some(id) = node["surface_id"].as_str() {
            rows.insert(id.into(), json!({"kind":"tiled","maximized":maximized==id}));
        }
        for child in node["children"].as_array().into_iter().flatten() {
            tiles(child, maximized, rows);
        }
    }
    let mut rows = BTreeMap::new();
    tiles(&layout["tiles"], &layout["maximized"], &mut rows);
    for entry in layout["floating"].as_array().into_iter().flatten() {
        if let Some(id) = entry["surface_id"].as_str() {
            rows.insert(
                id.into(),
                json!({"kind":"floating","placement":entry,"maximized":layout["maximized"]==id}),
            );
        }
    }
    rows
}

impl Recovery {
    pub fn observe(
        &mut self,
        activity: &str,
        workspaces: &Value,
        available: &BTreeSet<String>,
        fallback: &str,
    ) {
        assert!(available.contains(fallback));
        let previous = self.entries.clone();
        // Explicit placement edits supersede temporary routing. Focus-only
        // revisions and unrelated new windows cannot release recovery.
        self.entries.retain(|(workspace, output), entry| {
            let document = &workspaces[workspace];
            let current = placements(&document["outputs"][output]);
            entry.placements.retain(|id, _| current.contains_key(id));
            document["activity_id"] == entry.activity
                && !entry.placements.is_empty()
                && entry
                    .placements
                    .iter()
                    .all(|(id, old)| current.get(id) == Some(old))
        });
        for (workspace, document) in workspaces.as_object().into_iter().flatten() {
            if document["activity_id"] != activity {
                continue;
            }
            for (preferred, layout) in document["outputs"].as_object().into_iter().flatten() {
                if placements(layout).is_empty() {
                    continue;
                }
                let key = (workspace.clone(), preferred.clone());
                if !available.contains(preferred) {
                    self.entries.entry(key.clone()).or_insert_with(|| Entry {
                        activity: activity.into(),
                        destination: fallback.into(),
                        placements: placements(layout),
                    });
                }
                if let Some(entry) = self.entries.get_mut(&key) {
                    if !available.contains(&entry.destination) {
                        entry.destination = fallback.into();
                    }
                }
            }
        }
        if previous != self.entries || self.available != *available || self.active != activity {
            self.generation = self.generation.wrapping_add(1);
        }
        self.available = available.clone();
        self.active = activity.into();
    }

    pub fn destination(&self, workspace: &str, preferred: &str) -> Option<&str> {
        self.entries
            .get(&(workspace.into(), preferred.into()))
            .map(|entry| entry.destination.as_str())
    }

    pub fn recovered_outputs(&self) -> BTreeSet<String> {
        self.entries
            .iter()
            .filter(|(_, entry)| entry.activity == self.active)
            .map(|((_, preferred), _)| preferred.clone())
            .collect()
    }

    pub fn surfaces(&self) -> BTreeSet<String> {
        self.entries
            .values()
            .filter(|entry| entry.activity == self.active)
            .flat_map(|entry| entry.placements.keys().cloned())
            .collect()
    }

    pub fn destinations(&self) -> BTreeSet<String> {
        self.entries
            .values()
            .filter(|entry| entry.activity == self.active)
            .map(|entry| entry.destination.clone())
            .collect()
    }

    /// The full local capability is compared again when the renderer acts.
    /// Topology, activity and pending-route changes invalidate old controls.
    pub fn offer(&self) -> Option<Value> {
        let outputs = self.entries.iter()
            .filter(|((_, preferred), entry)| entry.activity == self.active && self.available.contains(preferred))
            .map(|((workspace, preferred), entry)| json!({"workspace_id":workspace,"preferred_output":preferred,"temporary_output":entry.destination}))
            .collect::<Vec<_>>();
        (!outputs.is_empty()).then(
            || json!({"generation":self.generation,"activity_id":self.active,"outputs":outputs}),
        )
    }

    pub fn restore(&mut self, expected: &Value) -> Result<Value, &'static str> {
        let current = self
            .offer()
            .ok_or("No returned preferred output is ready to restore")?;
        if current != *expected {
            return Err("Output recovery changed; review the current restoration offer");
        }
        self.entries.retain(|(_, preferred), entry| {
            entry.activity != self.active || !self.available.contains(preferred)
        });
        self.generation = self.generation.wrapping_add(1);
        Ok(json!({"restored":current["outputs"],"generation":self.generation}))
    }

    pub fn context_matches(
        &self,
        available: &BTreeSet<String>,
        selected_activity: Option<&str>,
    ) -> bool {
        self.available == *available && selected_activity.map_or(true, |id| id == self.active)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn displays(names: &[&str]) -> BTreeSet<String> {
        names.iter().map(|name| (*name).into()).collect()
    }
    fn documents() -> Value {
        json!({"workspace":{"activity_id":"a","outputs":{"left":{"tiles":{"surface_id":"editor"},"floating":[],"maximized":null}}}})
    }

    #[test]
    fn return_keeps_temporary_routing_until_explicit_restoration() {
        let mut recovery = Recovery::default();
        let documents = documents();
        recovery.observe("a", &documents, &displays(&["left", "right"]), "left");
        assert_eq!(recovery.destination("workspace", "left"), None);
        recovery.observe("a", &documents, &displays(&["right"]), "right");
        assert_eq!(recovery.destination("workspace", "left"), Some("right"));
        assert!(recovery.offer().is_none());
        recovery.observe("a", &documents, &displays(&["left", "right"]), "left");
        assert_eq!(recovery.destination("workspace", "left"), Some("right"));
        let offer = recovery.offer().unwrap();
        recovery.restore(&offer).unwrap();
        assert!(recovery.destination("workspace", "left").is_none());
        assert!(recovery.restore(&offer).is_err());
        assert_eq!(
            documents,
            self::documents(),
            "Recovery never rewrites preferred documents"
        );
    }

    #[test]
    fn focus_changes_preserve_recovery_but_explicit_layout_edits_replace_it() {
        let mut recovery = Recovery::default();
        let mut documents = documents();
        recovery.observe("a", &documents, &displays(&["right"]), "right");
        documents["workspace"]["focus"] = json!({"surface_id":"editor"});
        documents["workspace"]["revision"] = json!(4);
        recovery.observe("a", &documents, &displays(&["left", "right"]), "left");
        assert_eq!(recovery.destination("workspace", "left"), Some("right"));
        documents["workspace"]["outputs"]["left"]["maximized"] = json!("editor");
        recovery.observe("a", &documents, &displays(&["left", "right"]), "left");
        assert!(recovery.offer().is_none());
        assert!(recovery.destination("workspace", "left").is_none());
    }

    #[test]
    fn stale_topology_and_activity_offers_cannot_restore_different_work() {
        let mut recovery = Recovery::default();
        let documents = documents();
        recovery.observe("a", &documents, &displays(&["right"]), "right");
        recovery.observe("a", &documents, &displays(&["left", "right"]), "left");
        let old = recovery.offer().unwrap();
        recovery.observe(
            "a",
            &documents,
            &displays(&["left", "right", "third"]),
            "left",
        );
        assert!(recovery.restore(&old).is_err());
        let current = recovery.offer().unwrap();
        recovery.observe(
            "b",
            &documents,
            &displays(&["left", "right", "third"]),
            "left",
        );
        assert!(recovery.restore(&current).is_err());
        assert_eq!(recovery.destination("workspace", "left"), Some("right"));
    }

    #[test]
    fn activity_switch_queued_before_observation_invalidates_restoration() {
        let mut recovery = Recovery::default();
        recovery.observe("a", &documents(), &displays(&["right"]), "right");
        recovery.observe("a", &documents(), &displays(&["left", "right"]), "left");
        let available = displays(&["left", "right"]);
        assert!(recovery.context_matches(&available, Some("a")));
        assert!(!recovery.context_matches(&available, Some("b")));
        assert!(!recovery.context_matches(&displays(&["right"]), Some("a")));
        assert!(recovery.offer().is_some());
    }

    #[test]
    fn disappearing_temporary_output_retargets_and_deleted_work_is_forgotten() {
        let mut recovery = Recovery::default();
        let documents = documents();
        recovery.observe("a", &documents, &displays(&["right"]), "right");
        recovery.observe("a", &documents, &displays(&["third"]), "third");
        assert_eq!(recovery.destination("workspace", "left"), Some("third"));
        recovery.observe("a", &json!({}), &displays(&["left", "third"]), "left");
        assert!(recovery.recovered_outputs().is_empty());
        assert!(recovery.offer().is_none());
    }
    #[test]
    fn an_unrelated_new_window_does_not_release_the_active_editors_recovery() {
        let mut recovery = Recovery::default();
        let mut documents = documents();
        recovery.observe("a", &documents, &displays(&["right"]), "right");
        documents["workspace"]["outputs"]["left"]["floating"] =
            json!([{"surface_id":"monitor","x":10,"y":10,"width":500,"height":400}]);
        recovery.observe("a", &documents, &displays(&["left", "right"]), "left");
        assert_eq!(recovery.destination("workspace", "left"), Some("right"));
        assert!(recovery.offer().is_some());
        assert_eq!(recovery.surfaces(), displays(&["editor"]));
    }
}
