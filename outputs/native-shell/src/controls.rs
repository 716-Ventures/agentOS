//! Direct human controls; authority is dispatched through the existing core/broker.
use super::*;
struct JobRow {
    widget: gtk::Box,
    label: gtk::Label,
    stop: gtk::Button,
}
pub struct Controls {
    pub widget: gtk::Box,
    activity: Rc<RefCell<Option<String>>>,
    chooser: gtk::DropDown,
    choices: Rc<RefCell<Vec<String>>>,
    chooser_model: gtk::StringList,
    changing: Rc<Cell<bool>>,
    monitor: gtk::ApplicationWindow,
    jobs: gtk::Box,
    rows: BTreeMap<String, JobRow>,
    message: gtk::Label,
    model_text: gtk::Label,
    inspection: gtk::TextView,
}
impl Controls {
    pub fn new(app: &gtk::Application, commands: Sender<Command>) -> Self {
        let widget = ui::column(12);
        widget.set_margin_start(20);
        widget.set_margin_end(20);
        widget.set_margin_bottom(16);
        let activity = Rc::new(RefCell::new(None));
        let choices = Rc::new(RefCell::new(Vec::<String>::new()));
        let changing = Rc::new(Cell::new(false));
        let chooser_model = gtk::StringList::new(&[]);
        let chooser = gtk::DropDown::new(Some(chooser_model.clone()), gtk::Expression::NONE);
        chooser.update_property(&[gtk::accessible::Property::Label("Current activity")]);
        let (ids, changing_now, commands_now) =
            (choices.clone(), changing.clone(), commands.clone());
        chooser.connect_selected_notify(move |control| {
            if changing_now.get() {
                return;
            }
            if let Some(id) = ids.borrow().get(control.selected() as usize) {
                let _ = commands_now.send(Command::SelectActivity(id.clone()));
            }
        });
        let activity_row = ui::row(12);
        activity_row.append(&chooser);
        let name = TextField::new("New activity", "Activity name", "");
        activity_row.append(&name.widget);
        let new = ui::button("Create activity", ButtonVariant::Outline, false);
        activity_row.append(&new);
        let commands_now = commands.clone();
        new.connect_clicked(move |_| {
            if !name.entry.text().trim().is_empty() {
                let _ = commands_now.send(Command::CreateActivity(name.entry.text().into()));
            }
        });
        widget.append(&activity_row);
        let request = TextField::new("Ask Agent", "Describe the work you want done", "");
        widget.append(&request.widget);
        let send = ui::button("Send request", ButtonVariant::Primary, false);
        widget.append(&send);
        let (current, commands_now, entry) =
            (activity.clone(), commands.clone(), request.entry.clone());
        let submit = Rc::new(move || {
            let id = current
                .borrow()
                .as_ref()
                .and_then(|s: &String| s.parse::<i64>().ok());
            if let Some(activity) = id {
                let _ = commands_now.send(Command::Ask {
                    activity,
                    prompt: entry.text().into(),
                    grounding: None,
                });
            }
        });
        let click = submit.clone();
        send.connect_clicked(move |_| click());
        request.entry.connect_activate(move |_| submit());
        let message = ui::status("Select or create an activity to start work.");
        widget.append(&message);
        let monitor_content = ui::column(16);
        for side in [0, 1, 2, 3] {
            match side {
                0 => monitor_content.set_margin_top(20),
                1 => monitor_content.set_margin_bottom(20),
                2 => monitor_content.set_margin_start(20),
                _ => monitor_content.set_margin_end(20),
            }
        }
        monitor_content.append(&ui::text("Agent Monitor", true));
        let model_text = ui::text("Model configuration and measured usage unavailable", false);
        monitor_content.append(&model_text);
        let jobs = ui::column(12);
        monitor_content.append(&jobs);
        let inspection = gtk::TextView::new();
        inspection.set_editable(false);
        inspection.set_cursor_visible(true);
        inspection.set_monospace(true);
        inspection.set_wrap_mode(gtk::WrapMode::WordChar);
        inspection.update_property(&[gtk::accessible::Property::Label("Selected work output")]);
        monitor_content.append(&inspection);
        let scroll = gtk::ScrolledWindow::builder()
            .hscrollbar_policy(gtk::PolicyType::Never)
            .child(&monitor_content)
            .build();
        let monitor = gtk::ApplicationWindow::builder()
            .application(app)
            .title("Agent Monitor")
            .default_width(720)
            .default_height(600)
            .child(&scroll)
            .build();
        monitor.add_css_class("seven-ui");
        monitor.connect_close_request(|window| {
            window.set_visible(false);
            glib::Propagation::Stop
        });
        Self {
            widget,
            activity,
            chooser,
            choices,
            chooser_model,
            changing,
            monitor,
            jobs,
            rows: BTreeMap::new(),
            message,
            model_text,
            inspection,
        }
    }
    pub fn present(&self) {
        self.monitor.present();
    }
    pub fn update(&mut self, frame: &Frame, commands: &Sender<Command>) {
        *self.activity.borrow_mut() = frame.activity.clone();
        let activities = frame.core["activities"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        let ids = activities
            .iter()
            .map(|a| a["id"].to_string())
            .collect::<Vec<_>>();
        let names = activities
            .iter()
            .map(|a| a["name"].as_str().unwrap_or("Activity"))
            .collect::<Vec<_>>();
        self.changing.set(true);
        if *self.choices.borrow() != ids
            || (0..self.chooser_model.n_items())
                .map(|i| self.chooser_model.string(i).unwrap().to_string())
                .collect::<Vec<_>>()
                != names
        {
            self.chooser_model
                .splice(0, self.chooser_model.n_items(), &names);
            *self.choices.borrow_mut() = ids.clone();
        }
        self.chooser.set_selected(
            ids.iter()
                .position(|id| Some(id) == frame.activity.as_ref())
                .map(|i| i as u32)
                .unwrap_or(gtk::INVALID_LIST_POSITION),
        );
        self.changing.set(false);
        self.message.set_text(
            frame
                .error
                .as_deref()
                .or(frame.notice.as_deref())
                .unwrap_or(if frame.connected {
                    "Ready"
                } else {
                    "Core unavailable · reconnecting"
                }),
        );
        let mut seen = Vec::new();
        for (source, rows) in [
            ("core", frame.core["jobs"].as_array()),
            ("broker", frame.broker.as_array()),
        ] {
            for job in rows.into_iter().flatten() {
                let key = format!("{}:{}", source, job["id"]);
                seen.push(key.clone());
                let row = self.rows.entry(key).or_insert_with(|| {
                    let widget = ui::row(12);
                    let label = ui::text("", false);
                    widget.append(&label);
                    let inspect = ui::button("Read output", ButtonVariant::Outline, false);
                    let stop = ui::button("Stop work", ButtonVariant::Destructive, false);
                    widget.append(&inspect);
                    widget.append(&stop);
                    self.jobs.append(&widget);
                    let (sender, source_name, id) =
                        (commands.clone(), source.to_string(), job["id"].clone());
                    inspect.connect_clicked(move |_| {
                        let _ = sender.send(Command::Inspect {
                            source: source_name.clone(),
                            job: id.clone(),
                        });
                    });
                    let (sender, source_name, id) =
                        (commands.clone(), source.to_string(), job["id"].clone());
                    stop.connect_clicked(move |_| {
                        let _ = sender.send(Command::Stop {
                            source: source_name.clone(),
                            job: id.clone(),
                        });
                    });
                    JobRow {
                        widget,
                        label,
                        stop,
                    }
                });
                let argv = job["argv"]
                    .as_array()
                    .map(|a| {
                        a.iter()
                            .filter_map(Value::as_str)
                            .collect::<Vec<_>>()
                            .join(" ")
                    })
                    .unwrap_or_default();
                let status = job["status"].as_str().unwrap_or("unavailable");
                row.label
                    .set_text(&format!("{} · {}\n{}", source, status, argv));
                row.stop.set_sensitive(matches!(
                    status,
                    "starting" | "running" | "cancelling" | "approval_required"
                ));
            }
        }
        self.rows.retain(|id, row| {
            if seen.contains(id) {
                true
            } else {
                self.jobs.remove(&row.widget);
                false
            }
        });
        let usage = if frame.usage["unavailable"] == true {
            "Model configuration and measured usage unavailable".into()
        } else {
            format!(
                "Model configuration and measured usage\n{}",
                serde_json::to_string_pretty(&frame.usage).unwrap_or_default()
            )
        };
        if self.model_text.text() != usage {
            self.model_text.set_text(&usage);
        }
        if let Some(output) = &frame.inspection {
            let buffer = self.inspection.buffer();
            if buffer.text(&buffer.start_iter(), &buffer.end_iter(), false) != output.as_str() {
                buffer.set_text(output);
            }
        }
    }
}
