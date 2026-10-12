//! Capture bounded native evidence on deliberate input, independently of authority.
use super::*;
use std::io::Read;
use vte4::prelude::TerminalExt;

pub fn bounded(mut value: String) -> String {
    while value.len() > 8000 {
        value.pop();
    }
    value
}
pub fn label_selection(label: &gtk::Label) -> Option<String> {
    label.selection_bounds().map(|(a, b)| {
        label
            .text()
            .chars()
            .skip(a.min(b) as usize)
            .take((b - a).unsigned_abs() as usize)
            .collect()
    })
}
fn row_selection(model: Option<gtk::SelectionModel>) -> Option<(String, Option<String>)> {
    let object = model?
        .downcast::<gtk::SingleSelection>()
        .ok()?
        .selected_item()?
        .downcast::<glib::BoxedAnyObject>()
        .ok()?;
    let row = object.borrow::<ui::TableRow>();
    Some((row.cells.join("\t"), Some(row.id.clone())))
}
fn selection(element: &Element) -> Option<(String, Option<String>)> {
    if let Some(field) = &element.field {
        if let Some((a, b)) = field.entry.selection_bounds() {
            return Some((
                field
                    .entry
                    .text()
                    .chars()
                    .skip(a.min(b) as usize)
                    .take((b - a).unsigned_abs() as usize)
                    .collect(),
                None,
            ));
        }
    }
    if let Some(area) = &element.area {
        let buffer = area.view.buffer();
        if let Some((a, b)) = buffer.selection_bounds() {
            return Some((buffer.text(&a, &b, false).into(), None));
        }
    }
    if let Some(table) = &element.table {
        return row_selection(table.view.model());
    }
    if let Some(list) = &element.list {
        return row_selection(list.view.model());
    }
    if let Some(chart) = &element.chart {
        if let Some(value) = row_selection(chart.data.view.model()) {
            return Some(value);
        }
    }
    if let Some(pty) = &element.pty {
        if pty.view.terminal.has_selection() {
            return pty
                .view
                .terminal
                .text_selected(vte4::Format::Text)
                .map(|s| (s.into(), None));
        }
    }
    let labels = element
        .label
        .iter()
        .chain(element.status.iter().map(|v| &v.value))
        .chain(element.rich.iter().map(|v| &v.widget))
        .chain(
            element
                .outcome
                .iter()
                .flat_map(|v| [&v.heading, &v.message]),
        )
        .chain(element.image.iter().map(|v| &v.caption))
        .chain(element.chart.iter().map(|v| &v.heading));
    labels
        .filter_map(label_selection)
        .next()
        .map(|text| (text, None))
}

pub fn snapshot(surfaces: &BTreeMap<String, Surface>, frame: &Frame) -> Value {
    let activity = frame
        .activity
        .as_deref()
        .and_then(|s| s.parse::<i64>().ok());
    let focus = frame
        .documents
        .values()
        .find(|d| {
            d["workspace_id"].is_string() && d["activity_id"].as_str() == frame.activity.as_deref()
        })
        .map(|d| &d["focus"]);
    let chosen = surfaces
        .iter()
        .find(|(_, s)| s.window.is_active())
        .or_else(|| focus.and_then(|f| surfaces.get_key_value(f["surface_id"].as_str()?)));
    let mut context = json!({"activity_id":activity,"surface_id":"native-launcher","layout_revision":0,"job_ref":null,"selection":"","selection_kind":"focused_surface","surface_title":"Agent request"});
    if let Some((id, surface)) = chosen {
        context["activity_id"] = surface.document["activity_id"]
            .as_str()
            .and_then(|s| s.parse::<i64>().ok())
            .map_or(Value::Null, |a| json!(a));
        context["surface_id"] = json!(id);
        context["layout_revision"] = json!(surface.revision.unwrap_or(0));
        context["surface_title"] = json!(surface.document["title"]
            .as_str()
            .unwrap_or("Native view")
            .chars()
            .take(200)
            .collect::<String>());
        let focused = gtk::prelude::GtkWindowExt::focus(&surface.window);
        let selected = surface
            .elements
            .iter()
            .find(|(_, e)| {
                e.container.is_none()
                    && e.split.is_none()
                    && e.tabs.is_none()
                    && e.section.is_none()
                    && e.region.is_none()
                    && focused
                        .as_ref()
                        .is_some_and(|w| w == &e.widget || w.is_ancestor(&e.widget))
            })
            .or_else(|| {
                surface
                    .elements
                    .iter()
                    .find(|(_, e)| selection(e).is_some())
            });
        if let Some((element_id, element)) = selected {
            context["element_id"] = json!(element_id);
            if let Some((text, object)) = selection(element) {
                context["selection"] = json!(bounded(text));
                context["selection_kind"] = json!(if object.is_some() {
                    "selected_object"
                } else {
                    "selected_text"
                });
                if let Some(id) = object {
                    context["object_id"] = json!(id);
                }
            }
        }
    } else if let Some(id) = focus.and_then(|f| f["surface_id"].as_str()) {
        let host = &frame.host_surfaces[id];
        if frame.connected
            && activity.is_some_and(|id| id > 0)
            && host["availability"] == "available"
            && host["activity_id"].as_str() == frame.activity.as_deref()
            && host["source_revision"].as_u64().is_some()
        {
            context["surface_id"] = json!(id);
            context["surface_title"] = json!(host["title"]
                .as_str()
                .unwrap_or("Application")
                .chars()
                .take(200)
                .collect::<String>());
            context["layout_revision"] = host["source_revision"].clone();
            context["selection_kind"] = json!("focused_application");
        }
    }
    context["selection_captured_at"] = json!(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64());
    context
}

