//! Native shell client: stable GTK controls over the core's inert presentation API.
mod action_parameters;
mod broker_controls;
mod broker_pages;
mod controls;
mod document_dialog;
mod draft_cache;
mod first_run;
mod job_list;
mod log_view;
mod preferences;
mod presentation_pages;
mod pty_transport;
mod pty_view;
mod state_pages;
mod transport;
mod verification;
mod voice;
mod workspace_controls;
use gtk::{glib, prelude::*};
use serde_json::{json, Value};
use seven_sixteen_ui::{self as ui, gtk, Appearance, ButtonVariant, InputEvent, TextField};
use std::{
    cell::{Cell, RefCell},
    collections::BTreeMap,
    path::PathBuf,
    rc::Rc,
    sync::{mpsc::Sender, Arc, Mutex},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use transport::{Backend, Command, Draft, Frame};
fn nonce() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
}
struct Element {
    kind: String,
    widget: gtk::Widget,
    label: Option<gtk::Label>,
    rich: Option<ui::RichText>,
    image: Option<ui::ImageView>,
    reference: Option<ui::ReferenceView>,
    outcome: Option<ui::OutcomeView>,
    pty: Option<pty_view::PtyView>,
    image_attempted: bool,
    chart: Option<ui::BoundedChart>,
    field: Option<TextField>,
    choice: Option<ui::Choice>,
    selection_notice: Option<gtk::Label>,
    toggle: Option<ui::Toggle>,
    area: Option<ui::TextArea>,
    button: Option<gtk::Button>,
    progress: Option<gtk::ProgressBar>,
    container: Option<gtk::Box>,
    split: Option<ui::SplitView>,
    tabs: Option<ui::Tabs>,
    section: Option<ui::Section>,
    region: Option<ui::ScrollRegion>,
    table: Option<ui::DataTable>,
    list: Option<ui::DataList>,
    link: Option<gtk::LinkButton>,
    events: Rc<RefCell<Value>>,
    applying: Rc<Cell<bool>>,
    children: Vec<String>,
}
impl Element {
    fn child_widgets(&self) -> Option<Vec<gtk::Widget>> {
        if let Some(container) = &self.container {
            let mut widgets = Vec::new();
            let mut child = container.first_child();
            while let Some(widget) = child {
                child = widget.next_sibling();
                widgets.push(widget);
            }
            Some(widgets)
        } else if let Some(split) = &self.split {
            Some(split.children())
        } else {
            self.tabs.as_ref().map(|tabs| tabs.children())
        }
    }
    fn detach_children(&self) {
        if let Some(container) = &self.container {
            while let Some(child) = container.first_child() {
                container.remove(&child);
            }
        }
        if let Some(split) = &self.split {
            split.clear();
        }
        if let Some(tabs) = &self.tabs {
            tabs.clear();
        }
    }
}
struct Surface {
    window: gtk::ApplicationWindow,
    scroll: gtk::ScrolledWindow,
    elements: BTreeMap<String, Element>,
    revision: Option<u64>,
    root: String,
    document: Value,
}
fn lease(widget: &gtk::Widget, surface: &str, id: &str, commands: &Sender<Command>) {
    let focus = gtk::EventControllerFocus::new();
    let (s, e, c) = (surface.to_string(), id.to_string(), commands.clone());
    focus.connect_enter(move |_| {
        let _ = c.send(Command::Lease {
            surface: s.clone(),
            element: e.clone(),
            begin: true,
        });
    });
    let (s, e, c) = (surface.to_string(), id.to_string(), commands.clone());
    focus.connect_leave(move |_| {
        let _ = c.send(Command::Lease {
            surface: s.clone(),
            element: e.clone(),
            begin: false,
        });
    });
    widget.add_controller(focus);
}
fn construct(
    surface: &str,
    activity: &str,
    id: &str,
    node: &Value,
    frame: &Frame,
    commands: &Sender<Command>,
    drafts: &Arc<Mutex<BTreeMap<(String, String), Draft>>>,
) -> Element {
    let kind = node["type"].as_str().unwrap_or("Unknown").to_string();
    let props = &node["props"];
    let events = Rc::new(RefCell::new(node["events"].clone()));
    let applying = Rc::new(Cell::new(false));
    let mut result = Element {
        kind: kind.clone(),
        widget: gtk::Box::new(gtk::Orientation::Vertical, 0).upcast(),
        label: None,
        rich: None,
        image: None,
        reference: None,
        outcome: None,
        pty: None,
        image_attempted: false,
        chart: None,
        field: None,
        choice: None,
        selection_notice: None,
        toggle: None,
        area: None,
        button: None,
        progress: None,
        container: None,
        split: None,
        tabs: None,
        section: None,
        region: None,
        table: None,
        list: None,
        link: None,
        events: events.clone(),
        applying: applying.clone(),
        children: Vec::new(),
    };
    match kind.as_str() {
        "PtySession@1" => {
            let view = pty_view::PtyView::new(
                props["label"].as_str().unwrap(),
                props["source"].as_str().unwrap(),
                activity,
            );
            lease(&view.view.terminal.clone().upcast(), surface, id, commands);
            lease(&view.view.heading.clone().upcast(), surface, id, commands);
            result.widget = view.widget.clone().upcast();
            result.pty = Some(view);
        }
        "Result@1" | "Error@1" => {
            let key = if kind == "Error@1" {
                "message"
            } else {
                "value"
            };
            let value = bound(surface, &props[key], frame);
            let outcome = ui::OutcomeView::new(
                props["label"].as_str().unwrap(),
                value.as_str().unwrap_or("Unavailable"),
                kind == "Error@1",
            )
            .unwrap();
            let (events, sender) = (events.clone(), commands.clone());
            outcome.on_recover(move || dispatch_action(&events, &sender));
            lease(&outcome.message.clone().upcast(), surface, id, commands);
            lease(&outcome.heading.clone().upcast(), surface, id, commands);
            result.widget = outcome.widget.clone().upcast();
            result.outcome = Some(outcome);
        }
        "DocumentReference@1" | "ApplicationReference@1" => {
            let reference = ui::ReferenceView::new(props["label"].as_str().unwrap()).unwrap();
            let (state, sender, element) = (events.clone(), commands.clone(), id.to_string());
            reference.on_open(move || {
                let state = state.borrow();
                if let (Some(surface), Some(revision)) =
                    (state["surface"].as_str(), state["revision"].as_u64())
                {
                    let _ = sender.send(Command::Navigate {
                        surface: surface.into(),
                        element: element.clone(),
                        revision,
                    });
                }
            });
            result.widget = reference.widget.clone().upcast();
            result.reference = Some(reference);
        }
        "Image@1" => {
            let reference = props["reference"].as_str().unwrap();
            let label = props["label"].as_str().unwrap();
            result.image_attempted = frame.resources.contains_key(reference);
            let image = frame
                .resources
                .get(reference)
                .and_then(|bytes| ui::ImageView::new(label, bytes).ok());
            if let Some(image) = image {
                result.widget = image.widget.clone().upcast();
                result.label = Some(image.caption.clone());
                lease(&image.caption.clone().upcast(), surface, id, commands);
                result.image = Some(image);
            } else {
                let unavailable = ui::text(&format!("Image unavailable · {label}"), false);
                result.widget = unavailable.clone().upcast();
                result.label = Some(unavailable);
            }
        }
        "RichText@1" => {
            let runs = serde_json::from_value::<Vec<ui::RichRun>>(props["runs"].clone()).unwrap();
            let rich = ui::RichText::new(&runs).unwrap();
            result.widget = rich.widget.clone().upcast();
            result.label = Some(rich.widget.clone());
            lease(&result.widget, surface, id, commands);
            result.rich = Some(rich);
        }
        "Chart@1" => {
            let points =
                serde_json::from_value::<Vec<ui::ChartPoint>>(props["points"].clone()).unwrap();
            let chart = ui::BoundedChart::new(props["label"].as_str().unwrap(), &points).unwrap();
            result.widget = chart.widget.clone().upcast();
            lease(&result.widget, surface, id, commands);
            result.chart = Some(chart);
        }
        "Table@1" => {
            let columns = props["columns"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v.as_str().unwrap().to_string())
                .collect::<Vec<_>>();
            let table =
                ui::DataTable::new(props["label"].as_str().unwrap_or("Table"), &columns).unwrap();
            result.widget = table.widget.clone().upcast();
            lease(&result.widget, surface, id, commands);
            result.table = Some(table);
        }
        "List@1" | "KeyValue@1" => {
            let list =
                ui::DataList::new(props["label"].as_str().unwrap(), kind == "KeyValue@1").unwrap();
            result.widget = list.widget.clone().upcast();
            lease(&result.widget, surface, id, commands);
            result.list = Some(list);
        }
        "Split@1" => {
            let split = ui::SplitView::new(
                props["label"].as_str().unwrap(),
                props["axis"] == "vertical",
            )
            .unwrap();
            result.widget = split.widget.clone().upcast();
            result.split = Some(split);
        }
        "Tabs@1" => {
            let tabs = ui::Tabs::new(props["label"].as_str().unwrap()).unwrap();
            result.widget = tabs.widget.clone().upcast();
            lease(&result.widget, surface, id, commands);
            result.tabs = Some(tabs);
        }
        "Section@1" => {
            let section = ui::Section::new(props["label"].as_str().unwrap()).unwrap();
            result.widget = section.widget.clone().upcast();
            result.container = Some(section.content.clone());
            result.section = Some(section);
        }
        "Scroll@1" => {
            let region = ui::ScrollRegion::new(props["label"].as_str().unwrap()).unwrap();
            result.widget = region.widget.clone().upcast();
            result.container = Some(region.content.clone());
            result.region = Some(region);
        }
        "Stack@1" | "Row@1" => {
            let container = if kind == "Stack@1" {
                ui::column(12)
            } else {
                ui::row(12)
            };
            container.set_hexpand(true);
            result.widget = container.clone().upcast();
            result.container = Some(container);
        }
        "Text@1" | "Status@1" => {
            let label = if kind == "Status@1" {
                ui::status("")
            } else {
                ui::text("", props["role"] == "heading")
            };
            result.widget = label.clone().upcast();
            result.label = Some(label);
            if kind == "Text@1" {
                lease(&result.widget, surface, id, commands);
            } else if let Some(label) = &result.label {
                label.set_selectable(false);
            }
        }
        "Choice@1" | "Toggle@1" => {
            let recovered = frame.drafts.get(&(surface.into(), id.into()));
            let expected = recovered
                .and_then(|d| d["draft_revision"].as_u64())
                .unwrap_or(0);
            let value = recovered
                .and_then(|d| d["draft"].as_str())
                .map(String::from)
                .unwrap_or_else(|| literal_editor_value(props));
            let (s, e, edits, flag) = (
                surface.to_string(),
                id.to_string(),
                drafts.clone(),
                applying.clone(),
            );
            let changed = move |text: String| {
                if flag.get() {
                    return;
                }
                let mut drafts = edits.lock().unwrap();
                let draft = drafts.entry((s.clone(), e.clone())).or_insert(Draft {
                    text: String::new(),
                    expected,
                    dirty: false,
                    resolved: None,
                });
                draft.text = text;
                draft.dirty = true;
                draft.resolved = None;
            };
            if kind == "Choice@1" {
                let options = props["options"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|v| v.as_str().unwrap().to_string())
                    .collect::<Vec<_>>();
                let selected = if options.contains(&value) {
                    value.as_str()
                } else {
                    props["value"].as_str().unwrap()
                };
                let choice =
                    ui::Choice::new(props["label"].as_str().unwrap(), &options, selected).unwrap();
                let notice = ui::status(
                    "Saved choice is unavailable. Choose an available option before saving.",
                );
                notice.set_visible(!options.contains(&value));
                choice.widget.append(&notice);
                if !options.contains(&value) {
                    choice.control.set_selected(gtk::INVALID_LIST_POSITION);
                }
                let warning = notice.clone();
                choice.on_changed(move |value| {
                    warning.set_visible(false);
                    changed(value);
                });
                result.selection_notice = Some(notice);
                lease(&choice.control.clone().upcast(), surface, id, commands);
                draft_controls(&choice.widget, surface, id, commands, &events);
                result.widget = choice.widget.clone().upcast();
                result.choice = Some(choice);
            } else {
                let toggle =
                    ui::Toggle::new(props["label"].as_str().unwrap(), value == "true").unwrap();
                let notice =
                    ui::status("Saved toggle is unavailable. Choose true or false before saving.");
                notice.set_visible(value != "true" && value != "false");
                toggle
                    .control
                    .set_inconsistent(value != "true" && value != "false");
                toggle.widget.append(&notice);
                let warning = notice.clone();
                let control = toggle.control.clone();
                toggle.on_changed(move |value| {
                    warning.set_visible(false);
                    control.set_inconsistent(false);
                    changed(value.to_string());
                });
                result.selection_notice = Some(notice);
                lease(&toggle.control.clone().upcast(), surface, id, commands);
                draft_controls(&toggle.widget, surface, id, commands, &events);
                result.widget = toggle.widget.clone().upcast();
                result.toggle = Some(toggle);
            }
        }
        "TextField@1" | "DocumentEditor@1" => {
            let recovered = frame.drafts.get(&(surface.into(), id.into()));
            let value = recovered
                .and_then(|d| d["draft"].as_str())
                .or_else(|| props["value"].as_str())
                .unwrap_or("");
            if props["multiline"] == true || kind == "DocumentEditor@1" {
                let (area, widget) = if kind == "DocumentEditor@1" {
                    let editor =
                        ui::DocumentEditor::new(props["label"].as_str().unwrap(), value).unwrap();
                    (editor.area, editor.widget)
                } else {
                    let area = ui::TextArea::new(props["label"].as_str().unwrap_or("Text"), value);
                    let widget = area.widget.clone();
                    (area, widget)
                };
                let (s, e, edits, applying) = (
                    surface.to_string(),
                    id.to_string(),
                    drafts.clone(),
                    applying.clone(),
                );
                let expected = recovered
                    .and_then(|d| d["draft_revision"].as_u64())
                    .unwrap_or(0);
                let submit_events = events.clone();
                let submit_commands = commands.clone();
                area.on_event(move |event| {
                    if applying.get() {
                        return;
                    }
                    if matches!(&event, InputEvent::Submitted(_)) {
                        dispatch_action(&submit_events, &submit_commands);
                    }
                    if let InputEvent::Changed(text) = event {
                        let mut drafts = edits.lock().unwrap();
                        let draft = drafts.entry((s.clone(), e.clone())).or_insert(Draft {
                            text: String::new(),
                            expected,
                            dirty: false,
                            resolved: None,
                        });
                        draft.text = text;
                        draft.dirty = true;
                        draft.resolved = None;
                    }
                });
                draft_controls(&widget, surface, id, commands, &events);
                if kind == "DocumentEditor@1" {
                    let button =
                        ui::button("Export saved document…", ButtonVariant::Outline, false);
                    let (sender, s, state) =
                        (commands.clone(), surface.to_string(), events.clone());
                    button.connect_clicked(move |button| {
                        let parent = button
                            .root()
                            .and_then(|root| root.downcast::<gtk::Window>().ok());
                        document_dialog::choose(
                            parent.as_ref(),
                            Some((s.clone(), state.borrow()["revision"].as_u64().unwrap_or(0))),
                            None,
                            sender.clone(),
                        );
                    });
                    // Keep Save/Discard as the last toolbar for keyboard traversal and verification.
                    widget.insert_child_after(&button, None::<&gtk::Widget>);
                }
                result.widget = widget.clone().upcast();
                if kind == "DocumentEditor@1" {
                    lease(&widget.upcast(), surface, id, commands);
                } else {
                    lease(&area.view.clone().upcast(), surface, id, commands);
                }
                result.area = Some(area);
                return result;
            }
            let field = TextField::new(
                props["label"].as_str().unwrap_or("Text"),
                props["placeholder"].as_str().unwrap_or(""),
                value,
            );
            let (s, e, edits, applying) = (
                surface.to_string(),
                id.to_string(),
                drafts.clone(),
                applying.clone(),
            );
            let expected = recovered
                .and_then(|d| d["draft_revision"].as_u64())
                .unwrap_or(0);
            let submit_events = events.clone();
            let submit_commands = commands.clone();
            field.on_event(move |event| {
                if applying.get() {
                    return;
                }
                if matches!(&event, InputEvent::Submitted(_)) {
                    dispatch_action(&submit_events, &submit_commands);
                }
                if let InputEvent::Changed(text) = event {
                    let mut drafts = edits.lock().unwrap();
                    let draft = drafts.entry((s.clone(), e.clone())).or_insert(Draft {
                        text: String::new(),
                        expected,
                        dirty: false,
                        resolved: None,
                    });
                    draft.text = text;
                    draft.dirty = true;
                    draft.resolved = None;
                }
            });
            draft_controls(&field.widget, surface, id, commands, &events);
            result.widget = field.widget.clone().upcast();
            lease(&field.entry.clone().upcast(), surface, id, commands);
            result.field = Some(field);
        }
        "Button@1" => {
            let button = ui::button(
                props["label"].as_str().unwrap_or("Action"),
                ButtonVariant::Primary,
                props["disabled"] == true,
            );
            let (events, commands) = (events.clone(), commands.clone());
            button.connect_clicked(move |_| dispatch_action(&events, &commands));
            result.widget = button.clone().upcast();
            result.button = Some(button);
        }
        "Link@1" => {
            match ui::link(
                props["label"].as_str().unwrap_or("Link"),
                props["url"].as_str().unwrap_or(""),
            ) {
                Ok(link) => {
                    result.widget = link.clone().upcast();
                    result.link = Some(link);
                }
                Err(_) => {
                    let label = ui::text("Link unavailable", false);
                    result.widget = label.clone().upcast();
                    result.label = Some(label);
                }
            }
        }
        "Progress@1" => {
            let progress = ui::progress(
                props["label"].as_str().unwrap_or("Work"),
                props["value"].as_f64(),
            );
            result.widget = progress.clone().upcast();
            result.progress = Some(progress);
        }
        _ => {
            let label = ui::text(
                "Unsupported component · this view cannot dispatch actions",
                false,
            );
            result.widget = label.clone().upcast();
            result.label = Some(label);
        }
    }
    result
}
fn dispatch_action(events: &Rc<RefCell<Value>>, commands: &Sender<Command>) {
    let event = events.borrow();
    if let Some(reference) = event["host_reference"].as_str() {
        let _ = commands.send(Command::Action {
            reference: reference.into(),
            key: format!("native-{}", nonce()),
            surface: event["surface"].as_str().unwrap_or("").into(),
            revision: event["revision"].as_u64().unwrap_or(0),
            action: event["action"].as_str().unwrap_or("").into(),
            parameters: event["parameters"].clone(),
        });
    }
}
fn draft_controls(
    widget: &gtk::Box,
    surface: &str,
    element: &str,
    commands: &Sender<Command>,
    events: &Rc<RefCell<Value>>,
) {
    let row = ui::row(8);
    for (label, commit) in [("Save draft", true), ("Discard draft", false)] {
        let button = ui::button(label, ButtonVariant::Outline, false);
        let (sender, s, e) = (commands.clone(), surface.to_string(), element.to_string());
        let state = events.clone();
        button.connect_clicked(move |_| {
            let _ = sender.send(Command::ResolveDraft {
                surface: s.clone(),
                element: e.clone(),
                commit,
                revision: state.borrow()["revision"].as_u64().unwrap_or(0),
            });
        });
        row.append(&button);
    }
    widget.append(&row);
}
fn literal_editor_value(props: &Value) -> String {
    props["value"]
        .as_str()
        .map(String::from)
        .unwrap_or_else(|| {
            props["value"]
                .as_bool()
                .map(|value| value.to_string())
                .unwrap_or_default()
        })
}
fn editor_value(
    surface: &str,
    element: &str,
    revision: u64,
    props: &Value,
    frame: &Frame,
    drafts: &Arc<Mutex<BTreeMap<(String, String), Draft>>>,
) -> Option<String> {
    let key = (surface.to_string(), element.to_string());
    let mut edits = drafts.lock().unwrap();
    if let Some(local) = edits.get(&key) {
        if let Some(resolved) = local.resolved {
            let text = local.text.clone();
            let observed = frame
                .drafts
                .get(&key)
                .and_then(|d| d["draft_revision"].as_u64());
            if revision >= resolved && observed.map(|v| v >= local.expected).unwrap_or(false) {
                edits.remove(&key);
            }
            return Some(text);
        } else {
            return None;
        }
    }
    Some(
        frame
            .drafts
            .get(&key)
            .and_then(|v| v["draft"].as_str())
            .map(String::from)
            .unwrap_or_else(|| literal_editor_value(props)),
    )
}
fn bound(surface: &str, value: &Value, frame: &Frame) -> Value {
    if let Some(binding) = value["binding"].as_str() {
        match frame.bindings.get(surface) {
            Some(snapshot) if snapshot["bindings"][binding]["availability"] == "available" => {
                snapshot["bindings"][binding]["value"].clone()
            }
            _ => Value::Null,
        }
    } else {
        value.clone()
    }
}
impl Surface {
    fn new(app: &gtk::Application, id: &str, commands: &Sender<Command>) -> Self {
        let scroll = gtk::ScrolledWindow::builder()
            .hscrollbar_policy(gtk::PolicyType::Never)
            .build();
        let content = ui::column(0);
        let provenance = ui::text("Agent view", false);
        provenance.set_margin_start(24);
        provenance.set_margin_top(8);
        content.append(&provenance);
        content.append(&scroll);
        scroll.set_vexpand(true);
        let window = gtk::ApplicationWindow::builder()
            .application(app)
            .title("Agent view")
            .default_width(700)
            .default_height(500)
            .child(&content)
            .build();
        window.add_css_class("seven-ui");
        scroll.set_margin_top(24);
        scroll.set_margin_bottom(24);
        scroll.set_margin_start(24);
        scroll.set_margin_end(24);
        let (surface, close_commands) = (id.to_string(), commands.clone());
        window.connect_close_request(move |_| {
            let _ = close_commands.send(Command::Close {
                surface: surface.clone(),
            });
            glib::Propagation::Stop
        });
        let identity = format!("agentos.surface.{id}");
        let (registered, commands) = (id.to_string(), commands.clone());
        window.connect_map(move |window| {
            if let Some(surface) = window
                .surface()
                .and_then(|s| s.downcast::<gdk4_wayland::WaylandToplevel>().ok())
            {
                surface.set_application_id(&identity);
                let _ = commands.send(Command::RegisterRenderer(registered.clone()));
            }
        });
        // Mapping a result does not request an activation token. The compositor owns focus policy.
        window.set_visible(true);
        Self {
            window,
            scroll,
            elements: BTreeMap::new(),
            revision: None,
            root: String::new(),
            document: Value::Null,
        }
    }
    fn update(
        &mut self,
        id: &str,
        doc: &Value,
        frame: &Frame,
        commands: &Sender<Command>,
        drafts: &Arc<Mutex<BTreeMap<(String, String), Draft>>>,
    ) {
        let nodes = match doc["elements"].as_object() {
            Some(nodes) => nodes,
            None => return,
        };
        let protected = self.elements.values().any(|e| {
            e.field
                .as_ref()
                .map(|f| f.entry.has_focus() || f.entry.focus_child().is_some())
                .unwrap_or(false)
                || e.choice
                    .as_ref()
                    .map(|choice| {
                        choice.control.has_focus() || choice.control.focus_child().is_some()
                    })
                    .unwrap_or(false)
                || e.toggle
                    .as_ref()
                    .map(|toggle| {
                        toggle.control.has_focus()
                            || toggle.control.is_focus()
                            || toggle.control.focus_child().is_some()
                    })
                    .unwrap_or(false)
                || e.area
                    .as_ref()
                    .map(|a| {
                        a.view.has_focus()
                            || a.view.is_focus()
                            || a.view.buffer().selection_bounds().is_some()
                    })
                    .unwrap_or(false)
                || e.table
                    .as_ref()
                    .map(|table| table.view.has_focus() || table.view.focus_child().is_some())
                    .unwrap_or(false)
                || e.chart
                    .as_ref()
                    .map(|chart| {
                        chart.data.view.has_focus()
                            || chart.data.view.focus_child().is_some()
                            || chart.heading.selection_bounds().is_some()
                    })
                    .unwrap_or(false)
                || e.list
                    .as_ref()
                    .map(|list| list.view.has_focus() || list.view.focus_child().is_some())
                    .unwrap_or(false)
                || ((e.tabs.is_some() || e.split.is_some() || e.kind == "DocumentEditor@1")
                    && gtk::prelude::GtkWindowExt::focus(&self.window)
                        .map(|focus| focus == e.widget || focus.is_ancestor(&e.widget))
                        .unwrap_or(false))
                || e.pty.as_ref().is_some_and(|view| view.view.is_protected())
                || e.outcome.as_ref().is_some_and(|view| {
                    view.message.selection_bounds().is_some()
                        || view.heading.selection_bounds().is_some()
                })
                || e.label
                    .as_ref()
                    .map(|l| l.selection_bounds().is_some())
                    .unwrap_or(false)
        }) || drafts
            .lock()
            .unwrap()
            .iter()
            .any(|((s, _), d)| s == id && (d.dirty || d.resolved.is_none()));
        let resource_ready = !protected
            && nodes.iter().any(|(id, node)| {
                node["type"] == "Image@1"
                    && self
                        .elements
                        .get(id)
                        .is_some_and(|element| !element.image_attempted)
                    && node["props"]["reference"]
                        .as_str()
                        .is_some_and(|reference| frame.resources.contains_key(reference))
            });
        let changed = doc["revision"].as_u64() != self.revision || resource_ready;
        if changed && protected && self.revision.is_some() {
            let retained = self.document.clone();
            self.update(id, &retained, frame, commands, drafts);
            return;
        }
        if changed {
            self.window.set_title(Some(&format!(
                "Agent view · {}",
                doc["title"].as_str().unwrap_or("Work")
            )));
            for (element, node) in nodes {
                if self
                    .elements
                    .get(element)
                    .map(|e| {
                        Some(e.kind.as_str()) != node["type"].as_str()
                            || (e.kind == "Image@1"
                                && (self.document["elements"][element]["props"]["reference"]
                                    != node["props"]["reference"]
                                    || (!e.image_attempted
                                        && node["props"]["reference"].as_str().is_some_and(
                                            |reference| frame.resources.contains_key(reference),
                                        ))))
                            || (e.kind == "PtySession@1"
                                && self.document["elements"][element]["props"]["source"]
                                    != node["props"]["source"])
                            || (e.kind == "Table@1"
                                && e.table
                                    .as_ref()
                                    .map(|table| json!(table.columns()) != node["props"]["columns"])
                                    .unwrap_or(true))
                            || (e.kind == "Choice@1"
                                && e.choice
                                    .as_ref()
                                    .map(|choice| {
                                        json!(choice.options()) != node["props"]["options"]
                                    })
                                    .unwrap_or(true))
                            || (e.kind == "Text@1"
                                && e.label
                                    .as_ref()
                                    .map(|label| {
                                        label.accessible_role() == gtk::AccessibleRole::Heading
                                    })
                                    .unwrap_or(false)
                                    != (node["props"]["role"] == "heading"))
                            || (e.kind == "TextField@1"
                                && e.area.is_some() != (node["props"]["multiline"] == true))
                    })
                    .unwrap_or(true)
                {
                    if let Some(old) = self.elements.get(element) {
                        old.detach_children();
                    }
                    self.elements.insert(
                        element.clone(),
                        construct(
                            id,
                            doc["activity_id"].as_str().unwrap(),
                            element,
                            node,
                            frame,
                            commands,
                            drafts,
                        ),
                    );
                }
            }
            for (_, old) in self
                .elements
                .iter()
                .filter(|(key, _)| !nodes.contains_key(*key))
            {
                old.detach_children();
            }
            self.elements.retain(|key, _| nodes.contains_key(key));
            if doc["root"].as_str() != Some(self.root.as_str()) {
                self.scroll.set_child(gtk::Widget::NONE);
            }
            let mut plans = Vec::new();
            for (element, node) in nodes {
                let children = node["slots"]["children"]
                    .as_array()
                    .map(|a| {
                        a.iter()
                            .filter_map(|v| v.as_str().map(String::from))
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                let widgets = children
                    .iter()
                    .filter_map(|child| self.elements.get(child).map(|e| e.widget.clone()))
                    .collect::<Vec<_>>();
                if let Some(e) = self.elements.get_mut(element) {
                    if let Some(current) = e.child_widgets() {
                        if current != widgets {
                            e.detach_children();
                        }
                        if current != widgets || e.tabs.is_some() {
                            plans.push((element.clone(), children, widgets));
                        }
                    }
                    if let Some(container) = &e.container {
                        container.set_spacing(match node["props"]["spacing"].as_str() {
                            Some("compact") => 6,
                            Some("relaxed") => 20,
                            _ => 12,
                        });
                    }
                }
            }
            for (element, children, widgets) in plans {
                if let Some(e) = self.elements.get_mut(&element) {
                    if let Some(container) = &e.container {
                        for child in &widgets {
                            container.append(child);
                        }
                    }
                    if let Some(split) = &e.split {
                        split.set_children(&widgets[0], &widgets[1]).unwrap();
                    }
                    if let Some(tabs) = &e.tabs {
                        let labels = nodes[&element]["props"]["labels"].as_array().unwrap();
                        let pages = children
                            .iter()
                            .zip(&widgets)
                            .zip(labels)
                            .map(|((key, widget), title)| {
                                (
                                    key.clone(),
                                    title.as_str().unwrap().to_string(),
                                    widget.clone(),
                                )
                            })
                            .collect::<Vec<_>>();
                        tabs.set_pages(&pages).unwrap();
                    }
                    e.children = children;
                }
            }
            if let Some(root) = doc["root"].as_str() {
                if let Some(e) = self.elements.get(root) {
                    if root != self.root || self.scroll.child().as_ref() != Some(&e.widget) {
                        self.scroll.set_child(Some(&e.widget));
                        self.root = root.into();
                    }
                }
            }
            self.revision = doc["revision"].as_u64();
            self.document = doc.clone();
        }
        for (element, node) in nodes {
            if let Some(e) = self.elements.get_mut(element) {
                let props = &node["props"];
                if let Some(split) = &e.split {
                    split
                        .widget
                        .set_orientation(if props["axis"] == "vertical" {
                            gtk::Orientation::Vertical
                        } else {
                            gtk::Orientation::Horizontal
                        });
                    split
                        .widget
                        .update_property(&[gtk::accessible::Property::Label(
                            props["label"].as_str().unwrap(),
                        )]);
                }
                if let Some(tabs) = &e.tabs {
                    tabs.widget
                        .update_property(&[gtk::accessible::Property::Label(
                            props["label"].as_str().unwrap(),
                        )]);
                }
                if let Some(section) = &e.section {
                    let _ = section.set_label(props["label"].as_str().unwrap());
                }
                if let Some(region) = &e.region {
                    region
                        .widget
                        .update_property(&[gtk::accessible::Property::Label(
                            props["label"].as_str().unwrap(),
                        )]);
                }
                if e.table.is_some() || e.list.is_some() {
                    let rows = props["rows"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .map(|row| ui::TableRow {
                            id: row["id"].as_str().unwrap_or("").into(),
                            cells: row["cells"]
                                .as_array()
                                .into_iter()
                                .flatten()
                                .filter_map(Value::as_str)
                                .map(String::from)
                                .collect(),
                        })
                        .collect::<Vec<_>>();
                    let label = props["label"].as_str().unwrap_or("Collection");
                    if let Some(table) = e.table.as_mut() {
                        let _ = table.update(&rows);
                        table
                            .view
                            .update_property(&[gtk::accessible::Property::Label(label)]);
                    }
                    if let Some(list) = e.list.as_mut() {
                        let _ = list.update(&rows);
                        list.view
                            .update_property(&[gtk::accessible::Property::Label(label)]);
                    }
                }
                e.applying.set(true);
                if e.kind == "Image@1" && e.image.is_none() {
                    if let Some(label) = &e.label {
                        label.set_text(&format!(
                            "Image unavailable · {}",
                            props["label"].as_str().unwrap()
                        ));
                    }
                }
                if let Some(image) = &e.image {
                    let _ = image.set_label(props["label"].as_str().unwrap());
                }
                if let Some(chart) = e.chart.as_mut() {
                    let points =
                        serde_json::from_value::<Vec<ui::ChartPoint>>(props["points"].clone())
                            .unwrap();
                    let _ = chart.update(props["label"].as_str().unwrap(), &points);
                }
                if let Some(rich) = &e.rich {
                    let runs =
                        serde_json::from_value::<Vec<ui::RichRun>>(props["runs"].clone()).unwrap();
                    let _ = rich.reconcile(&runs);
                }
                if let Some(label) = &e.label {
                    if e.rich.is_none()
                        && e.kind != "Image@1"
                        && (e.kind == "Status@1"
                            || (!label.has_focus() && label.selection_bounds().is_none()))
                    {
                        let text = if e.kind == "Status@1" {
                            bound(id, &props["value"], frame)
                                .as_str()
                                .unwrap_or("Source unavailable")
                                .to_string()
                        } else {
                            props["text"]
                                .as_str()
                                .unwrap_or("Unsupported component")
                                .to_string()
                        };
                        if label.text() != text {
                            label.set_text(&text);
                        }
                    }
                }
                if e.field.is_some() || e.area.is_some() || e.choice.is_some() || e.toggle.is_some()
                {
                    if let Some(text) = editor_value(
                        id,
                        element,
                        doc["revision"].as_u64().unwrap_or(0),
                        props,
                        frame,
                        drafts,
                    ) {
                        if let Some(choice) = &e.choice {
                            let valid = choice.options().contains(&text);
                            if let Some(notice) = &e.selection_notice {
                                notice.set_visible(!valid);
                            }
                            if valid {
                                choice.reconcile(&text);
                            } else {
                                choice.control.set_selected(gtk::INVALID_LIST_POSITION);
                            }
                        }
                        if let Some(toggle) = &e.toggle {
                            let valid = text == "true" || text == "false";
                            if let Some(notice) = &e.selection_notice {
                                notice.set_visible(!valid);
                            }
                            if valid {
                                toggle.reconcile(text == "true");
                            }
                            toggle.control.set_inconsistent(!valid);
                        }
                        if let Some(field) = &e.field {
                            field.reconcile(&text);
                        }
                        if let Some(area) = &e.area {
                            area.reconcile(&text);
                        }
                    }
                }
                if let Some(choice) = &e.choice {
                    let label = props["label"].as_str().unwrap();
                    if let Some(heading) = choice
                        .widget
                        .first_child()
                        .and_then(|child| child.downcast::<gtk::Label>().ok())
                    {
                        heading.set_text(label);
                    }
                    choice
                        .control
                        .update_property(&[gtk::accessible::Property::Label(label)]);
                }
                if let Some(toggle) = &e.toggle {
                    let label = props["label"].as_str().unwrap();
                    toggle.control.set_label(Some(label));
                    toggle
                        .control
                        .update_property(&[gtk::accessible::Property::Label(label)]);
                }
                e.events.borrow_mut()["revision"] = doc["revision"].clone();
                if e.field.is_some() || e.area.is_some() {
                    let key = node["events"]["submit"]["action"].as_str().unwrap_or("");
                    let action = doc["actions"][key]["ref"].as_str();
                    *e.events.borrow_mut() = json!({"host_reference":action,"surface":id,"revision":doc["revision"],"action":key,"parameters":doc["actions"][key]["parameters"]});
                }
                if let Some(view) = &e.pty {
                    let job = props["source"]
                        .as_str()
                        .unwrap()
                        .strip_prefix("broker:")
                        .unwrap();
                    let available = frame.broker.as_array().is_some_and(|rows| {
                        rows.iter().any(|row| {
                            row["id"] == job
                                && row["terminal"] == true
                                && row["status"] == "running"
                                && row["activity"].as_i64().map(|id| id.to_string()).as_deref()
                                    == doc["activity_id"].as_str()
                        })
                    });
                    view.reconcile(props["label"].as_str().unwrap(), available);
                }
                if let Some(outcome) = &e.outcome {
                    let value = bound(
                        id,
                        &props[if e.kind == "Error@1" {
                            "message"
                        } else {
                            "value"
                        }],
                        frame,
                    );
                    let _ = outcome.reconcile(
                        props["label"].as_str().unwrap(),
                        value.as_str().unwrap_or("Unavailable"),
                    );
                    let key = node["events"]["recover"]["action"].as_str().unwrap_or("");
                    let action = doc["actions"][key]["ref"].as_str();
                    if let Some(action) = action {
                        let available = frame
                            .actions
                            .get(action)
                            .is_some_and(|info| info["available"] == true);
                        let _ = outcome.set_recovery(
                            props["recovery_label"].as_str().unwrap_or("Try again"),
                            available,
                        );
                    } else {
                        outcome.recovery.set_visible(false);
                        outcome.recovery.set_sensitive(false);
                    }
                    *e.events.borrow_mut() = json!({"host_reference":action,"surface":id,"revision":doc["revision"],"action":key,"parameters":doc["actions"][key]["parameters"]});
                }
                if let Some(reference) = &e.reference {
                    let target = props["target"].as_str().unwrap();
                    let available = if e.kind == "DocumentReference@1" {
                        frame.documents.get(target).is_some_and(|target| {
                            target.get("surface_id").is_some()
                                && target["activity_id"] == doc["activity_id"]
                        })
                    } else {
                        frame.host_surfaces[target]["availability"] == "available"
                            && frame.host_surfaces[target]["activity_id"] == doc["activity_id"]
                    };
                    let _ = reference.reconcile(props["label"].as_str().unwrap(), available);
                    *e.events.borrow_mut() = json!({"surface":id,"revision":doc["revision"]});
                }
                if let Some(button) = &e.button {
                    button.set_label(props["label"].as_str().unwrap_or("Action"));
                    let action = node["events"]["activate"]["action"]
                        .as_str()
                        .and_then(|key| doc["actions"][key]["ref"].as_str());
                    let available = action
                        .and_then(|reference| frame.actions.get(reference))
                        .map(|a| a["available"] == true)
                        .unwrap_or(false);
                    button.set_sensitive(props["disabled"] != true && available);
                    let key = node["events"]["activate"]["action"].as_str().unwrap_or("");
                    *e.events.borrow_mut() = json!({"host_reference":action,"surface":id,"revision":doc["revision"],"action":key,"parameters":doc["actions"][key]["parameters"]});
                }
                if let Some(progress) = &e.progress {
                    let value = bound(id, &props["value"], frame);
                    progress.set_text(Some(props["label"].as_str().unwrap_or("Work")));
                    if let Some(value) = value
                        .as_f64()
                        .filter(|n| n.is_finite() && (0.0..=1.0).contains(n))
                    {
                        progress.set_fraction(value);
                    } else {
                        progress.set_text(Some("Source unavailable"));
                        progress.set_fraction(0.0);
                    }
                }
                if let Some(link) = &e.link {
                    link.set_label(props["label"].as_str().unwrap_or("Link"));
                    if let Some(url) = props["url"].as_str() {
                        link.set_uri(url);
                    }
                }
                e.applying.set(false);
            }
        }
    }
}
fn main() {
    let args = std::env::args().collect::<Vec<_>>();
    let option = |name: &str| {
        args.iter()
            .position(|s| s == name)
            .and_then(|i| args.get(i + 1))
            .cloned()
    };
    let socket =
        PathBuf::from(option("--socket").unwrap_or_else(|| "/run/agent-os/runtime.sock".into()));
    if args.iter().any(|a| a == "--self-test") {
        verification::run(socket, option("--capture"));
        return;
    }
    let backend = Rc::new(RefCell::new(Backend::start(socket, option("--activity"))));
    let app = gtk::Application::builder()
        .application_id("com.agentos.Desktop")
        .build();
    let frontend = backend.clone();
    app.connect_activate(move |app| {
        let display = gtk::gdk::Display::default().expect("A native Wayland display is required");
        ui::install_theme(&display, Appearance::Dark, 1.0, false);
        let bar = ui::row(20);
        bar.add_css_class("seven-ui");
        bar.set_margin_top(12);
        bar.set_margin_bottom(12);
        bar.set_margin_start(20);
        bar.set_margin_end(20);
        let clock = ui::text("", false);
        let user = ui::text(
            &std::env::var("USER").unwrap_or_else(|_| "Local user".into()),
            false,
        );
        let status = ui::button("Connecting…", ButtonVariant::Ghost, false);
        bar.append(&clock);
        bar.append(&user);
        bar.append(&status);
        let logout=ui::button("End desktop session",ButtonVariant::Outline,false);
        let desktop=app.clone();logout.connect_clicked(move |_|desktop.quit());
        bar.append(&logout);
        let controls = Rc::new(RefCell::new(controls::Controls::new(
            app,
            frontend.borrow().commands.clone(),
        )));
        let content = ui::column(12);
        content.append(&bar);
        content.append(&controls.borrow().widget);
        let scroll=gtk::ScrolledWindow::builder().hscrollbar_policy(gtk::PolicyType::Never).child(&content).build();
        let main = gtk::ApplicationWindow::builder()
            .application(app)
            .title("agentOS")
            .default_width(800)
            .default_height(330)
            .child(&scroll)
            .build();
        main.add_css_class("seven-ui");
        main.present();
        first_run::present(app,frontend.borrow().commands.clone());
        let voice_cleanup=controls.clone();app.connect_shutdown(move |_|voice_cleanup.borrow().close());
        let opener = controls.clone();
        status.connect_clicked(move |_| opener.borrow().present());
        let surfaces = Rc::new(RefCell::new(BTreeMap::<String, Surface>::new()));
        let frontend = frontend.clone();
        let application = app.clone();
        glib::timeout_add_local(Duration::from_millis(50), move || {
            let backend = frontend.borrow();
            let frame = backend.frame.lock().unwrap().clone();
            if let Ok(now) = glib::DateTime::now_local() {
                if let Ok(text) = now.format("%a %e %b · %H:%M") {
                    clock.set_text(&text);
                }
            }
            let connection = if frame.connected {
                "Agent Monitor"
            } else {
                "Connection unavailable"
            };
            status.set_label(connection);
            controls.borrow_mut().update(&frame, &backend.commands);
            if let Some(activity)=frame.activity.as_ref().and_then(|a|a.parse::<i64>().ok()) {
                let mut context=json!({"activity_id":activity,"surface_id":"native-launcher","layout_revision":0,"job_ref":null,"selection":"","selection_kind":"focused_output","surface_title":"Agent request"});
                for (id,surface) in surfaces.borrow().iter(){
                    let selection=surface.elements.values().filter_map(|e|e.label.as_ref()).find_map(|label|label.selection_bounds().map(|(a,b)|label.text().chars().skip(a.min(b) as usize).take((b-a).unsigned_abs() as usize).collect::<String>()));
                    if surface.window.is_active() || selection.is_some(){let mut selected=selection.unwrap_or_default();while selected.len()>8000{selected.pop();}context["surface_id"]=json!(id);context["layout_revision"]=json!(surface.revision.unwrap_or(0));context["selection"]=json!(selected);context["surface_title"]=surface.document["title"].clone();break;}
                }
                controls.borrow().context(context);
            }
            let mut surfaces = surfaces.borrow_mut();
            for (id, doc) in &frame.documents {
                if doc.get("surface_id").is_some() {
                    let surface = surfaces
                        .entry(id.clone())
                        .or_insert_with(|| Surface::new(&application, id, &backend.commands));
                    surface.update(id, doc, &frame, &backend.commands, &backend.drafts);
                }
            }
            if frame.connected {
                let removed = surfaces
                    .keys()
                    .filter(|id| !frame.documents.contains_key(*id))
                    .cloned()
                    .collect::<Vec<_>>();
                for id in removed {
                    if let Some(surface) = surfaces.remove(&id) {
                        surface.window.destroy();
                    }
                }
            }
            glib::ControlFlow::Continue
        });
    });
    let cleanup = backend.clone();
    app.connect_shutdown(move |_| cleanup.borrow_mut().close());
    app.run_with_args(&["agent-os-desktop"]);
}
