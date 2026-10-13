//! Human-owned local PTYs, separate from attached broker work terminals.
use super::*;
use vte4::prelude::*;
thread_local! {static TERMINALS:RefCell<Vec<glib::WeakRef<vte4::Terminal>>>=const {RefCell::new(Vec::new())};}

fn theme(view: &vte4::Terminal, light: bool, scale: f64) {
    let foreground = gtk::gdk::RGBA::parse(if light { "#202a34" } else { "#ecf0f4" }).unwrap();
    let background = gtk::gdk::RGBA::parse(if light { "#ffffff" } else { "#11171d" }).unwrap();
    view.set_colors(Some(&foreground), Some(&background), &[]);
    view.set_font(Some(&gtk::pango::FontDescription::from_string(&format!(
        "monospace {}",
        12.0 * scale.clamp(1.0, 3.0)
    ))));
}
pub fn apply_theme(light: bool, scale: f64) {
    TERMINALS.with(|terminals| {
        terminals.borrow_mut().retain(|view| {
            if let Some(view) = view.upgrade() {
                theme(&view, light, scale);
                true
            } else {
                false
            }
        })
    });
}

fn observe(value: Value) {
    if let Some(path) = std::env::var_os("AGENT_OS_LOCAL_TERMINAL_OBSERVATION") {
        let path = PathBuf::from(path);
        let temporary = path.with_extension("tmp");
        if std::fs::write(&temporary, value.to_string()).is_ok() {
            let _ = std::fs::rename(temporary, path);
        }
    }
}

