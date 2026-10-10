//! Direct human controls; authority is dispatched through the existing core/broker.
use super::*;
pub struct Controls {
    pub widget: gtk::Box,
    activity: Rc<RefCell<Option<String>>>,
    chooser: gtk::DropDown,
    choices: Rc<RefCell<Vec<String>>>,
    chooser_model: gtk::StringList,
    changing: Rc<Cell<bool>>,
    monitor: gtk::ApplicationWindow,
    jobs: super::job_list::JobList,
    message: gtk::Label,
    model_text: gtk::Label,
    inspection: gtk::TextView,
    output_page: Option<log_view::Page>,
    output_label: gtk::Label,
    output_previous: gtk::Button,
    output_next: gtk::Button,
    output_refresh: gtk::Button,
    output_follow: gtk::CheckButton,
    output_changing: Rc<Cell<bool>>,
    output_displayed: Rc<RefCell<Option<log_view::Page>>>,
    voice: voice::Voice,
    voice_button: gtk::Button,
    voice_status: gtk::Label,
    voice_context: Rc<RefCell<Value>>,
    review: gtk::ApplicationWindow,
    transcript: TextField,
    review_ready: bool,
    request_field: TextField,
    new_document: gtk::Button,
    import_document: gtk::Button,
    workspace: workspace_controls::WorkspaceControls,
    images: image_controls::ImageControls,
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
        let terminal = ui::button("Open terminal", ButtonVariant::Outline, false);
        let sender = commands.clone();
        terminal.connect_clicked(move |_| {
            let _ = sender.send(Command::OpenTerminal);
        });
        widget.append(&terminal);
        let new_document = ui::button("New document", ButtonVariant::Outline, false);
        let sender = commands.clone();
        new_document.connect_clicked(move |_| {
            let _ = sender.send(Command::CreateDocument);
        });
        widget.append(&new_document);
        let import_document = ui::button("Import text file…", ButtonVariant::Outline, false);
        widget.append(&import_document);
        let shortcuts=gtk::Expander::builder().label("Desktop keyboard shortcuts").child(&ui::text("Ctrl+Alt+Tab: next view (Shift: previous)\nCtrl+Alt+F10: maximize · F9: restore · F8: float\nCtrl+Alt+Arrow: move · Shift+Arrow: resize\nCtrl+Alt+PageUp/PageDown: pan oversized view (Shift: horizontal)\nCtrl+Alt+Delete: close view · Ctrl+Alt+Z: undo arrangement\nSplit, swap and pin controls are available under Arrange workspace in Agent Monitor.",true)).build();
        widget.append(&shortcuts);
        let appearance = gtk::DropDown::from_strings(&["Dark", "Light"]);
        let scale = gtk::SpinButton::with_range(1.0, 3.0, 0.25);
        let preferences = super::preferences::read();
        scale.set_value(preferences["text_scale"].as_f64().unwrap_or(1.0));
        appearance.set_selected(if preferences["appearance"] == "light" {
            1
        } else {
            0
        });
        let reduced = gtk::CheckButton::with_label("Reduce motion");
        appearance.update_property(&[gtk::accessible::Property::Label("Appearance")]);
        scale.update_property(&[gtk::accessible::Property::Label("Text scale")]);
        reduced.set_active(preferences["reduced_motion"] == true);
        let appearance_row = ui::row(12);
        appearance_row.append(&appearance);
        appearance_row.append(&ui::text("Text scale", false));
        appearance_row.append(&scale);
        appearance_row.append(&reduced);
        widget.append(&appearance_row);
        let (a, s, r) = (appearance.clone(), scale.clone(), reduced.clone());
        let sender = commands.clone();
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
                let _=sender.send(Command::Preferences(json!({"appearance":if a.selected()==0{"dark"}else{"light"},"text_scale":s.value(),"reduced_motion":r.is_active()})));
            }
        });
        theme();
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
        let activity_row = gtk::FlowBox::new();
        activity_row.set_selection_mode(gtk::SelectionMode::None);
        activity_row.set_max_children_per_line(3);
        activity_row.set_min_children_per_line(1);
        activity_row.set_column_spacing(12);
        activity_row.set_row_spacing(12);
        activity_row.insert(&chooser, -1);
        let name = TextField::new("New activity", "Activity name", "");
        activity_row.insert(&name.widget, -1);
        let new = ui::button("Create activity", ButtonVariant::Outline, false);
        activity_row.insert(&new, -1);
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
        let images = image_controls::ImageControls::new(commands.clone());
        widget.append(&images.widget);
        let workspace = workspace_controls::WorkspaceControls::new(commands.clone());
        monitor_content.append(&workspace.widget);
        let jobs = super::job_list::JobList::new(app, &commands);
        monitor_content.append(&jobs.widget);
        let inspection = gtk::TextView::new();
        inspection.set_editable(false);
        inspection.set_cursor_visible(true);
        inspection.set_monospace(true);
        inspection.set_wrap_mode(gtk::WrapMode::WordChar);
        inspection.update_property(&[gtk::accessible::Property::Label("Selected work output")]);
        monitor_content.append(&inspection);
        let output_label = ui::text("Select work to inspect its output", false);
        monitor_content.append(&output_label);
        let output_previous = ui::button("Previous output page", ButtonVariant::Outline, false);
        let output_next = ui::button("Next output page", ButtonVariant::Outline, false);
        let output_refresh = ui::button("Refresh output page", ButtonVariant::Outline, false);
        let pages = gtk::FlowBox::new();
        pages.set_selection_mode(gtk::SelectionMode::None);
        pages.set_min_children_per_line(1);
        pages.set_max_children_per_line(3);
        pages.set_column_spacing(8);
        pages.set_row_spacing(8);
        for (button, direction) in [
            (&output_previous, -1),
            (&output_next, 1),
            (&output_refresh, 0),
        ] {
            pages.insert(button, -1);
            button.set_sensitive(false);
            let sender = commands.clone();
            button.connect_clicked(move |_| {
                let _ = sender.send(Command::PageOutput(direction));
            });
        }
        monitor_content.append(&pages);
        let output_follow = gtk::CheckButton::with_label("Follow live output");
        output_follow.set_sensitive(false);
        let output_changing = Rc::new(Cell::new(false));
        let output_displayed = Rc::new(RefCell::new(None::<log_view::Page>));
        let (sender, output_guard, buffer) = (
            commands.clone(),
            output_changing.clone(),
            inspection.buffer(),
        );
        output_follow.connect_toggled(move |control| {
            if output_guard.get() {
                return;
            }
            if control.is_active() && buffer.has_selection() {
                buffer.place_cursor(&buffer.end_iter());
            }
            let _ = sender.send(Command::FollowOutput(control.is_active()));
        });
        let (sender, displayed, control, output_guard) = (
            commands.clone(),
            output_displayed.clone(),
            output_follow.clone(),
            output_changing.clone(),
        );
        inspection
            .buffer()
            .connect_notify_local(Some("has-selection"), move |buffer, _| {
                if buffer.has_selection() {
                    if let Some(page) = displayed.borrow().as_ref() {
                        let _ = sender.send(Command::FreezeOutput(page.start));
                    }
                    output_guard.set(true);
                    control.set_active(false);
                    output_guard.set(false);
                }
            });
        monitor_content.append(&output_follow);
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
        let import_activity = activity.clone();
        let import_sender = commands.clone();
        import_document.connect_clicked(move |button| {
            let parent = button
                .root()
                .and_then(|root| root.downcast::<gtk::Window>().ok());
            document_dialog::choose(
                parent.as_ref(),
                None,
                import_activity.borrow().clone(),
                import_sender.clone(),
            );
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
            message,
            model_text,
            inspection,
            output_page: None,
            output_label,
            output_previous,
            output_next,
            output_refresh,
            output_follow,
            output_changing,
            output_displayed,
            voice,
            voice_button,
            voice_status,
            voice_context,
            review,
            transcript,
            review_ready: false,
            request_field: request,
            new_document,
            import_document,
            workspace,
            images,
        }
    }
    pub fn verify_controls(&mut self, frame: &Frame, commands: &Sender<Command>) {
        self.update(frame, commands);
        assert!(self.new_document.is_sensitive());
        self.new_document.emit_clicked();
        assert!(self.chooser.selected() != gtk::INVALID_LIST_POSITION);
        self.request_field
            .entry
            .set_text("Explicit native request λ");
        self.request_field.entry.emit_activate();
        self.jobs.verify_initial();
        assert!(!self.model_text.text().is_empty());
        self.workspace.verify(frame);

        self.present();
    }
    pub fn verify_history(&mut self, frame: &Frame, commands: &Sender<Command>) {
        self.jobs.verify_virtualization(frame, commands);
    }
    pub fn verify_output(&mut self, frame: &Frame, commands: &Sender<Command>) {
        let mut fixture = frame.clone();
        fixture.inspection = Some(log_view::Page {
            text: "Selected λ output".into(),
            source: "core".into(),
            job: json!(7),
            activity: 1,
            title: "Live fixture".into(),
            start: 10,
            end: 30,
            has_more: false,
            has_previous: true,
            following: true,
        });
        self.update(&fixture, commands);
        assert!(self.output_follow.is_active());
        let buffer = self.inspection.buffer();
        buffer.select_range(&buffer.start_iter(), &buffer.end_iter());
        assert!(!self.output_follow.is_active());
        fixture.inspection.as_mut().unwrap().text = "New incoming output".into();
        self.update(&fixture, commands);
        assert_eq!(
            buffer.text(&buffer.start_iter(), &buffer.end_iter(), false),
            "Selected λ output"
        );
        assert_eq!(self.output_page.as_ref().unwrap().start, 10);
        self.output_follow.set_active(true);
        assert!(!buffer.has_selection());
        self.output_previous.emit_clicked();
    }
    pub fn context(&self, mut context: Value) {
        let buffer = self.inspection.buffer();
        if self.monitor.is_active() || buffer.has_selection() {
            if let Some(page) = &self.output_page {
                let mut selection = buffer
                    .selection_bounds()
                    .map(|(start, end)| buffer.text(&start, &end, false).to_string())
                    .unwrap_or_default();
                while selection.len() > 8000 {
                    selection.pop();
                }
                context["activity_id"] = json!(page.activity);
                context["surface_id"] = json!("native-monitor");
                context["layout_revision"] = json!(page.start);
                context["job_ref"] = if page.source == "core" {
                    page.job.clone()
                } else {
                    json!(format!("broker:{}", page.job.as_str().unwrap_or("")))
                };
                context["selection"] = json!(selection);
                context["surface_title"] = json!(page.title.chars().take(200).collect::<String>());
            }
        }
        *self.voice_context.borrow_mut() = context;
    }
    pub fn close(&self) {
        self.voice.cancel();
    }
    pub fn present(&self) {
        self.monitor.present();
    }
    pub fn update(&mut self, frame: &Frame, _commands: &Sender<Command>) {
        self.images.update(frame);
        self.import_document
            .set_sensitive(frame.connected && frame.activity.is_some());
        self.new_document
            .set_sensitive(frame.connected && frame.activity.is_some());
        *self.activity.borrow_mut() = frame.activity.clone();
        self.workspace.update(frame);
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
        self.jobs.update(frame);
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
            self.output_previous.set_sensitive(output.has_previous);
            self.output_next.set_sensitive(output.has_more);
            self.output_refresh.set_sensitive(frame.connected);
            self.output_follow.set_sensitive(frame.connected);
            self.output_changing.set(true);
            self.output_follow
                .set_active(output.following && !buffer.has_selection());
            self.output_changing.set(false);
            if !buffer.has_selection() {
                if buffer.text(&buffer.start_iter(), &buffer.end_iter(), false) != output.text {
                    buffer.set_text(&output.text);
                }
                self.output_label.set_text(&format!(
                    "{} work {} · output bytes {}–{} · {}",
                    output.source,
                    output.job,
                    output.start,
                    output.end,
                    if output.following {
                        "Following"
                    } else {
                        "Paused"
                    }
                ));
                self.output_page = Some(output.clone());
                *self.output_displayed.borrow_mut() = Some(output.clone());
            }
        }
    }
}

