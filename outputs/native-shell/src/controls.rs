//! Direct human controls; authority is dispatched through the existing core/broker.
use super::*;
// Preserve the launch-time source while typing. A deliberate selection of
// status text inside the launcher is a new local reference chosen by the user.
fn request_context(frozen: Option<Value>, current: Value) -> Value {
    let local_status = current["surface_id"] == "native-launcher"
        && current["selection_kind"] == "selected_text"
        && current["job_ref"].is_null()
        && current["selection"].as_str().is_some_and(|text| !text.is_empty())
        && current["element_id"].as_str().is_some_and(|element|
            matches!(element, "message-status" | "microphone-status" | "model-status"));
    if local_status { current } else { frozen.unwrap_or(current) }
}

pub struct Controls {
    pub widget: gtk::Box,
    commands: Sender<Command>,
    activity: Rc<RefCell<Option<String>>>,
    chooser: gtk::DropDown,
    choices: Rc<RefCell<Vec<String>>>,
    chooser_model: gtk::StringList,
    activity_rows: Value,
    changing: Rc<Cell<bool>>,
    monitor: gtk::ApplicationWindow,
    pub monitor_content: gtk::Box,
    pub monitor_actions: gtk::Box,
    jobs: super::job_list::JobList,
    agents: super::agent_monitor::Monitor,
    history: gtk::Expander,
    message: ui::StatusView,
    model_text: ui::StatusView,
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
    cancel_recording: gtk::Button,
    pending_prompt: Rc<RefCell<Option<String>>>,
    prior_request: Rc<Cell<Option<i64>>>,
    last_request: Rc<Cell<Option<i64>>>,
    stop_request: gtk::Button,
    request_state: gtk::Label,
    request_job: Rc<Cell<Option<i64>>>,
    voice_status: ui::StatusView,
    frozen_context: Rc<RefCell<Option<Value>>>,
    context_provider: Rc<RefCell<Option<Rc<dyn Fn() -> Value>>>>,
    context_label: gtk::Label,
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
        let shortcuts=gtk::Expander::builder().label("Desktop keyboard shortcuts").child(&ui::text("Ctrl+Alt+Space: open launcher\nCtrl+Alt+Tab: next view (Shift: previous)\nCtrl+Alt+F10: maximize · F9: restore · F8: float\nCtrl+Alt+Arrow: move · Shift+Arrow: resize\nCtrl+Alt+PageUp/PageDown: pan oversized view (Shift: horizontal)\nCtrl+Alt+Delete: close view · Ctrl+Alt+Z: undo arrangement\nSplit, swap and pin controls are available under Arrange workspace in Agent Monitor.",true)).build();
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
                desktop_theme::install(&display, a.selected() == 1, s.value());
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
        let frozen_context = Rc::new(RefCell::new(None::<Value>));
        let context_provider = Rc::new(RefCell::new(None::<Rc<dyn Fn() -> Value>>));
        let context_label = ui::status("Context is captured when you send a request");
        context_label.set_selectable(false);
        context_label.set_wrap(false);
        context_label.set_ellipsize(gtk::pango::EllipsizeMode::End);
        widget.append(&context_label);
        let pending_prompt = Rc::new(RefCell::new(None::<String>));
        let prior_request = Rc::new(Cell::new(None));
        let last_request = Rc::new(Cell::new(None));
        let request_job = Rc::new(Cell::new(None::<i64>));
        let stop_request = ui::button("Stop request", ButtonVariant::Outline, false);
        stop_request.set_visible(false);
        let selected=request_job.clone();let sender=commands.clone();
        stop_request.connect_clicked(move |_| {if let Some(id)=selected.get(){let _=sender.send(Command::Stop{source:"core".into(),job:json!(id)});}});
        let send = ui::button("Send request", ButtonVariant::Primary, false);
        widget.append(&send);
        widget.append(&stop_request);
        let (current, commands_now, entry) =
            (activity.clone(), commands.clone(), request.entry.clone());
        let (frozen, provider) = (frozen_context.clone(), context_provider.clone());
        let failure=context_label.clone();
        let (pending, prior, last)=(pending_prompt.clone(),prior_request.clone(),last_request.clone());
        let submit = Rc::new(move || {
                if entry.text().trim().is_empty() {return;}
                *pending.borrow_mut()=Some(entry.text().to_string());
                prior.set(last.get());
            let id = current
                .borrow()
                .as_ref()
                .and_then(|s: &String| s.parse::<i64>().ok());
            let mut context = request_context(frozen.borrow().clone(), provider.borrow().as_ref().map(|capture|capture()).unwrap_or(Value::Null));
            if !context.is_object() { context=json!({"surface_id":"native-launcher","layout_revision":0,"job_ref":null,"selection":"","selection_kind":"focused_surface","surface_title":"Agent request"}); }
            if context["activity_id"].is_null() {context["activity_id"]=json!(id);}
            let activity=context["activity_id"].as_i64();
            failure.set_text(&format!("Context: {}",context["surface_title"].as_str().unwrap_or("Agent request")));
                match input_context::stamp(context,"typed") {
                    Ok(context)=>{let _ = commands_now.send(Command::Ask { activity, prompt: entry.text().into(), grounding: Some(context) });},
                    Err(_)=>failure.set_text("Could not capture the request context. Try again."),
                }
        });
        let click = submit.clone();
        send.connect_clicked(move |_| click());
        request.entry.connect_activate(move |_| submit());
        let voice = voice::Voice::new();
        let voice_button = ui::button("Record voice", ButtonVariant::Outline, false);
        voice_button.set_valign(gtk::Align::Start);
        let voice_status = ui::StatusView::new("Microphone idle").unwrap();
        let voice_row = ui::row(12);
        voice_row.append(&voice_button);
        voice_row.append(&voice_status.widget);
        let cancel_recording=ui::button("Cancel recording",ButtonVariant::Ghost,false);
        cancel_recording.set_visible(false);
        let recorder=voice.clone();cancel_recording.connect_clicked(move |_|recorder.cancel());
        voice_row.append(&cancel_recording);
        widget.append(&voice_row);
        let review_content = ui::column(12);
        review_content.set_margin_start(24); review_content.set_margin_end(24); review_content.set_margin_top(24); review_content.set_margin_bottom(24);
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
        review.add_css_class("agentos-launcher");
        let recorder = voice.clone();
        let (frozen, provider) = (frozen_context.clone(), context_provider.clone());
        voice_button.connect_clicked(move |_| {
            let phase = recorder.state.lock().unwrap().phase.clone();
            if phase == "recording" {
                recorder.finish();
            } else if phase == "idle" {
                let context = request_context(frozen.borrow().clone(), provider.borrow().as_ref().map(|capture|capture()).unwrap_or(Value::Null));
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
        let (pending, prior, last)=(pending_prompt.clone(),prior_request.clone(),last_request.clone());
        send_voice.connect_clicked(move |_| {
            if entry.text().trim().is_empty() {
                return;
            }
            if let Some(context) = recorder.consume() {
                let activity = context["activity_id"].as_i64();
                *pending.borrow_mut() = Some(entry.text().to_string());
                prior.set(last.get());
                let _ = sender.send(Command::Ask {
                    activity,
                    prompt: entry.text().into(),
                    grounding: Some(context),
                });
                window.set_visible(false);
            }
        });
        let request_state=ui::status("Ready when you are.");
        request_state.set_selectable(false);
        request_state.set_visible(false);
        widget.append(&request_state);
        let message = ui::StatusView::new("Ready when you are.").unwrap();
        widget.append(&message.widget);
        let monitor_content = ui::column(16);
        for side in [0, 1, 2, 3] {
            match side {
                0 => monitor_content.set_margin_top(20),
                1 => monitor_content.set_margin_bottom(20),
                2 => monitor_content.set_margin_start(20),
                _ => monitor_content.set_margin_end(20),
            }
        }
        let history_content = ui::column(16);
        let history = gtk::Expander::builder().label("Work history and output").child(&history_content).build();
        let agents = super::agent_monitor::Monitor::new(commands.clone(), &history);
        let monitor_actions=agents.actions.clone();
        let monitor_root = ui::column(20);
        monitor_root.set_margin_top(24); monitor_root.set_margin_bottom(24); monitor_root.set_margin_start(24); monitor_root.set_margin_end(24);
        monitor_root.append(&agents.widget);
        let model_text = ui::StatusView::new("Model configuration and measured usage unavailable").unwrap();
        model_text.value.remove_css_class("muted");
        history_content.append(&model_text.widget);
        let images = image_controls::ImageControls::new(commands.clone());
        widget.append(&images.widget);
        let workspace = workspace_controls::WorkspaceControls::new(commands.clone());
        monitor_root.append(&workspace.restoration);
        monitor_content.append(&workspace.widget);
        let jobs = super::job_list::JobList::new(app, &commands);
        history_content.append(&jobs.widget);
        let inspection = gtk::TextView::new();
        inspection.set_editable(false);
        inspection.set_cursor_visible(true);
        inspection.set_monospace(true);
        inspection.set_wrap_mode(gtk::WrapMode::WordChar);
        inspection.update_property(&[gtk::accessible::Property::Label("Selected work output")]);
        history_content.append(&inspection);
        let output_label = ui::text("Select work to inspect its output", false);
        history_content.append(&output_label);
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
        history_content.append(&pages);
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
        history_content.append(&output_follow);
        monitor_root.append(&history);
        let desktop_controls = gtk::Expander::builder().label("Desktop controls").child(&monitor_content).build();
        monitor_root.append(&desktop_controls);
        let scroll = gtk::ScrolledWindow::builder()
            .hscrollbar_policy(gtk::PolicyType::Never)
            .child(&monitor_root)
            .build();
        let monitor = gtk::ApplicationWindow::builder()
            .application(app)
            .title("Agent Monitor")
            .default_width(920)
            .default_height(755)
            .child(&scroll)
            .build();
        monitor.add_css_class("seven-ui");
        monitor.add_css_class("agentos-monitor");
        monitor.connect_map(|window| {
            if let Some(surface)=window.surface().and_then(|surface|surface.downcast::<gdk4_wayland::WaylandToplevel>().ok()) {
                surface.set_application_id("agentos.monitor");
            }
        });
        desktop_theme::titlebar(&monitor);
        monitor.connect_close_request(|window| {
            // A remapped GTK window gets a new AT-SPI identity. Unroot the
            // retained controls so readers cannot follow a dead frame parent.
            let content = window.child();
            window.set_child(gtk::Widget::NONE);
            window.set_visible(false);
            window.set_child(content.as_ref());
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
            commands,
            widget,
            activity,
            chooser,
            choices,
            chooser_model,
            activity_rows: Value::Null,
            changing,
            monitor,
            monitor_content,
            monitor_actions,
            agents,
            history,
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
            cancel_recording,
            pending_prompt,
            prior_request,
            last_request,
            stop_request,
            request_state,
            request_job,
            voice_status,
            frozen_context,
            context_provider,
            context_label,
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
        assert!(!self.model_text.value.text().is_empty());
        self.workspace.verify(frame);

        self.present();
    }
    pub fn verify_activity_chooser(&mut self, frame: &Frame, commands: &Sender<Command>) {
        let mut observed = frame.clone();
        let rows = (1..=2000).map(|id| json!({"id":id,"name":format!("Activity {id}")})).collect::<Vec<_>>();
        observed.core["activities"] = json!(rows);
        observed.activity = Some("2000".into());
        let chooser = self.chooser.clone();
        self.update(&observed, commands);
        assert_eq!(self.chooser.selected(), 1999);
        assert_eq!(self.chooser_model.n_items(), 2000);
        let started = std::time::Instant::now();
        for _ in 0..50 { self.update(&observed, commands); }
        println!("Activity chooser unchanged-history CPU measurement {}", json!({"activities":2000,"updates":50,"total_ms":started.elapsed().as_secs_f64()*1000.0,"meaning":"Synthetic host update CPU duration; not input-to-display latency"}));
        observed.core["activities"][1999]["name"] = json!("Renamed λ 日本語");
        self.update(&observed, commands);
        assert_eq!(self.chooser_model.string(1999).as_deref(), Some("Renamed λ 日本語"));
        observed.core["activities"].as_array_mut().unwrap().reverse();
        self.update(&observed, commands);
        assert_eq!(self.chooser.selected(), 0);
        assert_eq!(self.choices.borrow()[0], "2000");
        assert_eq!(self.chooser_model.string(0).as_deref(), Some("Renamed λ 日本語"));
        observed.core["activities"].as_array_mut().unwrap().remove(1999);
        self.update(&observed, commands);
        assert_eq!(self.chooser.selected(), 0);
        assert_eq!(self.chooser_model.n_items(), 1999);
        observed.activity = Some("1999".into());
        self.update(&observed, commands);
        assert_eq!(self.chooser.selected(), 1);
        assert_eq!(self.chooser, chooser);
        self.update(frame, commands);
        println!("CHECK: large activity history retains chooser identity and current names/selection across rename, reorder, removal and activity switching");
    }
    pub fn verify_status_updates(&mut self, frame: &Frame, commands: &Sender<Command>) {
        self.history.set_expanded(true);
        let original_voice = self.voice.state.lock().unwrap().clone();
        let request = self.request_field.entry.text();
        for kind in ["message", "voice", "model"] {
            if std::env::var("AGENT_OS_STATUS_SELECTION_CASE").is_ok_and(|case| case != kind) {
                continue;
            }
            let mut fixture = frame.clone();
            fixture.notice = Some("Original notice λ 日本語".into());
            fixture.error = None;
            fixture.usage = json!({"configuration":[{"model":"Original λ 日本語","role":"fixture","configured":false}],"models":{}});
            self.voice.state.lock().unwrap().error = Some("Original microphone λ 日本語".into());
            self.update(&fixture, commands);
            let label = match kind {
                "message" => self.message.value.clone(),
                "voice" => self.voice_status.value.clone(),
                _ => self.model_text.value.clone(),
            };
            let original = label.text();
            label.select_region(0, -1);
            let selection = label.selection_bounds();
            assert!(selection.is_some());
            fixture.notice = Some("Current notice 日本語".into());
            fixture.usage["configuration"][0]["model"] = json!("Current 日本語");
            self.voice.state.lock().unwrap().error = Some("Current microphone 日本語".into());
            self.update(&fixture, commands);
            assert_eq!(label.text(), original, "{kind}: background refresh replaced selected status");
            assert_eq!(label.selection_bounds(), selection, "{kind}");
            assert_eq!(self.request_field.entry.text(), request);
            let seed = json!({"activity_id":frame.activity.as_ref().unwrap().parse::<i64>().unwrap(),"surface_id":"native-launcher","layout_revision":0,"job_ref":null,"selection":"","selection_kind":"focused_surface","surface_title":"Agent request"});
            let captured = self.capture_context_for_surfaces(seed.clone(), kind == "model", kind != "model");
            assert_eq!(captured["selection"], original.as_str(), "{kind}: selected status missing from input context");
            assert_eq!(captured["selection_kind"], "selected_text");
            assert_eq!(self.capture_context_for_surfaces(seed.clone(), false, false), seed, "Inactive status selection replaced focused context");
            let view = match kind { "message" => &self.message, "voice" => &self.voice_status, _ => &self.model_text };
            assert!(view.current.is_visible(), "{kind}: current observation hidden");
            assert!(view.current.text().contains("Current"), "{kind}: current observation missing");
            self.update(&fixture, commands);
            assert_eq!(label.selection_bounds(), selection, "{kind}: repeated poll changed selection");
            label.select_region(0, 0);
            self.update(&fixture, commands);
            assert_ne!(label.text(), original, "{kind}: deselection did not apply current state");
            println!("CHECK: selected {kind} status retains snapshot and request draft across background refresh");
        }
        *self.voice.state.lock().unwrap() = original_voice;
        self.update(frame, commands);
    }
    pub fn verify_local_status_requests(&mut self, frame: &Frame, commands: &Sender<Command>) -> Vec<(String, Value)> {
        self.history.set_expanded(true);
        let previous_provider = self.context_provider.borrow().clone();
        let previous_voice = self.voice.state.lock().unwrap().clone();
        let previous_request = self.request_field.entry.text();
        let activity = frame.activity.as_ref().unwrap().parse::<i64>().unwrap();
        let mut expected = Vec::new();
        for kind in ["message", "voice"] {
            if std::env::var("AGENT_OS_LOCAL_STATUS_INPUT_CASE").is_ok_and(|selected| selected != kind) { continue; }
            self.hide_launcher();
            let source = Rc::new(RefCell::new(json!({"activity_id":activity,"surface_id":"native-fixture","layout_revision":7,"job_ref":null,"selection":"Original view selection","selection_kind":"selected_text","surface_title":"Original document","element_id":"field"})));
            let current = source.clone(); self.context_provider(Rc::new(move || current.borrow().clone()));
            self.open_launcher();
            let mut fixture = frame.clone(); fixture.error = None;
            fixture.notice = Some("Original local notice λ 日本語".into());
            self.voice.state.lock().unwrap().error = Some("Original local microphone λ 日本語".into());
            self.update(&fixture, commands);
            let label = if kind == "message" { self.message.value.clone() } else { self.voice_status.value.clone() };
            label.select_region(0, -1);
            fixture.notice = Some("Current local notice".into());
            self.voice.state.lock().unwrap().error = Some("Current local microphone".into());
            self.update(&fixture, commands);
            let selected = self.capture_context_for_surfaces(json!({"activity_id":activity,"surface_id":"native-launcher","layout_revision":0,"job_ref":null,"selection":"","selection_kind":"focused_surface","surface_title":"Agent request"}), false, true);
            assert_eq!(selected["selection"], label.text().as_str());
            *source.borrow_mut() = selected.clone();
            self.request_field.entry.set_text(&format!("Explain selected local {kind} status"));
            self.request_field.entry.emit_activate();
            expected.push((kind.to_owned(), selected));
            label.select_region(0, 0);
            self.hide_launcher();
        }
        *self.context_provider.borrow_mut() = previous_provider;
        *self.voice.state.lock().unwrap() = previous_voice;
        self.request_field.entry.set_text(&previous_request);
        self.update(frame, commands);
        expected
    }
    pub fn verify_work_context(&mut self, frame: &Frame, commands: &Sender<Command>) {
        self.history.set_expanded(true);
        for source in ["core", "broker"] {
            let case = if source == "core" { "work" } else { "work-broker" };
            if std::env::var("AGENT_OS_STATUS_SELECTION_CASE").is_ok_and(|selected| selected != case) { continue; }
            let mut fixture = frame.clone();
            fixture.core["jobs"] = json!([]);
            fixture.broker = json!([]);
            let activity = frame.activity.as_ref().unwrap().parse::<i64>().unwrap();
            let id = if source == "core" { json!(731) } else { json!("0123456789abcdef0123456789abcdef") };
            let job = json!({"id":id,"activity_id":activity,"activity":activity,"status":"running","argv":["Selected work λ 日本語"]});
            if source == "core" { fixture.core["jobs"] = json!([job]); } else { fixture.broker = json!([job]); }
            self.update(&fixture, commands);
            for _ in 0..32 { if glib::MainContext::default().pending() { glib::MainContext::default().iteration(false); } else { break; } }
            let key = format!("{source}:{}", if source == "core" { "731" } else { id.as_str().unwrap() });
            let view = self.jobs.status_capture_view(&key);
            let original = view.value.text();
            view.value.select_region(0, -1);
            let seed = json!({"activity_id":activity,"surface_id":"native-launcher","layout_revision":0,"job_ref":null,"selection":"","selection_kind":"focused_surface","surface_title":"Agent request"});
            let captured = self.capture_context_for_surfaces(seed.clone(), true, false);
            assert_eq!(captured["selection"], original.as_str(), "{case}: selected status missing from input context");
            assert_eq!(captured["job_ref"], if source == "core" { id } else { json!(format!("broker:{}",id.as_str().unwrap())) });
            assert_eq!(captured["activity_id"], activity);
            assert_eq!(captured["surface_id"], "native-monitor");
            assert_eq!(self.capture_context_for_surfaces(seed.clone(), false, false), seed);
            view.value.select_region(0, 0);
            self.update(frame, commands);
            println!("CHECK: selected {source} work context retains exact row text and job/activity identity without using another output page");
        }
    }
    pub fn capture_status(mut self, kind: String, path: String, mut frame: Frame, commands: Sender<Command>, quit: gtk::Application) {
        self.history.set_expanded(true);
        frame.connected = true;
        frame.error = None;
        frame.notice = Some("Original notice λ 日本語".into());
        frame.usage = json!({"configuration":[{"model":"Original model λ 日本語","role":"fixture","configured":false}],"models":{}});
        frame.core["jobs"] = json!([{"id":731,"status":"running","argv":["Selection verification","λ 日本語"]}]);
        frame.broker = json!([]);
        self.voice.state.lock().unwrap().error = Some("Original microphone λ 日本語".into());
        self.request_field.entry.set_text("Unsent request λ 日本語");
        self.update(&frame, &commands);
        self.temporary_launcher();
        let window = if matches!(kind.as_str(), "voice" | "message") {
            let window = gtk::ApplicationWindow::builder().application(&quit)
                .title("Status selection verification").default_width(720).child(&self.widget).build();
            window.add_css_class("seven-ui");
            window.present();
            window
        } else {
            self.monitor.present();
            self.monitor.clone()
        };
        glib::timeout_add_local_once(Duration::from_millis(180), move || {
            let (label, current) = match kind.as_str() {
                "message" => (self.message.value.clone(), self.message.current.clone()),
                "voice" => (self.voice_status.value.clone(), self.voice_status.current.clone()),
                "model" => (self.model_text.value.clone(), self.model_text.current.clone()),
                "work" => { let view = self.jobs.status_capture_view("core:731"); (view.value.clone(), view.current.clone()) },
                _ => panic!("Unknown status capture"),
            };
            let original = label.text();
            label.select_region(0, -1);
            assert!(label.grab_focus());
            frame.notice = Some("Current notice 日本語".into());
            frame.usage["configuration"][0]["model"] = json!("Current model 日本語");
            frame.core["jobs"][0]["status"] = json!("failed");
            self.voice.state.lock().unwrap().error = Some("Current microphone 日本語".into());
            self.update(&frame, &commands);
            assert_eq!(label.text(), original);
            assert!(current.is_visible());
            assert_eq!(self.request_field.entry.text(), "Unsent request λ 日本語");
            glib::timeout_add_local_once(Duration::from_millis(180), move || {
                assert!(label.is_mapped() && current.is_mapped());
                assert!(current.width() > 0 && current.height() > 0);
                let paintable = gtk::WidgetPaintable::new(Some(&window));
                let snapshot = gtk::Snapshot::new();
                paintable.snapshot(&snapshot, window.width() as f64, window.height() as f64);
                let node = snapshot.to_node().expect("Status host capture has no rendered node");
                window.renderer().unwrap().render_texture(&node, None).save_to_png(path).unwrap();
                println!("PASS: mapped {kind} status current notice and retained selection captured with unsent request intact");
                label.select_region(0, 0);
                window.destroy();
                self.close();
                quit.quit();
            });
        });
    }
    pub fn verify_context_request(&self, frame: &Frame) {
        let source=Rc::new(RefCell::new(json!({"activity_id":frame.activity.as_ref().unwrap().parse::<i64>().unwrap(),"surface_id":"native-fixture","layout_revision":7,"job_ref":null,"selection":"Original selected λ 日本語","selection_kind":"selected_text","surface_title":"Selected document","element_id":"field","selection_captured_at":SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64()})));
        let capture=source.clone();self.context_provider(Rc::new(move ||capture.borrow().clone()));
        self.open_launcher();
        source.borrow_mut()["selection"]=json!("Later selection must not replace captured evidence");
        self.request_field.entry.set_text("Contextual native request λ");self.request_field.entry.emit_activate();
        self.hide_launcher();self.open_launcher();
        self.request_field.entry.set_text("Refreshed contextual request");self.request_field.entry.emit_activate();
        self.hide_launcher();
    }
    pub fn verify_history(&mut self, frame: &Frame, commands: &Sender<Command>) {
        self.history.set_expanded(true);
        self.jobs.verify_virtualization(frame, commands);
    }
    pub fn verify_output(&mut self, frame: &Frame, commands: &Sender<Command>) {
        self.history.set_expanded(true);
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
    pub fn capture_context(&self, context: Value) -> Value {
        let launcher_active = self.widget.root()
            .and_then(|root| root.downcast::<gtk::Window>().ok())
            .is_some_and(|window| window.is_active());
        self.capture_context_for_surfaces(context, self.monitor.is_active(), launcher_active)
    }
    fn capture_context_for_surfaces(&self, mut context: Value, monitor_active: bool, launcher_active: bool) -> Value {
        for (active, view, element, title) in [
            (monitor_active, &self.model_text, "model-status", "Model configuration and measured usage"),
            (launcher_active, &self.message, "message-status", "Agent status"),
            (launcher_active, &self.voice_status, "microphone-status", "Microphone status"),
        ] {
            if !active { continue; }
            if let Some(selection) = input_context::label_selection(&view.value) {
                let activity = self.activity.borrow().as_ref().and_then(|id| id.parse::<i64>().ok());
                context["activity_id"] = json!(activity);
                context["surface_id"] = json!("native-launcher");
                context["layout_revision"] = json!(0);
                context["job_ref"] = Value::Null;
                context["selection_kind"] = json!("selected_text");
                context["selection"] = json!(input_context::bounded(selection));
                context["surface_title"] = json!(title);
                context["element_id"] = json!(element);
                context.as_object_mut().unwrap().remove("object_id");
                return context;
            }
        }
        if monitor_active {
            if let Some(selected) = self.jobs.selected_context() {
                let fields = context.as_object_mut().unwrap();
                fields.remove("element_id"); fields.remove("object_id");
                fields.extend(selected.as_object().unwrap().clone());
                return context;
            }
        }
        let buffer = self.inspection.buffer();
        if monitor_active {
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
                context["selection_kind"] = json!("focused_output");
                context.as_object_mut().unwrap().remove("element_id");
                context.as_object_mut().unwrap().remove("object_id");
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
        context
    }
    pub fn context_provider(&self, capture: Rc<dyn Fn() -> Value>) { *self.context_provider.borrow_mut()=Some(capture); }
    pub fn open_launcher(&self) {
        if self.frozen_context.borrow().is_none() {
            let context=self.context_provider.borrow().as_ref().map(|capture|capture()).unwrap_or(Value::Null);
            let title=context["surface_title"].as_str().unwrap_or("Agent request");
            let kind=if context["selection"].as_str().is_some_and(|s|!s.is_empty()) {"Selection"} else {"Context"};
            self.context_label.set_text(&format!("{kind}: {title}"));
            *self.frozen_context.borrow_mut()=Some(context);
        }
        self.focus_request();
    }

    pub fn close(&self) {
        self.voice.cancel();
    }
    pub fn hide_launcher(&self) {
        self.frozen_context.borrow_mut().take();
        // Closed launcher statuses cannot become stale selections in a later
        // request. The request entry and selected monitor/domain views persist.
        self.message.value.select_region(0, 0);
        self.voice_status.value.select_region(0, 0);
        let phase = self.voice.state.lock().unwrap().phase.clone();
        if phase == "starting" || phase == "recording" { self.voice.cancel(); }
    }
    pub fn focus_request(&self) { self.request_field.entry.grab_focus(); }
    pub fn temporary_launcher(&self) {
        let settings = ui::column(12);
        let direct = gtk::FlowBox::new();
        direct.set_selection_mode(gtk::SelectionMode::None);
        direct.set_min_children_per_line(1);
        direct.set_max_children_per_line(3);
        direct.set_column_spacing(12);
        direct.set_row_spacing(12);
        while let Some(child) = self.widget.first_child() {
            if child == self.request_field.widget.clone().upcast::<gtk::Widget>() { break; }
            self.widget.remove(&child);
            let quick = child.downcast_ref::<gtk::Button>().and_then(|button| button.label()).is_some_and(|label| matches!(label.as_str(), "Open terminal" | "New document" | "Import text file…"));
            if quick { direct.insert(&child, -1); } else { settings.append(&child); }
        }
        self.widget.remove(&self.images.widget);
        settings.append(&self.images.widget);
        self.widget.append(&direct);
        self.widget.set_margin_top(16);
        let section = gtk::Expander::builder().label("Activities, appearance and setup").child(&settings).build();
        self.monitor_content.append(&section);
    }
    /// Opt-in verification capture of the mapped, active restoration controls.
    pub fn capture_output_restoration(&self, path: &str) -> bool {
        self.monitor.is_visible() && self.monitor.is_active()
            && self.workspace.restoration.is_visible()
            && system_bar::capture(&self.monitor, path)
    }
    pub fn preview_size(&self, width: i32, height: i32) { self.monitor.set_default_size(width, height); }
    pub fn capture_monitor(&self, path: &str) -> bool { self.monitor.is_visible() && system_bar::capture(&self.monitor, path) }
    pub fn present(&self) {
        self.monitor.present();
        if std::env::var_os("AGENT_OS_COMPOSITOR_SOCKET").is_some() {let _=self.commands.send(Command::PresentMonitor);}
    }
    pub fn update(&mut self, frame: &Frame, _commands: &Sender<Command>) {
        self.images.update(frame);
        self.import_document.set_sensitive(frame.connected);
        self.new_document.set_sensitive(frame.connected);
        *self.activity.borrow_mut() = frame.activity.clone();
        self.workspace.update(frame);
        let voice = self.voice.state.lock().unwrap().clone();
        self.cancel_recording.set_visible(matches!(voice.phase.as_str(),"starting"|"recording"|"transcribing"));
        self.voice_button.set_label(if voice.phase == "recording" {
            "Finish recording"
        } else {
            "Record voice"
        });
        self.voice_button
            .set_sensitive(matches!(voice.phase.as_str(), "idle" | "recording"));
        status_projection::update(&self.voice_status,
            voice
                .error
                .as_deref()
                .unwrap_or(match voice.phase.as_str() {
                    "idle" => "Microphone idle",
                    "starting" => "Starting microphone…",
                    "recording" => "Listening · finish or cancel recording",
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

        self.changing.set(true);
        let rows = &frame.core["activities"];
        // A poll often carries the same history. Keep native model reads and
        // row allocation off the input thread until the observed rows change.
        if &self.activity_rows != rows {
            let ids = rows.as_array().into_iter().flatten()
                .map(|a| a["id"].to_string()).collect::<Vec<_>>();
            let names = rows.as_array().into_iter().flatten()
                .map(|a| a["name"].as_str().unwrap_or("Activity")).collect::<Vec<_>>();
            if *self.choices.borrow() != ids
                || (0..self.chooser_model.n_items())
                    .map(|i| self.chooser_model.string(i).unwrap().to_string())
                    .collect::<Vec<_>>() != names
            {
                self.chooser_model.splice(0, self.chooser_model.n_items(), &names);
                *self.choices.borrow_mut() = ids;
            }
            self.activity_rows = rows.clone();
        }
        self.chooser.set_selected(
            self.choices.borrow().iter()
                .position(|id| Some(id) == frame.activity.as_ref())
                .map(|i| i as u32).unwrap_or(gtk::INVALID_LIST_POSITION),
        );
        self.changing.set(false);
        status_projection::update(&self.message,
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
        self.last_request.set(frame.submitted_request);
        self.request_state.set_visible(self.pending_prompt.borrow().is_some() || !self.request_field.entry.text().is_empty());
        if self.pending_prompt.borrow().is_some() {
            let job=frame.core["jobs"].as_array().into_iter().flatten().find(|job| {
                frame.submitted_request.is_some() && frame.submitted_request != self.prior_request.get()
                && job["id"].as_i64()==frame.submitted_request
            });
            let status=job.and_then(|j|j["status"].as_str());
            self.request_job.set(job.and_then(|j|j["id"].as_i64()));
            let active=matches!(status,Some("starting"|"running"|"cancelling"));
            self.stop_request.set_visible(active);self.stop_request.set_sensitive(frame.connected && active);
            let phase=job.map(|j|&frame.usage["agents"][j["id"].to_string()]["phase"]);
            let feedback=match status {
                Some("starting")=>"Understanding your request…",
                Some("running")=>if phase.is_some_and(|p|p=="acting") {"Acting on your request…"} else {"Understanding your request…"},
                Some("cancelling")=>"Stopping your request…",
                Some("cancelled")=>"Stopped. Completed work is saved.",
                Some("succeeded")=>if phase.is_some_and(|p|p=="clarification_needed") {"Your agent needs more information. View its activity, then reply here."}else{"Completed. View the result in Agent Monitor."},
                Some("failed")=>"The request failed. View its activity for details, then correct or retry it.",
                _=>if frame.connected {"Submitting your request…"}else{"Connection unavailable. Your draft is retained."},
            };
            self.request_state.set_text(feedback);
        } else if !self.request_field.entry.text().is_empty() && frame.error.is_none() && frame.notice.is_none() {
            self.request_state.set_text("Composing · send when you’re ready");
        }
        self.agents.update(frame);
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
        status_projection::update(&self.model_text, &usage);
        if let Some(output) = &frame.inspection {
            if self.output_page.as_ref().is_none_or(|prior|prior.source!=output.source || prior.job!=output.job) {self.history.set_expanded(true);}
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

#[cfg(test)]
mod context_tests {
    use super::*;
    #[test]
    fn request_context_only_replaces_frozen_source_for_explicit_local_status() {
        let original = json!({"surface_id":"document","selection":"Original λ"});
        let changed = json!({"surface_id":"document","selection":"Later 日本語"});
        assert_eq!(request_context(Some(original.clone()), changed.clone()), original);
        assert_eq!(request_context(None, changed.clone()), changed);
        for element in ["message-status", "microphone-status", "model-status"] {
            let selected = json!({"surface_id":"native-launcher","selection_kind":"selected_text","job_ref":null,"element_id":element,"selection":"Selected λ 日本語"});
            assert_eq!(request_context(Some(original.clone()), selected.clone()), selected);
            let mut empty = selected.clone(); empty["selection"] = json!("");
            assert_eq!(request_context(Some(original.clone()), empty), original);
            let mut other = selected; other["element_id"] = json!("field");
            assert_eq!(request_context(Some(original.clone()), other), original);
        }
    }
}