pub fn open(
    app: &gtk::Application,
    setup: bool,
    ready: impl FnOnce(Result<String, String>) + 'static,
) {
    let identity = format!("agentos.local-terminal.{:032x}", nonce());
    let terminal = vte4::Terminal::new();
    terminal.set_scrollback_lines(10000);
    terminal.set_hexpand(true);
    terminal.set_vexpand(true);
    terminal.update_property(&[gtk::accessible::Property::Label(if setup {
        "Setup terminal"
    } else {
        "Local terminal"
    })]);
    let preferences = preferences::read();
    let light = preferences["appearance"] == "light";
    theme(
        &terminal,
        light,
        preferences["text_scale"].as_f64().unwrap_or(1.0),
    );
    TERMINALS.with(|terminals| {
        let mut terminals = terminals.borrow_mut();
        terminals.retain(|view| view.upgrade().is_some());
        terminals.push(terminal.downgrade());
    });
    terminal.set_margin_start(12);
    terminal.set_margin_end(12);
    terminal.set_margin_top(8);
    terminal.set_margin_bottom(12);
    let copy = ui::button("Copy", ButtonVariant::Ghost, false);
    copy.set_sensitive(false);
    let paste = ui::button("Paste", ButtonVariant::Ghost, false);
    paste.set_sensitive(false);
    let actions = ui::row(4);
    actions.set_halign(gtk::Align::End);
    actions.set_margin_start(8);
    actions.set_margin_end(8);
    actions.append(&copy);
    actions.append(&paste);
    let selection = copy.downgrade();
    terminal.connect_selection_changed(move |view| {
        if let Some(button) = selection.upgrade() {
            button.set_sensitive(view.has_selection());
        }
    });
    let view = terminal.downgrade();
    copy.connect_clicked(move |_| {
        if let Some(view) = view.upgrade() {
            view.copy_clipboard_format(vte4::Format::Text);
            view.grab_focus();
        }
    });
    let view = terminal.downgrade();
    paste.connect_clicked(move |_| {
        if let Some(view) = view.upgrade() {
            view.paste_clipboard();
            view.grab_focus();
        }
    });
    let scroll = gtk::ScrolledWindow::builder()
        .hscrollbar_policy(gtk::PolicyType::Never)
        .vexpand(true)
        .child(&terminal)
        .build();
    scroll.add_css_class("local-terminal-console");
    let body = ui::column(0);
    body.append(&actions);
    body.append(&scroll);
    let window = gtk::ApplicationWindow::builder()
        .application(app)
        .title(if setup { "Setup" } else { "Terminal" })
        .default_width(880)
        .default_height(560)
        .child(&body)
        .build();
    window.add_css_class("seven-ui");
    desktop_theme::titlebar(&window);
    let app_id = identity.clone();
    window.connect_map(move |window| {
        if let Some(surface) = window
            .surface()
            .and_then(|surface| surface.downcast::<gdk4_wayland::WaylandToplevel>().ok())
        {
            surface.set_application_id(&app_id);
        }
    });
    let keys = gtk::EventControllerKey::new();
    let view = terminal.downgrade();
    let target = window.downgrade();
    keys.connect_key_pressed(move |_, key, _, modifiers| {
        if modifiers
            .contains(gtk::gdk::ModifierType::CONTROL_MASK | gtk::gdk::ModifierType::SHIFT_MASK)
        {
            if let Some(view) = view.upgrade() {
                match key.to_unicode().map(|c| c.to_ascii_lowercase()) {
                    Some('c') => {
                        view.copy_clipboard_format(vte4::Format::Text);
                        return glib::Propagation::Stop;
                    }
                    Some('v') => {
                        view.paste_clipboard();
                        return glib::Propagation::Stop;
                    }
                    Some('w') => {
                        if let Some(window) = target.upgrade() {
                            window.close();
                        }
                        return glib::Propagation::Stop;
                    }
                    _ => {}
                }
            }
        }
        glib::Propagation::Proceed
    });
    terminal.add_controller(keys);
    let child = Rc::new(Cell::new(0));
    let closed = Rc::new(Cell::new(false));
    let exited = Rc::new(Cell::new(false));
    let pid = child.clone();
    let closing = closed.clone();
    window.connect_close_request(move |_| {
        closing.set(true);
        let pid = pid.get();
        if pid > 0 {
            unsafe {
                libc::kill(pid, libc::SIGHUP);
            }
        }
        glib::Propagation::Proceed
    });
    let pid = child.clone();
    let target = window.downgrade();
    let ended = exited.clone();
    terminal.connect_child_exited(move |_, status| {
        observe(json!({"pid":pid.get(),"exited":true,"status":status}));
        ended.set(true);
        pid.set(0);
        if let Some(window) = target.upgrade() {
            window.close();
        }
    });
    let target = window.downgrade();
    app.connect_shutdown(move |_| {
        if let Some(window) = target.upgrade() {
            window.close();
        }
    });
    window.present();
    terminal.grab_focus();
    let target = window.downgrade();
    let view = terminal.downgrade();
    let paste = paste.downgrade();
    let program = if setup {
        "/usr/local/bin/agent-os-setup"
    } else {
        "/bin/bash"
    };
    let home = std::env::var("HOME").unwrap_or_else(|_| "/".into());
    terminal.spawn_async(
        vte4::PtyFlags::DEFAULT,
        Some(&home),
        &[program],
        &["TERM=xterm-256color", "COLORTERM=truecolor"],
        glib::SpawnFlags::DEFAULT,
        || {},
        5000,
        gtk::gio::Cancellable::NONE,
        move |result| match result {
            Ok(pid) => {
                observe(json!({"pid":pid.0,"exited":false}));
                child.set(pid.0);
                if closed.get() {
                    if !exited.get() {
                        unsafe {
                            libc::kill(pid.0, libc::SIGHUP);
                        }
                    }
                    return;
                }
                if let Some(button) = paste.upgrade() {
                    button.set_sensitive(true);
                }
                if std::env::var("AGENT_OS_LOCAL_TERMINAL_VERIFY").as_deref() == Ok("1") {
                    if let Some(view) = view.upgrade() {
                        view.feed_child("printf 'native-terminal-λ\\n'\n".as_bytes());
                    }
                }
                if let Ok(path) = std::env::var("AGENT_OS_LOCAL_TERMINAL_CAPTURE") {
                    let capture = target.clone();
                    glib::timeout_add_local_once(Duration::from_millis(700), move || {
                        if let Some(window) = capture.upgrade() {
                            let _ = system_bar::capture(&window, &path);
                        }
                    });
                }
                ready(Ok(identity));
            }
            Err(error) => {
                if let Some(window) = target.upgrade() {
                    window.close();
                }
                ready(Err(error.to_string()));
            }
        },
    );
}
