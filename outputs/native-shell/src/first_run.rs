//! A local first-run introduction; setup remains deliberate and can be deferred.
use super::*;
fn completed() -> bool {
    let root = std::env::var_os("XDG_STATE_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".local/state")
        });
    std::fs::read(root.join("agent-os/setup.json"))
        .ok()
        .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
        .map(|v| v["version"] == 1 && v["completed_at"].as_f64().is_some())
        .unwrap_or(false)
}
pub fn present(app: &gtk::Application, commands: Sender<Command>) {
    if completed() || std::env::args().any(|arg| arg == "--self-test") {
        return;
    }
    let content = ui::column(16);
    content.add_css_class("seven-ui");
    content.set_margin_start(24);
    content.set_margin_end(24);
    content.set_margin_top(24);
    content.set_margin_bottom(24);
    let title=ui::text("Welcome to agentOS",true);title.set_selectable(false);title.add_css_class("desktop-heading");content.append(&title);
    content.append(&ui::text("Your desktop is ready. Open the launcher to describe what you want to do, or open a document or terminal and get straight to work.",false));
    content.append(&ui::text("Connect your model providers and check your microphone in Setup. Agents shows your agents, their progress and usage.",false));
    let setup = ui::button("Open setup", ButtonVariant::Primary, false);
    let later = ui::button("Continue to desktop", ButtonVariant::Outline, false);
    let actions=ui::row(12);actions.append(&setup);actions.append(&later);content.append(&actions);
    let window = gtk::ApplicationWindow::builder()
        .application(app)
        .title("Welcome to agentOS")
        .default_width(560)
        .child(&content)
        .build();
    window.add_css_class("seven-ui");
    window.add_css_class("agentos-launcher");
    let welcome = window.clone();
    setup.connect_clicked(move |_| {
        let _ = commands.send(Command::Setup);
        welcome.close();
    });
    let welcome = window.clone();
    later.connect_clicked(move |_| welcome.close());
    window.present();
}
