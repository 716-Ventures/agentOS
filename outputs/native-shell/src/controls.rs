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
    voice: voice::Voice,
    voice_button: gtk::Button,
    voice_status: gtk::Label,
    voice_context: Rc<RefCell<Value>>,
    review: gtk::ApplicationWindow,
    transcript: TextField,
    review_ready: bool,
}
impl Controls {
    pub fn new(app: &gtk::Application, commands: Sender<Command>) -> Self {
        let widget = ui::column(12);
        widget.set_margin_start(20);
        widget.set_margin_end(20);
        widget.set_margin_bottom(16);
        let setup = ui::button(
            "Setup network, audio and providers",
            ButtonVariant::Outline,
            false,
        );
        let sender = commands.clone();
        setup.connect_clicked(move |_| {
            let _ = sender.send(Command::Setup);
        });
        widget.append(&setup);
        let appearance = gtk::DropDown::from_strings(&["Dark", "Light"]);
        let scale = gtk::SpinButton::with_range(1.0, 3.0, 0.25);
        scale.set_value(1.0);
        let reduced = gtk::CheckButton::with_label("Reduce motion");
        appearance.update_property(&[gtk::accessible::Property::Label("Appearance")]);
        scale.update_property(&[gtk::accessible::Property::Label("Text scale")]);
        let appearance_row = ui::row(12);
        appearance_row.append(&appearance);
        appearance_row.append(&ui::text("Text scale", false));
        appearance_row.append(&scale);
        appearance_row.append(&reduced);
        widget.append(&appearance_row);
        let (a, s, r) = (appearance.clone(), scale.clone(), reduced.clone());
        let theme = Rc::new(move || {
            if let Some(display) = gtk::gdk::Display::default() {
                ui::install_theme(
                    &display,
                    if a.selected() == 0 {
                        Appearance::Dark
                    } else {
                        Appearance::Light
                    },
                    s.value(),
                    r.is_active(),
                );
            }
        });
        let change = theme.clone();
        appearance.connect_selected_notify(move |_| change());
        let change = theme.clone();
        scale.connect_value_changed(move |_| change());
        reduced.connect_toggled(move |_| theme());
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
        let voice = voice::Voice::new();
        let voice_context = Rc::new(RefCell::new(Value::Null));
        let voice_button = ui::button("Record voice", ButtonVariant::Outline, false);
        let voice_status = ui::status("Microphone idle");
        let voice_row = ui::row(12);
        voice_row.append(&voice_button);
        voice_row.append(&voice_status);
        widget.append(&voice_row);
        let review_content = ui::column(12);
        review_content.append(&ui::text("Review voice request", true));
        let transcript = TextField::new("Edit the transcript before sending", "Transcript", "");
        review_content.append(&transcript.widget);
        let review_actions = ui::row(12);
        let send_voice = ui::button("Send reviewed request", ButtonVariant::Primary, false);
        let discard = ui::button("Discard recording", ButtonVariant::Outline, false);
        review_actions.append(&send_voice);
        review_actions.append(&discard);
        review_content.append(&review_actions);
        let review = gtk::ApplicationWindow::builder()
            .application(app)
            .title("Review voice request")
            .default_width(700)
            .default_height(220)
            .child(&review_content)
            .build();
        review.add_css_class("seven-ui");
        let recorder = voice.clone();
        let context = voice_context.clone();
        voice_button.connect_clicked(move |_| {
            let phase = recorder.state.lock().unwrap().phase.clone();
            if phase == "recording" {
                recorder.finish();
            } else if phase == "idle" {
                let context = context.borrow().clone();
                if !context.is_null() {
                    recorder.start(context);
                }
            }
        });
        let recorder = voice.clone();
        let window = review.clone();
        discard.connect_clicked(move |_| {
            recorder.cancel();
            window.set_visible(false);
        });
        let recorder = voice.clone();
        review.connect_close_request(move |window| {
            recorder.cancel();
            window.set_visible(false);
            glib::Propagation::Stop
        });
        let recorder = voice.clone();
        let window = review.clone();
        let entry = transcript.entry.clone();
        let sender = commands.clone();
        send_voice.connect_clicked(move |_| {
            if entry.text().trim().is_empty() {
                return;
            }
            if let Some(context) = recorder.consume() {
                if let Some(activity) = context["activity_id"].as_i64() {
                    let _ = sender.send(Command::Ask {
                        activity,
                        prompt: entry.text().into(),
                        grounding: Some(context),
                    });
                    window.set_visible(false);
                }
            }
        });
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
            voice,
            voice_button,
            voice_status,
            voice_context,
            review,
            transcript,
            review_ready: false,
        }
    }
    pub fn context(&self, context: Value) {
        *self.voice_context.borrow_mut() = context;
    }
    pub fn close(&self) {
        self.voice.cancel();
    }
    pub fn present(&self) {
        self.monitor.present();
    }
    pub fn update(&mut self, frame: &Frame, commands: &Sender<Command>) {
        *self.activity.borrow_mut() = frame.activity.clone();
        let voice = self.voice.state.lock().unwrap().clone();
        self.voice_button.set_label(if voice.phase == "recording" {
            "Finish recording"
        } else {
            "Record voice"
        });
        self.voice_button
            .set_sensitive(matches!(voice.phase.as_str(), "idle" | "recording"));
        self.voice_status.set_text(
            voice
                .error
                .as_deref()
                .unwrap_or(match voice.phase.as_str() {
                    "idle" => "Microphone idle",
                    "starting" => "Starting microphone…",
                    "recording" => "Recording · finish or discard",
                    "transcribing" => "Recognizing speech locally…",
                    "review" => "Review the transcript before sending",
                    _ => "Voice unavailable · discard and retry",
                }),
        );
        if voice.phase == "review" && !self.review_ready {
            self.transcript
                .entry
                .set_text(voice.text.as_deref().unwrap_or(""));
            self.review.present();
            self.review_ready = true;
        }
        if voice.phase != "review" {
            self.review_ready = false;
        }
        if voice.phase == "error" {
            self.review.present();
        }

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
            let mut lines = vec!["Model configuration and measured usage".to_string()];
            for config in frame.usage["configuration"]
                .as_array()
                .into_iter()
                .flatten()
            {
                lines.push(format!(
                    "{} · {} · {}",
                    config["model"].as_str().unwrap_or("Unknown model"),
                    config["role"].as_str().unwrap_or(""),
                    if config["configured"] == true {
                        "Configured"
                    } else {
                        "Setup required"
                    }
                ));
            }
            for row in frame.usage["models"]
                .as_object()
                .into_iter()
                .flat_map(|m| m.values())
            {
                let tokens = if row["total_reports"].as_u64().unwrap_or(0) > 0 {
                    format!("{} reported tokens", row["total_tokens"])
                } else {
                    "Token usage not reported".into()
                };
                lines.push(format!(
                    "{} · {} responses · {} active · {} errors · {}",
                    row["model"].as_str().unwrap_or("Model"),
                    row["responses"],
                    row["active"],
                    row["errors"],
                    tokens
                ));
            }
            lines.join("\n")
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