pub(super) fn review_proposal(app: &gtk::Application, proposal: Value, commands: Sender<Command>) {
    let content = ui::column(12);
    content.set_margin_top(20);
    content.set_margin_bottom(20);
    content.set_margin_start(20);
    content.set_margin_end(20);
    content.append(&ui::text("Review proposed system operation", true));
    let arguments = proposal["argv"]
        .as_array()
        .into_iter()
        .flatten()
        .enumerate()
        .map(|(i, a)| {
            format!(
                "{}: {}",
                i + 1,
                serde_json::to_string(a.as_str().unwrap_or("")).unwrap()
            )
        })
        .collect::<Vec<_>>()
        .join("\n");
    let explanation=format!("Purpose: {}\nDirectory: {}\nReason for review: {}\n\nExact command arguments:\n{}\n\nSupplied input: {} bytes · fingerprint {}\nInteractive terminal: {}\n\nThis operation runs with root authority in the guest.",proposal["purpose"].as_str().unwrap_or("Unspecified"),proposal["cwd"].as_str().unwrap_or("Unspecified"),proposal["policy"]["reason"].as_str().unwrap_or("Review required"),arguments,proposal["stdin_bytes"].as_u64().unwrap_or(0),proposal["stdin_sha256"].as_str().unwrap_or("none"),if proposal["terminal"]==true{"yes"}else{"no"});
    content.append(&ui::text(&explanation, false));
    if proposal["stdin_bytes"].as_u64().unwrap_or(0) > 0 {
        let inspect = ui::button("Inspect stored input", ButtonVariant::Outline, false);
        let preview = gtk::TextView::builder()
            .editable(false)
            .cursor_visible(true)
            .monospace(true)
            .wrap_mode(gtk::WrapMode::WordChar)
            .build();
        preview.update_property(&[gtk::accessible::Property::Label("Stored operation input")]);
        let scroll = gtk::ScrolledWindow::builder()
            .min_content_height(160)
            .max_content_height(300)
            .child(&preview)
            .build();
        content.append(&inspect);
        content.append(&scroll);
        let (sender, current, weak) = (commands.clone(), proposal.clone(), preview.downgrade());
        inspect.connect_clicked(move |button| {
            button.set_sensitive(false);
            let (reply, receiver) = std::sync::mpsc::channel();
            if sender
                .send(Command::ReviewInput {
                    proposal: current.clone(),
                    reply,
                })
                .is_err()
            {
                return;
            }
            let weak = weak.clone();
            glib::timeout_add_local(Duration::from_millis(100), move || {
                let Some(preview) = weak.upgrade() else {
                    return glib::ControlFlow::Break;
                };
                match receiver.try_recv() {
                    Ok(Ok(value)) => {
                        preview
                            .buffer()
                            .set_text(value["stdin"].as_str().unwrap_or("No stored input"));
                        glib::ControlFlow::Break
                    }
                    Ok(Err(error)) => {
                        preview
                            .buffer()
                            .set_text(&format!("Input inspection unavailable: {error}"));
                        glib::ControlFlow::Break
                    }
                    Err(std::sync::mpsc::TryRecvError::Empty) => glib::ControlFlow::Continue,
                    Err(_) => {
                        preview.buffer().set_text("Input inspection unavailable");
                        glib::ControlFlow::Break
                    }
                }
            });
        });
    }
    let approve = ui::button("Approve this operation", ButtonVariant::Destructive, false);
    let reject = ui::button("Reject this operation", ButtonVariant::Outline, false);
    let cancel = ui::button("Keep pending", ButtonVariant::Ghost, false);
    content.append(&approve);
    content.append(&reject);
    content.append(&cancel);
    let scroll = gtk::ScrolledWindow::builder()
        .hscrollbar_policy(gtk::PolicyType::Never)
        .child(&content)
        .build();
    let window = gtk::ApplicationWindow::builder()
        .application(app)
        .title("Review system operation")
        .default_width(680)
        .default_height(560)
        .child(&scroll)
        .build();
    window.add_css_class("seven-ui");
    let (view, sender, current) = (window.downgrade(), commands.clone(), proposal.clone());
    approve.connect_clicked(move |button| {
        button.set_sensitive(false);
        let _ = sender.send(Command::Approve(current.clone()));
        if let Some(view) = view.upgrade() {
            view.close();
        }
    });
    let (view, sender, id) = (window.downgrade(), commands, proposal["id"].clone());
    reject.connect_clicked(move |_| {
        let _ = sender.send(Command::Stop {
            source: "broker".into(),
            job: id.clone(),
        });
        if let Some(view) = view.upgrade() {
            view.close();
        }
    });
    let view = window.downgrade();
    cancel.connect_clicked(move |_| {
        if let Some(view) = view.upgrade() {
            view.close();
        }
    });
    window.present();
}
