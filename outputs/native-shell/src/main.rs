//! Native shell client: stable GTK controls over the core's inert presentation API.
mod broker_controls;
mod controls;
mod draft_cache;
mod log_view;
mod preferences;
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
    field: Option<TextField>,
    area: Option<ui::TextArea>,
    button: Option<gtk::Button>,
    progress: Option<gtk::ProgressBar>,
    container: Option<gtk::Box>,
    link: Option<gtk::LinkButton>,
    events: Rc<RefCell<Value>>,
    applying: Rc<Cell<bool>>,
    children: Vec<String>,
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
        field: None,
        area: None,
        button: None,
        progress: None,
        container: None,
        link: None,
        events: events.clone(),
        applying: applying.clone(),
        children: Vec::new(),
    };
    match kind.as_str() {
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
        "TextField@1" => {
            let recovered = frame.drafts.get(&(surface.into(), id.into()));
            let value = recovered
                .and_then(|d| d["draft"].as_str())
                .or_else(|| props["value"].as_str())
                .unwrap_or("");
            if props["multiline"] == true {
                let area = ui::TextArea::new(props["label"].as_str().unwrap_or("Text"), value);
                let (s, e, edits, applying) = (
                    surface.to_string(),
                    id.to_string(),
                    drafts.clone(),
                    applying.clone(),
                );
                let expected = recovered
                    .and_then(|d| d["draft_revision"].as_u64())
                    .unwrap_or(0);
                area.on_event(move |event| {
                    if applying.get() {
                        return;
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
                draft_controls(&area.widget, surface, id, commands);
                result.widget = area.widget.clone().upcast();
                lease(&area.view.clone().upcast(), surface, id, commands);
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
            field.on_event(move |event| {
                if applying.get() {
                    return;
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
            draft_controls(&field.widget, surface, id, commands);
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
            button.connect_clicked(move |_| {
                let event = events.borrow();
                if let Some(reference) = event["host_reference"].as_str() {
                    let _ = commands.send(Command::Action {
                        reference: reference.into(),
                        key: format!("native-{}", nonce()),
                    });
                }
            });
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
fn draft_controls(widget: &gtk::Box, surface: &str, element: &str, commands: &Sender<Command>) {
    let row = ui::row(8);
    for (label, commit) in [("Save draft", true), ("Discard draft", false)] {
        let button = ui::button(label, ButtonVariant::Outline, false);
        let (sender, s, e) = (commands.clone(), surface.to_string(), element.to_string());
        button.connect_clicked(move |_| {
            let _ = sender.send(Command::ResolveDraft {
                surface: s.clone(),
                element: e.clone(),
                commit,
            });
        });
        row.append(&button);
    }
    widget.append(&row);
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
            .or_else(|| props["value"].as_str())
            .unwrap_or("")
            .into(),
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
        let window = gtk::ApplicationWindow::builder()
            .application(app)
            .title("agentOS surface")
            .default_width(700)
            .default_height(500)
            .child(&scroll)
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
                || e.area
                    .as_ref()
                    .map(|a| {
                        a.view.has_focus()
                            || a.view.is_focus()
                            || a.view.buffer().selection_bounds().is_some()
                    })
                    .unwrap_or(false)
                || e.label
                    .as_ref()
                    .map(|l| l.selection_bounds().is_some())
                    .unwrap_or(false)
        }) || drafts
            .lock()
            .unwrap()
            .iter()
            .any(|((s, _), d)| s == id && (d.dirty || d.resolved.is_none()));
        let changed = doc["revision"].as_u64() != self.revision;
        if changed && protected && self.revision.is_some() {
            let retained = self.document.clone();
            self.update(id, &retained, frame, commands, drafts);
            return;
        }
        if changed {
            self.window
                .set_title(Some(doc["title"].as_str().unwrap_or("Work")));
            for (element, node) in nodes {
                if self
                    .elements
                    .get(element)
                    .map(|e| {
                        Some(e.kind.as_str()) != node["type"].as_str()
                            || (e.kind == "TextField@1"
                                && e.area.is_some() != (node["props"]["multiline"] == true))
                    })
                    .unwrap_or(true)
                {
                    self.elements.insert(
                        element.clone(),
                        construct(id, element, node, frame, commands, drafts),
                    );
                }
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
                    if let Some(container) = &e.container {
                        let mut current = Vec::new();
                        let mut child = container.first_child();
                        while let Some(widget) = child {
                            child = widget.next_sibling();
                            current.push(widget);
                        }
                        if current != widgets {
                            while let Some(child) = container.first_child() {
                                container.remove(&child);
                            }
                            plans.push((element.clone(), children, widgets));
                        }
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
                        for child in widgets {
                            container.append(&child);
                        }
                        e.children = children;
                    }
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
                e.applying.set(true);
                if let Some(label) = &e.label {
                    if e.kind == "Status@1"
                        || (!label.has_focus() && label.selection_bounds().is_none())
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
                if e.field.is_some() || e.area.is_some() {
                    if let Some(text) = editor_value(
                        id,
                        element,
                        doc["revision"].as_u64().unwrap_or(0),
                        props,
                        frame,
                        drafts,
                    ) {
                        if let Some(field) = &e.field {
                            field.reconcile(&text);
                        }
                        if let Some(area) = &e.area {
                            area.reconcile(&text);
                        }
                    }
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
                    *e.events.borrow_mut() = json!({"host_reference":action});
                }
                if let Some(progress) = &e.progress {
                    let value = bound(id, &props["value"], frame);
                    progress.set_text(Some(props["label"].as_str().unwrap_or("Work")));
                    if let Some(value) = value.as_f64() {
                        progress.set_fraction(value.clamp(0.0, 1.0));
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
