//! Agent identities come from supervised requests, never illustrative model roles.
use super::*;
#[derive(Clone, Debug, PartialEq)]
struct Agent {
    id: i64,
    name: String,
    task: String,
    status: String,
    model: String,
    provider: String,
    input: String,
    output: String,
    total: String,
    detail: String,
    active: bool,
}
fn text(value: &Value, key: &str) -> String {
    value[key].as_str().unwrap_or("").to_owned()
}
fn count(models: &[&Value], field: &str) -> String {
    let report = format!("{field}_reports");
    let tokens = format!("{field}_tokens");
    let reported = models
        .iter()
        .filter(|m| m[&report].as_u64().unwrap_or(0) > 0)
        .collect::<Vec<_>>();
    if reported.is_empty() {
        return "Not reported".into();
    }
    let sum = reported
        .iter()
        .map(|m| m[&tokens].as_u64().unwrap_or(0))
        .sum::<u64>();
    let partial = models
        .iter()
        .any(|m| m[&report].as_u64().unwrap_or(0) < m["responses"].as_u64().unwrap_or(0));
    format!("{sum}{}", if partial { " + unknown" } else { "" })
}
fn project(frame: &Frame) -> Vec<Agent> {
    let state = if frame.agents.is_null() {
        &frame.core
    } else {
        &frame.agents
    };
    state["jobs"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|job| {
            let argv = job["argv"].as_array()?;
            let worker = 2;
            if argv.first()?.as_str() != Some("/usr/bin/python3")
                || argv.get(1)?.as_str() != Some("-u")
                || argv.get(worker)?.as_str() != Some("/usr/local/lib/agent-os/services/worker.py")
            {
                return None;
            }
            if !matches!(argv.get(worker + 1)?.as_str()?, "ask" | "resume") {
                return None;
            }
            let id = job["id"].as_i64()?;
            let usage = &frame.usage["agents"][id.to_string()]["models"];
            let models = usage
                .as_object()
                .map(|m| m.values().collect::<Vec<_>>())
                .unwrap_or_default();
            let names = models
                .iter()
                .map(|m| text(m, "resolved_model"))
                .filter(|s| !s.is_empty())
                .collect::<Vec<_>>();
            let model = if names.is_empty() {
                models
                    .iter()
                    .map(|m| text(m, "model"))
                    .collect::<Vec<_>>()
                    .join(" · ")
            } else {
                names.join(" · ")
            };
            let provider = models
                .iter()
                .map(|m| text(m, "provider"))
                .collect::<Vec<_>>()
                .join(" · ");
            let activity = &job["activity_id"];
            let name = state["activities"]
                .as_array()
                .into_iter()
                .flatten()
                .find(|a| a["id"] == *activity)
                .map(|a| text(a, "name"))
                .filter(|s| !s.is_empty())
                .unwrap_or_else(|| format!("Activity {activity}"));
            let raw = text(job, "status");
            let active = matches!(raw.as_str(), "starting" | "running" | "cancelling");
            let status = if !frame.connected {
                "Unavailable"
            } else {
                match raw.as_str() {
                    "starting" => "Starting",
                    "running" => match frame.usage["agents"][id.to_string()]["phase"].as_str() {
                        Some("understanding") => "Understanding",
                        Some("acting") => "Acting",
                        _ => "Working",
                    },
                    "cancelling" => "Stopping",
                    "succeeded" => {
                        if frame.usage["agents"][id.to_string()]["phase"] == "clarification_needed"
                        {
                            "Needs input"
                        } else {
                            "Completed"
                        }
                    }
                    "cancelled" => "Stopped",
                    "failed" => "Failed",
                    _ => "Unavailable",
                }
            }
            .to_owned();
            let task = if argv[worker + 1] == "resume" {
                "Continuing the saved request".into()
            } else {
                argv.get(worker + 3)
                    .and_then(Value::as_str)
                    .unwrap_or("Request unavailable")
                    .to_owned()
            };
            let started = job["created_at"]
                .as_i64()
                .and_then(|t| glib::DateTime::from_unix_local(t).ok())
                .and_then(|t| t.format("%a %e %b, %H:%M").ok())
                .map(|s| s.to_string())
                .unwrap_or_else(|| "Not recorded".into());
            let ended = job["finished_at"]
                .as_i64()
                .and_then(|t| glib::DateTime::from_unix_local(t).ok())
                .and_then(|t| t.format("%H:%M").ok())
                .map(|s| format!("\nFinished {s}"))
                .unwrap_or_default();
            let error = job["error"]
                .as_str()
                .filter(|s| !s.is_empty())
                .map(|s| format!("\n{s}"))
                .unwrap_or_default();
            Some(Agent {
                id,
                name,
                task,
                status,
                model: if model.is_empty() {
                    "Not reported".into()
                } else {
                    model
                },
                provider: if provider.is_empty() {
                    "Not reported".into()
                } else {
                    provider
                },
                input: count(&models, "input"),
                output: count(&models, "output"),
                total: count(&models, "total"),
                detail: format!("Started {started}{ended}{error}"),
                active: active && frame.connected,
            })
        })
        .collect()
}
struct Row {
    widget: gtk::ListBoxRow,
    cells: Vec<gtk::Label>,
}
fn columns(values: &[&str]) -> (gtk::Box, Vec<gtk::Label>) {
    let row = ui::row(18);
    let mut labels = Vec::new();
    for (index, value) in values.iter().enumerate() {
        let label = ui::text(value, false);
        label.set_wrap(false);
        label.set_selectable(false);
        label.set_xalign(if index >= 3 { 1.0 } else { 0.0 });
        let scale = preferences::read()["text_scale"]
            .as_f64()
            .unwrap_or(1.0)
            .clamp(1.0, 3.0);
        label.set_size_request(
            ([140, 104, 204, 80, 80, 80][index] as f64 * scale) as i32,
            -1,
        );
        label.set_hexpand(index == 0);
        label.set_ellipsize(gtk::pango::EllipsizeMode::End);
        if index == 0 {
            label.add_css_class("agent-name");
            label.set_hexpand(true);
        }
        if index >= 3 {
            label.add_css_class("token-count");
        }
        row.append(&label);
        labels.push(label);
    }
    (row, labels)
}
pub struct Monitor {
    pub widget: gtk::Box,
    pub actions: gtk::Box,
    list: gtk::ListBox,
    table_region: gtk::ScrolledWindow,
    rows: BTreeMap<i64, Row>,
    data: Rc<RefCell<Vec<Agent>>>,
    selected: Rc<Cell<Option<i64>>>,
    summary: gtk::Label,
    empty: gtk::Label,
    details: gtk::FlowBox,
    title: gtk::Label,
    task: gtk::Label,
    timeline: gtk::Label,
    usage: gtk::Label,
    stop: gtk::Button,
    view: gtk::Button,
}
impl Monitor {
    pub fn new(commands: Sender<Command>, history: &gtk::Expander) -> Self {
        let widget = ui::column(14);
        let heading = ui::text("Agent Monitor", true);
        heading.add_css_class("desktop-heading");
        heading.set_selectable(false);
        heading.set_hexpand(true);
        heading.set_wrap(true);
        heading.set_xalign(0.0);
        let actions = ui::row(12);
        actions.set_halign(gtk::Align::End);
        let titles = ui::column(6);
        titles.set_hexpand(true);
        titles.append(&heading);
        let aside = ui::column(10);
        aside.append(&actions);
        let header = gtk::FlowBox::new();
        header.set_selection_mode(gtk::SelectionMode::None);
        header.set_min_children_per_line(1);header.set_max_children_per_line(2);
        header.set_column_spacing(16);header.set_row_spacing(12);
        header.set_focusable(false);
        for child in [&titles,&aside] {
            let group=gtk::FlowBoxChild::builder().child(child).focusable(false).accessible_role(gtk::AccessibleRole::Group).build();
            header.insert(&group,-1);
        }
        widget.append(&header);
        let subtitle = ui::text("See what your agents are doing", false);
        subtitle.add_css_class("desktop-subtitle");
        subtitle.set_selectable(false);
        subtitle.set_margin_top(0);
        titles.append(&subtitle);
        let summary = ui::text("Connecting to your agents…", false);
        summary.add_css_class("desktop-muted");
        summary.set_selectable(false);
        summary.set_xalign(1.0);
        summary.set_wrap(true);
        summary.set_max_width_chars(35);
        aside.append(&summary);
        let table = ui::column(10);
        let (header, _) = columns(&[
            "Agent",
            "Status",
            "Model / provider",
            "Input",
            "Output",
            "Total",
        ]);
        header.add_css_class("agent-table-header");
        table.append(&header);
        let list = gtk::ListBox::new();
        list.set_selection_mode(gtk::SelectionMode::Single);
        list.add_css_class("agent-table");
        table.append(&list);
        let region = gtk::ScrolledWindow::builder()
            .hscrollbar_policy(gtk::PolicyType::Automatic)
            .vscrollbar_policy(gtk::PolicyType::Automatic)
            .min_content_height(80)
            .max_content_height(280)
            .propagate_natural_height(true)
            .child(&table)
            .build();
        region.set_overlay_scrolling(false);
        widget.append(&region);
        let empty=ui::text("Your agents will appear here when you send a request.\nOpen the launcher with Ctrl+Alt+Space to start working.",false);
        empty.add_css_class("desktop-muted");
        empty.add_css_class("monitor-empty");
        empty.set_justify(gtk::Justification::Center);
        empty.set_halign(gtk::Align::Center);
        widget.append(&empty);
        let details = gtk::FlowBox::new();
        details.set_selection_mode(gtk::SelectionMode::None);
        details.set_min_children_per_line(1);
        details.set_max_children_per_line(2);
        details.set_homogeneous(false);
        details.add_css_class("agent-details");
        details.set_column_spacing(16);
        details.set_row_spacing(16);
        let left = ui::column(12);
        left.add_css_class("agent-detail");
        left.set_hexpand(true);
        left.set_width_request(440);
        let title = ui::text("No agent selected", true);
        title.add_css_class("agent-name");
        left.append(&title);
        let task = ui::text("Select an agent to see its request and progress.", false);
        task.set_xalign(0.0);
        task.set_wrap(true);
        task.set_max_width_chars(48);
        left.append(&task);
        let timeline = ui::text("", false);
        timeline.set_xalign(0.0);
        timeline.add_css_class("desktop-muted");
        left.append(&timeline);
        let stop = ui::button("Stop agent", ButtonVariant::Outline, false);
        stop.set_halign(gtk::Align::Start);
        stop.set_sensitive(false);
        left.append(&stop);
        let right = ui::column(16);
        right.add_css_class("agent-detail");
        right.set_hexpand(true);
        right.set_width_request(300);
        right.append(&ui::text("Model and usage", true));
        let usage = ui::text("Select an agent to see reported usage.", false);
        usage.set_wrap(true);
        usage.set_max_width_chars(48);
        usage.set_xalign(0.0);
        right.append(&usage);
        let view = ui::button("View activity", ButtonVariant::Outline, false);
        view.set_halign(gtk::Align::Start);
        view.set_sensitive(false);
        right.append(&view);
        details.insert(&left, -1);
        details.insert(&right, -1);
        widget.append(&details);
        let selected = Rc::new(Cell::new(None));
        let data = Rc::new(RefCell::new(Vec::<Agent>::new()));
        let identity = selected.clone();
        list.connect_row_selected(move |_, row| {
            identity.set(row.and_then(|row| {
                row.widget_name()
                    .strip_prefix("agent-")
                    .and_then(|s| s.parse().ok())
            }));
        });
        let identity = selected.clone();
        let sender = commands.clone();
        stop.connect_clicked(move |_| {
            if let Some(id) = identity.get() {
                let _ = sender.send(Command::Stop {
                    source: "core".into(),
                    job: json!(id),
                });
            }
        });
        let identity = selected.clone();
        let history = history.clone();
        view.connect_clicked(move |_| {
            if let Some(id) = identity.get() {
                history.set_expanded(true);
                let _ = commands.send(Command::Inspect {
                    source: "core".into(),
                    job: json!(id),
                });
                history.grab_focus();
            }
        });
        Self {
            widget,
            actions,
            list,
            table_region: region,
            rows: BTreeMap::new(),
            data,
            selected,
            summary,
            empty,
            details,
            title,
            task,
            timeline,
            usage,
            stop,
            view,
        }
    }
    pub fn update(&mut self, frame: &Frame) {
        let agents = project(frame);
        self.table_region
            .set_min_content_height((32 + agents.len().min(4) as i32 * 64).min(240));
        let working = agents.iter().filter(|a| a.active).count();
        let session = &frame.usage["sessions"]
            [frame.usage["current_session"].as_str().unwrap_or("")]["models"];
        let session = session
            .as_object()
            .map(|m| m.values().collect::<Vec<_>>())
            .unwrap_or_default();
        let total=count(&session,"total");
        let usage=if !frame.connected {"Session usage unavailable".into()}
            else if total=="Not reported" {"Session usage not reported".into()}
            else {format!("{total} tokens this session")};
        set_label(&self.summary, &format!("{} agents · {} working\n{}",agents.len(),working,usage));
        self.empty.set_visible(agents.is_empty());
        self.table_region.set_visible(!agents.is_empty());
        self.details.set_visible(!agents.is_empty());
        let removed = self
            .rows
            .keys()
            .filter(|id| !agents.iter().any(|a| a.id == **id))
            .copied()
            .collect::<Vec<_>>();
        for id in removed {
            if let Some(row) = self.rows.remove(&id) {
                self.list.remove(&row.widget);
            }
        }
        for agent in &agents {
            let model_provider = format!("{}\n{}", agent.model, agent.provider);
            let row = self.rows.entry(agent.id).or_insert_with(|| {
                let (body, cells) = columns(&["", "", "", "", "", ""]);
                let widget = gtk::ListBoxRow::new();
                widget.set_widget_name(&format!("agent-{}", agent.id));
                widget.set_child(Some(&body));
                self.list.append(&widget);
                Row { widget, cells }
            });
            for (cell, value) in row.cells.iter().zip([
                &agent.name,
                &agent.status,
                &model_provider,
                &agent.input,
                &agent.output,
                &agent.total,
            ]) {
                if cell.text().as_str() != value {
                    cell.set_text(value);
                }
                cell.set_tooltip_text(Some(value));
            }
            row.cells[2].set_tooltip_text(Some(&format!("{}\n{}", agent.model, agent.provider)));
        }
        if !agents.iter().any(|a| Some(a.id) == self.selected.get()) {
            self.selected.set(agents.first().map(|a| a.id));
            if let Some(row) = self.selected.get().and_then(|id| self.rows.get(&id)) {
                self.list.select_row(Some(&row.widget));
            }
        }
        if let Some(agent) = agents.iter().find(|a| Some(a.id) == self.selected.get()) {
            set_label(&self.title, &format!("{} · {}", agent.name, agent.status));
            set_label(&self.task, &agent.task);
            set_label(&self.timeline, &agent.detail);
            set_label(&self.usage,&format!("{}\n{}\n\nInput   {}\nOutput   {}\nTotal   {}\n\nProvider-reported cost: not reported\nEstimated cost: unavailable",agent.model,agent.provider,agent.input,agent.output,agent.total));
            self.stop.set_sensitive(agent.active);
            self.view.set_sensitive(frame.connected);
        } else {
            self.stop.set_sensitive(false);
            self.view.set_sensitive(false);
        }
        *self.data.borrow_mut() = agents;
    }
}
fn set_label(label: &gtk::Label, value: &str) {
    // Preserve selected evidence until the user releases it.
    if label.selection_bounds().is_none() && label.text().as_str() != value {
        label.set_text(value);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reported_zero_and_missing_usage_are_distinct() {
        let zero = json!({"input_reports":1,"input_tokens":0,"responses":1});
        let missing = json!({"input_reports":0,"input_tokens":0,"responses":1});
        assert_eq!(count(&[&zero], "input"), "0");
        assert_eq!(count(&[&missing], "input"), "Not reported");
        assert_eq!(count(&[&zero, &missing], "input"), "0 + unknown");
    }
    #[test]
    #[ignore = "requires the private GTK verification display"]
    fn selected_agent_controls_keep_exact_job_identity() {
        gtk::init().unwrap();
        let (sender, commands) = std::sync::mpsc::channel();
        let history = gtk::Expander::new(Some("Work history and output"));
        let mut monitor = Monitor::new(sender, &history);
        let job = |id| json!({"id":id,"activity_id":1,"status":"running","created_at":1,"argv":["/usr/bin/python3","-u","/usr/local/lib/agent-os/services/worker.py","ask","1","Test request"]});
        let mut frame = Frame {
            connected: true,
            core: Arc::new(json!({"jobs":[job(1),job(2)]})),
            ..Frame::default()
        };
        monitor.update(&frame);
        monitor
            .list
            .select_row(monitor.list.row_at_index(1).as_ref());
        monitor.update(&frame);
        monitor.stop.emit_clicked();
        assert!(matches!(commands.try_recv().unwrap(),Command::Stop{job,..} if job==2));
        Arc::make_mut(&mut frame.core)["jobs"] = json!([job(1)]);
        monitor.update(&frame);
        monitor.view.emit_clicked();
        assert!(history.is_expanded());
        assert!(matches!(commands.try_recv().unwrap(),Command::Inspect{job,..} if job==1));
        frame.connected = false;
        monitor.update(&frame);
        assert!(!monitor.stop.is_sensitive());
        assert!(!monitor.view.is_sensitive());
    }
    #[test]
    fn ordinary_commands_are_not_agents() {
        let frame = Frame {
            core: Arc::new(json!({"jobs":[{"id":1,"argv":["echo","hello"]}]})),
            ..Frame::default()
        };
        assert!(project(&frame).is_empty());
    }
}