pub fn stamp(mut context: Value, modality: &str) -> Result<Value, String> {
    let mut bytes = [0u8; 16];
    std::fs::File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut bytes))
        .map_err(|e| e.to_string())?;
    context["input_id"] = json!(bytes.iter().map(|b| format!("{b:02x}")).collect::<String>());
    context["captured_at"] = json!(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64());
    context["modality"] = json!(modality);
    Ok(context)
}

pub fn verify(
    app: &gtk::Application,
    frame: &Frame,
    commands: &Sender<Command>,
    drafts: &Arc<Mutex<BTreeMap<(String, String), Draft>>>,
) {
    for kind in [
        "TextField@1",
        "DocumentEditor@1",
        "Status@1",
        "Table@1",
        "List@1",
        "KeyValue@1",
    ] {
        let mut props = json!({"label":"Context selection","value":"Before λ 日本語 after"});
        if kind == "Status@1" {
            props = json!({"value":"Before λ 日本語 after"});
        }
        if kind == "Table@1" {
            props = json!({"label":"Context selection","columns":["Name","Detail"],"rows":[{"id":"stable-row","cells":["λ","日本語"]}]});
        }
        if kind == "List@1" {
            props = json!({"label":"Context selection","rows":[{"id":"stable-row","cells":["λ 日本語"]}]});
        }
        if kind == "KeyValue@1" {
            props = json!({"label":"Context selection","rows":[{"id":"stable-row","cells":["λ","日本語"]}]});
        }
        let doc = json!({"surface_id":"context-fixture","activity_id":"1","revision":3,"title":"Selected view","root":"root","elements":{"root":{"type":kind,"props":props}}});
        let mut surface = Surface::new(app, "context-fixture", commands);
        surface.window.set_visible(false);
        surface.update("context-fixture", &doc, frame, commands, drafts);
        let element = &surface.elements["root"];
        let expected = if let Some(field) = &element.field {
            field.entry.select_region(7, 12);
            "λ 日本語"
        } else if let Some(area) = &element.area {
            let buffer = area.view.buffer();
            buffer.select_range(&buffer.iter_at_offset(7), &buffer.iter_at_offset(12));
            "λ 日本語"
        } else if let Some(status) = &element.status {
            status.value.select_region(7, 12);
            assert!(!status.reconcile("New observed state 日本語").unwrap());
            "λ 日本語"
        } else if let Some(table) = &element.table {
            assert!(table.select_key("stable-row"));
            "λ\t日本語"
        } else {
            let list = element.list.as_ref().unwrap();
            assert!(list.select_key("stable-row"));
            if kind == "KeyValue@1" {
                "λ\t日本語"
            } else {
                "λ 日本語"
            }
        };
        let mut current = frame.clone();
        current.activity = Some("1".into());
        current
            .documents
            .retain(|_, d| !d["workspace_id"].is_string());
        current.documents.insert("context-workspace".into(),json!({"workspace_id":"context-workspace","activity_id":"1","focus":{"surface_id":"context-fixture","element_id":"root"}}));
        let surfaces = BTreeMap::from([("context-fixture".into(), surface)]);
        let captured = snapshot(&surfaces, &current);
        assert_eq!(captured["selection"], expected, "{kind}");
        assert_eq!(captured["element_id"], "root");
        assert_eq!(captured["layout_revision"], 3);
        if matches!(kind, "Table@1" | "List@1" | "KeyValue@1") {
            assert_eq!(captured["object_id"], "stable-row");
            assert_eq!(captured["selection_kind"], "selected_object");
        } else {
            assert_eq!(captured["selection_kind"], "selected_text");
        }
        if let Some(status) = &surfaces["context-fixture"].elements["root"].status {
            // This fixture never realizes its window. Release PRIMARY while
            // its label is alive; GTK 4.14 otherwise retains a stale provider.
            status.value.select_region(0, 0);
            assert!(status.value.selection_bounds().is_none());
        }
        surfaces["context-fixture"].window.destroy();
    }
    let unicode = "日本語λ".repeat(3000);
    let value = bounded(unicode.clone());
    assert!(value.len() <= 8000 && unicode.starts_with(&value));
    println!("CHECK: actual native field/editor/Status and Table/List/KeyValue Unicode selections retain stable surface/element/row identities");
}

