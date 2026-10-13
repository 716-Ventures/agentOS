//! Direct desktop preferences, independent of model availability and agent telemetry.
use super::*;
pub struct Settings {
    pub window: gtk::ApplicationWindow,
    pages: BTreeMap<&'static str, gtk::Box>,
}
impl Settings {
    pub fn new(app: &gtk::Application) -> Self {
        let stack = gtk::Stack::new();
        stack.set_hexpand(true);
        stack.set_vexpand(true);
        // Preferences change immediately; switching pages needs no choreography.
        stack.set_transition_type(gtk::StackTransitionType::None);
        let navigation = ui::column(4);
        navigation.add_css_class("settings-navigation");
        navigation.set_margin_top(16);
        navigation.set_margin_start(12);
        navigation.set_margin_end(12);
        navigation.set_width_request(150);
        let mut pages = BTreeMap::new();
        let mut first = None::<gtk::ToggleButton>;
        for title in [
            "Appearance",
            "Activities",
            "Workspace",
            "Accessibility",
            "Storage",
            "Setup",
        ] {
            let page = ui::column(16);
            page.set_margin_top(24);
            page.set_margin_bottom(24);
            page.set_margin_start(24);
            page.set_margin_end(24);
            let heading = ui::text(title, true);
            heading.set_selectable(false);
            page.append(&heading);
            let scroll = gtk::ScrolledWindow::builder()
                .hscrollbar_policy(gtk::PolicyType::Automatic)
                .child(&page)
                .build();
            stack.add_titled(&scroll, Some(title), title);
            let button = gtk::ToggleButton::with_label(title);
            button.add_css_class("settings-category");
            button.set_group(first.as_ref());
            let target = stack.downgrade();
            button.connect_toggled(move |button| {
                if button.is_active() {
                    if let Some(stack) = target.upgrade() {
                        stack.set_visible_child_name(title);
                    }
                }
            });
            navigation.append(&button);
            if first.is_none() {
                first = Some(button.clone());
                button.set_active(true);
            }
            pages.insert(title, page);
        }
        let body = ui::row(0);
        body.append(&navigation);
        body.append(&gtk::Separator::new(gtk::Orientation::Vertical));
        body.append(&stack);
        let window = gtk::ApplicationWindow::builder()
            .application(app)
            .title("Desktop settings")
            .default_width(760)
            .default_height(540)
            .child(&body)
            .build();
        window.add_css_class("seven-ui");
        window.add_css_class("agentos-settings");
        desktop_theme::titlebar(&window);
        window.connect_map(|window| {
            if let Some(surface) = window
                .surface()
                .and_then(|s| s.downcast::<gdk4_wayland::WaylandToplevel>().ok())
            {
                surface.set_application_id("agentos.settings");
            }
        });
        window.connect_close_request(|window| {
            let body = window.child();
            window.set_child(gtk::Widget::NONE);
            window.set_visible(false);
            window.set_child(body.as_ref());
            glib::Propagation::Stop
        });
        window.connect_map(|window| {
            if let Ok(path) = std::env::var("AGENT_OS_SETTINGS_CAPTURE") {
                let target = window.downgrade();
                glib::timeout_add_local_once(Duration::from_millis(700), move || {
                    if let Some(window) = target.upgrade() {
                        let _ = system_bar::capture(&window, &path);
                    }
                });
            }
        });
        Self { window, pages }
    }
    pub fn append(&self, page: &str, widget: &impl IsA<gtk::Widget>) {
        self.pages[page].append(widget);
    }
    pub fn present(&self) {
        self.window.present();
    }
    pub fn close(&self) {
        self.window.close();
    }
}
