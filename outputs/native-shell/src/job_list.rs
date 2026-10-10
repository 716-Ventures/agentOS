//! Stable work identities in a virtualized GTK list; recycled controls resolve current data.
use super::*;
#[derive(Clone)]
struct Item {
    key: String,
    source: String,
    job: Value,
    available: bool,
}
#[derive(Clone)]
struct Row {
    widget: gtk::Box,
    label: gtk::Label,
    stop: gtk::Button,
    review: gtk::Button,
    attach: gtk::Button,
    inspect: gtk::Button,
    resume: gtk::Button,
    current: Rc<RefCell<Option<Item>>>,
}
impl Row {
    fn new(app: &gtk::Application, commands: &Sender<Command>) -> Self {
        let widget = ui::column(8);
        let label = ui::text("", false);
        widget.append(&label);
        let inspect = ui::button("Read output", ButtonVariant::Outline, false);
        let stop = ui::button("Stop work", ButtonVariant::Destructive, false);
        let review = ui::button("Review approval", ButtonVariant::Outline, false);
        let attach = ui::button("Attach terminal", ButtonVariant::Outline, false);
        let actions = gtk::FlowBox::new();
        actions.set_selection_mode(gtk::SelectionMode::None);
        actions.set_min_children_per_line(1);
        actions.set_max_children_per_line(4);
        actions.set_column_spacing(8);
        actions.set_row_spacing(8);
        for button in [&inspect, &stop, &review, &attach] {
            actions.insert(button, -1);
        }
        widget.append(&actions);
        let resume = ui::button("Continue request", ButtonVariant::Outline, false);
        actions.insert(&resume, -1);
        let current = Rc::new(RefCell::new(None::<Item>));
        let (data, sender) = (current.clone(), commands.clone());
        resume.connect_clicked(move |_| {
            if let Some(item) = data.borrow().as_ref() {
                let _ = sender.send(Command::Resume(item.job.clone()));
            }
        });
        let (data, sender, app) = (current.clone(), commands.clone(), app.clone());
        review.connect_clicked(move |_| {
            if let Some(item) = data.borrow().as_ref() {
                super::controls::review_proposal(&app, item.job.clone(), sender.clone());
            }
        });
        let (data, sender) = (current.clone(), commands.clone());
        attach.connect_clicked(move |_| {
            if let Some(item) = data.borrow().as_ref() {
                let _ = sender.send(Command::Attach(item.job.clone()));
            }
        });
        for (button, inspect) in [(&inspect, true), (&stop, false)] {
            let (data, sender) = (current.clone(), commands.clone());
            button.connect_clicked(move |_| {
                if let Some(item) = data.borrow().as_ref() {
                    let _ = sender.send(if inspect {
                        Command::Inspect {
                            source: item.source.clone(),
                            job: item.job["id"].clone(),
                        }
                    } else {
                        Command::Stop {
                            source: item.source.clone(),
                            job: item.job["id"].clone(),
                        }
                    });
                }
            });
        }
        Self {
            widget,
            label,
            stop,
            review,
            attach,
            inspect,
            resume,
            current,
        }
    }
    fn update(&self, item: &Item) {
        let argv = item.job["argv"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(Value::as_str)
                    .collect::<Vec<_>>()
                    .join(" ")
            })
            .unwrap_or_default();
        let status = item.job["status"].as_str().unwrap_or("unavailable");
        let text = format!(
            "{} · {}{}\n{}",
            item.source,
            status,
            if item.available {
                ""
            } else {
                " · service unavailable"
            },
            argv
        );
        if self.label.text() != text {
            self.label.set_text(&text);
        }
        self.review.set_sensitive(
            item.available && item.source == "broker" && status == "approval_required",
        );
        self.attach.set_sensitive(
            item.available
                && item.source == "broker"
                && status == "running"
                && item.job["terminal"] == true,
        );
        self.stop.set_sensitive(
            item.available
                && matches!(
                    status,
                    "starting" | "running" | "cancelling" | "approval_required"
                ),
        );
        self.inspect.set_sensitive(item.available);
        self.resume.set_sensitive(
            item.available
                && item.source == "broker"
                && super::broker_controls::continuation_request(&item.job).is_some(),
        );
        *self.current.borrow_mut() = Some(item.clone());
    }
    fn clear(&self) {
        *self.current.borrow_mut() = None;
        for button in [
            &self.stop,
            &self.review,
            &self.attach,
            &self.inspect,
            &self.resume,
        ] {
            button.set_sensitive(false);
        }
    }
}
pub struct JobList {
    pub widget: gtk::ScrolledWindow,
    store: gtk::gio::ListStore,
    items: BTreeMap<String, glib::BoxedAnyObject>,
    rows: Rc<RefCell<BTreeMap<usize, Row>>>,
    bound: Rc<RefCell<BTreeMap<String, usize>>>,
}
impl JobList {
    pub fn new(app: &gtk::Application, commands: &Sender<Command>) -> Self {
        let store = gtk::gio::ListStore::new::<glib::BoxedAnyObject>();
        let factory = gtk::SignalListItemFactory::new();
        let rows = Rc::new(RefCell::new(BTreeMap::<usize, Row>::new()));
        let bound = Rc::new(RefCell::new(BTreeMap::<String, usize>::new()));
        let (cells, app, commands) = (rows.clone(), app.clone(), commands.clone());
        factory.connect_setup(move |_, object| {
            let item = object.downcast_ref::<gtk::ListItem>().unwrap();
            let row = Row::new(&app, &commands);
            item.set_child(Some(&row.widget));
            cells.borrow_mut().insert(item.as_ptr() as usize, row);
        });
        let (cells, bindings) = (rows.clone(), bound.clone());
        factory.connect_bind(move |_, object| {
            let list_item = object.downcast_ref::<gtk::ListItem>().unwrap();
            let object = list_item
                .item()
                .unwrap()
                .downcast::<glib::BoxedAnyObject>()
                .unwrap();
            let item = object.borrow::<Item>();
            let pointer = list_item.as_ptr() as usize;
            cells.borrow()[&pointer].update(&item);
            bindings.borrow_mut().insert(item.key.clone(), pointer);
        });
        let (cells, bindings) = (rows.clone(), bound.clone());
        factory.connect_unbind(move |_, object| {
            let pointer = object.as_ptr() as usize;
            if let Some(row) = cells.borrow().get(&pointer) {
                if let Some(item) = row.current.borrow().as_ref() {
                    let mut bound = bindings.borrow_mut();
                    if bound.get(&item.key) == Some(&pointer) {
                        bound.remove(&item.key);
                    }
                }
                row.clear();
            }
        });
        let cells = rows.clone();
        factory.connect_teardown(move |_, object| {
            cells.borrow_mut().remove(&(object.as_ptr() as usize));
        });
        let selection = gtk::NoSelection::new(Some(store.clone()));
        let view = gtk::ListView::new(Some(selection), Some(factory));
        view.set_single_click_activate(false);
        view.update_property(&[gtk::accessible::Property::Label("Work history")]);
        let widget = gtk::ScrolledWindow::builder()
            .hscrollbar_policy(gtk::PolicyType::Never)
            .min_content_height(320)
            .max_content_height(480)
            .propagate_natural_height(true)
            .child(&view)
            .build();
        Self {
            widget,
            store,
            items: BTreeMap::new(),
            rows,
            bound,
        }
    }
    pub fn update(&mut self, frame: &Frame) {
        let mut seen = std::collections::BTreeSet::new();
        for (source, rows) in [
            ("core", frame.core["jobs"].as_array()),
            ("broker", frame.broker.as_array()),
        ] {
            if rows.is_none() {
                for (key, object) in &self.items {
                    if key.starts_with(&format!("{source}:")) {
                        seen.insert(key.clone());
                        let mut item = object.borrow_mut::<Item>();
                        item.available = false;
                        if let Some(pointer) = self.bound.borrow().get(key) {
                            if let Some(row) = self.rows.borrow().get(pointer) {
                                row.update(&item);
                            }
                        }
                    }
                }
            }
            for job in rows.into_iter().flatten() {
                let key = format!("{}:{}", source, job["id"]);
                seen.insert(key.clone());
                let item = Item {
                    key: key.clone(),
                    source: source.into(),
                    job: job.clone(),
                    available: true,
                };
                if let Some(object) = self.items.get(&key) {
                    let mut previous = object.borrow_mut::<Item>();
                    if previous.job != item.job || previous.available != item.available {
                        *previous = item.clone();
                        if let Some(pointer) = self.bound.borrow().get(&key) {
                            if let Some(row) = self.rows.borrow().get(pointer) {
                                row.update(&item);
                            }
                        }
                    }
                } else {
                    let object = glib::BoxedAnyObject::new(item);
                    self.items.insert(key, object.clone());
                    self.store.append(&object);
                }
            }
        }
        for index in (0..self.store.n_items()).rev() {
            let object = self
                .store
                .item(index)
                .unwrap()
                .downcast::<glib::BoxedAnyObject>()
                .unwrap();
            let key = object.borrow::<Item>().key.clone();
            if !seen.contains(&key) {
                self.store.remove(index);
                self.items.remove(&key);
            }
        }
    }
    pub fn verify_initial(&self) {
        assert!(self
            .rows
            .borrow()
            .values()
            .all(|row| !row.stop.is_sensitive()));
    }
    pub fn verify_virtualization(&mut self, frame: &Frame, commands: &Sender<Command>) {
        let mut fixture = frame.clone();
        fixture.broker = json!([]);
        fixture.core["jobs"] = json!((1..=4000)
            .map(|id| json!({"id":id,"status":"running","argv":["fixture",id.to_string()]}))
            .collect::<Vec<_>>());
        self.update(&fixture);
        for _ in 0..32 {
            if glib::MainContext::default().pending() {
                glib::MainContext::default().iteration(false);
            } else {
                break;
            }
        }
        assert_eq!(self.store.n_items(), 4000);
        assert!(
            self.rows.borrow().len() < 500,
            "GTK must not construct a widget for every history entry"
        );
        let original = self.items["core:1"].clone();
        fixture.core["jobs"][0]["status"] = json!("succeeded");
        self.update(&fixture);
        assert_eq!(self.items["core:1"], original);
        if let Some(pointer) = self.bound.borrow().get("core:1") {
            let row = &self.rows.borrow()[pointer];
            assert!(!row.stop.is_sensitive());
            row.inspect.emit_clicked();
        }
        fixture.core["jobs"] = json!([]);
        self.update(&fixture);
        for _ in 0..32 {
            if glib::MainContext::default().pending() {
                glib::MainContext::default().iteration(false);
            } else {
                break;
            }
        }
        assert_eq!(self.store.n_items(), 0);
        // Recycled or unbound controls must never retain a previous command target.
        for row in self.rows.borrow().values() {
            assert!(row.current.borrow().is_none());
        }
        let _ = commands;
        self.update(frame);
    }
}