/// Recheck authority-relevant identities before launching a request. Original
/// selected content stays immutable; current state cannot silently replace it.
pub fn prepare(
    mut context: Value,
    activity: i64,
    mut core: impl FnMut(&Value) -> Result<Value, String>,
    mut broker: impl FnMut(&Value) -> Result<Value, String>,
    stopped: impl Fn() -> bool,
) -> Result<Value, String> {
    if context["activity_id"] != activity {
        return Err("The selected context belongs to another activity. Open a new request.".into());
    }
    let generation = broker(&json!({"op":"activity_state","activity":activity}))?["generation"]
        .as_u64()
        .ok_or("Current work generation unavailable")?;
    match context["modality"].as_str() {
        Some("typed") => context["expected_generation"] = json!(generation),
        Some("voice") if context["expected_generation"].as_u64() == Some(generation) => {}
        Some("voice") => {
            return Err("Work was stopped after recording. Record a new request.".into())
        }
        _ => return Err("Input modality unavailable".into()),
    }
    let surface = context["surface_id"]
        .as_str()
        .ok_or("Input surface unavailable")?;
    if surface == "native-monitor" {
        let reference = &context["job_ref"];
        let valid = if let Some(id) = reference.as_i64() {
            core(&json!({"op":"job.get","job_id":id}))
                .map(|job| job["id"] == id && job["activity_id"] == activity)
                .unwrap_or(false)
        } else if let Some(id) = reference.as_str().and_then(|r| r.strip_prefix("broker:")) {
            broker(&json!({"op":"poll","job_id":id}))
                .map(|job| job["activity"] == activity)
                .unwrap_or(false)
        } else {
            false
        };
        if !valid {
            return Err("The referenced work is unavailable or belongs to another activity. Open a new request.".into());
        }
    } else if surface != "native-launcher" {
        let snapshot = presentation_pages::read(&mut core, Some(&activity.to_string()), &stopped)?;
        if context["selection_kind"] == "focused_application" {
            let host = &snapshot["host_surfaces"][surface];
            if host["availability"] != "available"
                || host["activity_id"].as_str() != Some(activity.to_string().as_str())
                || host["source_revision"].as_u64().is_none()
                || host["source_revision"] != context["layout_revision"]
                || context.get("element_id").is_some()
                || context.get("object_id").is_some()
                || !context["job_ref"].is_null()
                || context["selection"].as_str() != Some("")
            {
                return Err(
                    "The referenced application changed or disconnected. Open a new request."
                        .into(),
                );
            }
            if stopped() {
                return Err("Request cancelled".into());
            }
            return Ok(context);
        }
        let doc = &snapshot["documents"][surface];
        if doc["activity_id"].as_str() != Some(activity.to_string().as_str()) {
            return Err("The referenced view was closed or moved. Open a new request.".into());
        }
        if let Some(id) = context["element_id"].as_str() {
            let element = &doc["elements"][id];
            if !element.is_object() {
                return Err("The selected control was removed. Open a new request.".into());
            }
            if let Some(object) = context["object_id"].as_str() {
                let rows = if element["type"] == "Chart@1" {
                    &element["props"]["points"]
                } else {
                    &element["props"]["rows"]
                };
                if !rows
                    .as_array()
                    .is_some_and(|rows| rows.iter().any(|row| row["id"] == object))
                {
                    return Err(
                        "The selected item was removed. Select an item and open a new request."
                            .into(),
                    );
                }
            }
        }
    }
    if stopped() {
        return Err("Request cancelled".into());
    }
    Ok(context)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[ignore]
    fn real_core_application_context_rechecks_registered_revision_and_connection() {
        let socket = PathBuf::from(std::env::var("AGENT_OS_SOCKET").unwrap());
        let call = |query: &Value| transport::request(&socket, query);
        let activity = call(&json!({"op":"snapshot"})).unwrap()["activities"][0]["id"]
            .as_i64()
            .unwrap();
        let mut host = json!({"op":"host.surface","surface_id":"request-context-host","activity_id":activity.to_string(),"title":"Original application","app_id":"org.example.Context","connected":true});
        call(&host).unwrap();
        let state = presentation_pages::read(call, Some(&activity.to_string()), || false).unwrap();
        let mut context = json!({"activity_id":activity,"modality":"typed","surface_id":"request-context-host","selection_kind":"focused_application","selection":"","layout_revision":state["host_surfaces"]["request-context-host"]["source_revision"],"job_ref":null,"surface_title":"Original application"});
        let prepare_now = |context| {
            prepare(
                context,
                activity,
                call,
                |_| Ok(json!({"generation":7})),
                || false,
            )
        };
        assert!(prepare_now(context.clone()).is_ok());
        host["title"] = json!("Updated application");
        call(&host).unwrap();
        assert!(
            prepare_now(context.clone()).is_err(),
            "Changed host revision accepted"
        );
        let state = presentation_pages::read(call, Some(&activity.to_string()), || false).unwrap();
        context["layout_revision"] =
            state["host_surfaces"]["request-context-host"]["source_revision"].clone();
        assert!(prepare_now(context.clone()).is_ok());
        host["connected"] = json!(false);
        call(&host).unwrap();
        assert!(
            prepare_now(context).is_err(),
            "Disconnected application accepted"
        );
        println!("PASS: real authenticated core application context rejects changed revisions and disconnection without inference");
    }
    #[test]
    fn application_context_uses_authenticated_workspace_identity_never_a_title_match() {
        let mut frame = Frame {
            connected: true,
            activity: Some("1".into()),
            ..Frame::default()
        };
        frame.documents.insert("workspace".into(),json!({"workspace_id":"workspace","activity_id":"1","focus":{"surface_id":"chosen-host"}}));
        frame.host_surfaces = json!({"other-host":{"activity_id":"1","availability":"available","title":"Same title","source_revision":8},"chosen-host":{"activity_id":"1","availability":"available","title":"Same title","source_revision":3}});
        let captured = snapshot(&BTreeMap::new(), &frame);
        assert_eq!(captured["surface_id"], "chosen-host");
        assert_eq!(captured["selection_kind"], "focused_application");
        assert_eq!(captured["layout_revision"], 3);
        assert_eq!(captured["selection"], "");
        assert!(captured.get("element_id").is_none());
        for change in [
            json!({"availability":"unavailable"}),
            json!({"activity_id":"2"}),
            json!({"source_revision":null}),
        ] {
            let mut changed = frame.clone();
            changed.host_surfaces["chosen-host"]
                .as_object_mut()
                .unwrap()
                .extend(change.as_object().unwrap().clone());
            assert_eq!(
                snapshot(&BTreeMap::new(), &changed)["surface_id"],
                "native-launcher"
            );
        }
        frame.connected = false;
        assert_eq!(
            snapshot(&BTreeMap::new(), &frame)["surface_id"],
            "native-launcher"
        );
    }
    #[test]
    fn application_context_rejects_changed_disconnected_moved_or_forged_referents() {
        for mode in [
            "current",
            "changed",
            "disconnected",
            "moved",
            "missing",
            "forged-element",
            "forged-selection",
        ] {
            let mut context = json!({"activity_id":1,"modality":"typed","surface_id":"host","selection_kind":"focused_application","selection":"","layout_revision":3,"job_ref":null,"surface_title":"Original title"});
            if mode == "forged-element" {
                context["element_id"] = json!("invented-control");
            }
            if mode == "forged-selection" {
                context["selection"] = json!("Unobserved application text");
            }
            let result = prepare(
                context,
                1,
                |q| match q["op"].as_str().unwrap() {
                    "presentation.page" => {
                        Ok(json!({"event_cursor":7,"next_after_id":null,"documents":{}}))
                    }
                    "presentation.metadata" => Ok(
                        json!({"event_cursor":7,"host_surfaces":if mode=="missing" {json!({})}else{json!({"host":{"activity_id":if mode=="moved"{"2"}else{"1"},"availability":if mode=="disconnected"{"unavailable"}else{"available"},"source_revision":if mode=="changed"{4}else{3},"title":"Current title"}})}}),
                    ),
                    _ => panic!("Unexpected operation {q}"),
                },
                |_| Ok(json!({"generation":4})),
                || false,
            );
            assert_eq!(result.is_ok(), mode == "current", "{mode}");
            if let Ok(value) = result {
                assert_eq!(value["surface_title"], "Original title");
            }
        }
    }
    #[test]
    fn selected_object_context_keeps_original_content_and_rejects_removed_or_moved_targets() {
        for mode in ["current", "removed", "moved", "control-removed"] {
            let context = json!({"activity_id":1,"modality":"typed","surface_id":"view","element_id":"table","object_id":"row","selection_kind":"selected_object","selection":"Original λ","layout_revision":3});
            let result = prepare(
                context.clone(),
                1,
                |q| match q["op"].as_str().unwrap() {
                    "presentation.page" => Ok(
                        json!({"event_cursor":7,"next_after_id":null,"documents":{"view":{"activity_id":if mode=="moved"{"2"}else{"1"},"revision":9,"elements":if mode=="control-removed"{json!({})}else{json!({"table":{"type":"Table@1","props":{"rows":if mode=="removed"{json!([])}else{json!([{"id":"row","cells":["Updated live value"]}])}}}})}}}}),
                    ),
                    "presentation.metadata" => Ok(json!({"event_cursor":7})),
                    _ => panic!("Unexpected operation {q}"),
                },
                |q| {
                    assert_eq!(q["op"], "activity_state");
                    Ok(json!({"generation":4}))
                },
                || false,
            );
            assert_eq!(result.is_ok(), mode == "current");
            if let Ok(value) = result {
                assert_eq!(value["selection"], "Original λ");
                assert_eq!(value["layout_revision"], 3);
                assert_eq!(value["expected_generation"], 4);
            }
        }
    }
    #[test]
    fn revoked_voice_and_cross_activity_context_stop_before_source_lookup() {
        for (context, generation) in [
            (json!({"activity_id":2,"modality":"typed"}), 4),
            (
                json!({"activity_id":1,"modality":"voice","expected_generation":3}),
                4,
            ),
        ] {
            assert!(prepare(
                context,
                1,
                |_| panic!("Invalid context looked up a source"),
                |_| Ok(json!({"generation":generation})),
                || false
            )
            .is_err());
        }
        let voice = json!({"activity_id":1,"modality":"voice","expected_generation":4,"surface_id":"native-launcher","selection":"Original speech context"});
        assert_eq!(
            prepare(
                voice.clone(),
                1,
                |_| panic!("No source lookup needed"),
                |_| Ok(json!({"generation":4})),
                || false
            )
            .unwrap(),
            voice
        );
    }
}

pub fn verify_terminal_selection(element: &Element) {
    let terminal = &element.pty.as_ref().unwrap().view.terminal;
    let parsed = Rc::new(Cell::new(false));
    let ready = parsed.clone();
    let handler = terminal.connect_contents_changed(move |_| ready.set(true));
    terminal.feed("Selected terminal λ 日本語\r\n".as_bytes());
    let deadline = std::time::Instant::now() + Duration::from_secs(3);
    while !parsed.get() {
        glib::MainContext::default().iteration(false);
        assert!(
            std::time::Instant::now() < deadline,
            "VTE did not parse the selection fixture"
        );
        std::thread::sleep(Duration::from_millis(1));
    }
    terminal.disconnect(handler);
    terminal.select_all();
    let (text, object) = selection(element).expect("Native VTE selection unavailable");
    assert!(text.contains("Selected terminal λ 日本語"));
    assert!(object.is_none());
    terminal.unselect_all();
    println!("CHECK: native VTE contextual selection preserves exact Unicode without reading or replacing the clipboard");
}
