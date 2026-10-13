//! A local first-run introduction; setup remains deliberate and can be deferred.
use super::*;
fn state_root() -> PathBuf {
    std::env::var_os("XDG_STATE_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".local/state"))
        .join("agent-os")
}
fn completed() -> bool {
    let root=state_root();
    let read=|name: &str| std::fs::read(root.join(name)).ok()
        .filter(|bytes| bytes.len() <= 16384)
        .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok());
    read("setup.json").is_some_and(|v| v["version"] == 1 && v["completed_at"].as_f64().is_some())
        || read("welcome.json").is_some_and(|v| v["version"] == 1 && v["dismissed"] == true)
}
// Dismissing the introduction is distinct from completing provider setup.
fn remember_dismissal() -> std::io::Result<()> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    let root=state_root();std::fs::create_dir_all(&root)?;
    let temporary=root.join(format!(".welcome-{}-{}",std::process::id(),nonce()));
    let result=(|| {
        let mut file=std::fs::OpenOptions::new().create_new(true).write(true).mode(0o600).open(&temporary)?;
        file.write_all(b"{\"version\":1,\"dismissed\":true}\n")?;file.sync_all()?;
        std::fs::rename(&temporary,root.join("welcome.json"))?;
        std::fs::File::open(&root)?.sync_all()
    })();
    let _=std::fs::remove_file(&temporary);result
}
pub fn present(app: &gtk::Application, commands: Sender<Command>) {
    if completed() || std::env::args().any(|arg| arg == "--self-test") {
        return;
    }
    let content = ui::column(16);
    let body=ui::column(16);
    body.set_margin_start(24);body.set_margin_end(24);
    body.set_margin_top(24);body.set_margin_bottom(24);
    let title=ui::text("Welcome to agentOS",true);title.set_selectable(false);title.add_css_class("desktop-heading");content.append(&title);
    content.append(&ui::text("Describe what you want to do in the launcher, or open a document or terminal and get straight to work.",false));
    content.append(&ui::text("Connect your model providers and check your microphone in Setup. Agents shows your agents, their progress and usage.",false));
    let setup = ui::button("Open setup", ButtonVariant::Primary, false);
    let later = ui::button("Continue to desktop", ButtonVariant::Outline, false);
    let actions=gtk::FlowBox::new();
    actions.add_css_class("welcome-actions");
    actions.set_selection_mode(gtk::SelectionMode::None);
    actions.set_focusable(false);
    actions.set_min_children_per_line(1);actions.set_max_children_per_line(2);
    actions.set_column_spacing(12);actions.set_row_spacing(12);
    actions.set_halign(gtk::Align::End);
    for button in [&later,&setup] {
        let group=gtk::FlowBoxChild::builder().child(button).focusable(false).accessible_role(gtk::AccessibleRole::Group).build();
        actions.insert(&group,-1);
    }
    let scale=preferences::read()["text_scale"].as_f64().unwrap_or(1.0).clamp(1.0,3.0);
    let scroll=gtk::ScrolledWindow::builder().hscrollbar_policy(gtk::PolicyType::Never).min_content_height((80.0*scale) as i32).vexpand(true).child(&content).build();
    scroll.set_overlay_scrolling(false);
    body.append(&scroll);body.append(&actions);
    let window = gtk::ApplicationWindow::builder()
        .application(app)
        .title("Welcome to agentOS")
        .default_width(560)
        .child(&body)
        .build();
    window.add_css_class("seven-ui");
    window.add_css_class("agentos-launcher");
    desktop_theme::titlebar(&window);
    window.connect_map(|window| {
        if let Ok(path)=std::env::var("AGENT_OS_WELCOME_CAPTURE") {
            let target=window.downgrade();
            glib::timeout_add_local_once(Duration::from_millis(350),move || {if let Some(window)=target.upgrade(){let _=system_bar::capture(&window,&path);}});
        }
        if let Some(surface)=window.surface().and_then(|surface|surface.downcast::<gdk4_wayland::WaylandToplevel>().ok()) {
            surface.set_application_id("agentos.welcome");
        }
    });
    let welcome = window.clone();
    setup.connect_clicked(move |_| {
        let _ = commands.send(Command::Setup);
        welcome.close();
    });
    let welcome = window.clone();
    later.connect_clicked(move |_| welcome.close());
    let mut child=content.first_child();
    while let Some(widget)=child {
        child=widget.next_sibling();
        if let Ok(label)=widget.downcast::<gtk::Label>() {label.set_selectable(false);}
    }
    window.connect_close_request(|_| {
        if let Err(error)=remember_dismissal(){eprintln!("Could not remember welcome dismissal: {error}");}
        glib::Propagation::Proceed
    });
    window.present();
}
