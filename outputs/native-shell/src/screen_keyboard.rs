//! Local input controls; never supplied by a presentation document or a model.
use super::*;

fn request(value: Value) -> Result<Value, String> {
    let path = std::env::var_os("AGENT_OS_COMPOSITOR_SOCKET")
        .map(PathBuf::from)
        .ok_or("Keyboard connection unavailable")?;
    transport::request_timeout(&path, &value, Duration::from_millis(300))
}

#[derive(Clone)]
struct Commands {
    sender: std::sync::mpsc::SyncSender<(std::time::Instant, u64, Value)>,
    latest: Arc<std::sync::atomic::AtomicU64>,
}
impl Commands {
    fn send(&self, value: Value) -> Result<(), String> {
        let sequence = self.latest.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1;
        self.sender.try_send((std::time::Instant::now(), sequence, value))
            .map_err(|_| "Keyboard busy; try again".to_owned())
    }
}
struct Input {
    commands: Commands,
    stop: Arc<std::sync::atomic::AtomicBool>,
    worker: Mutex<Option<std::thread::JoinHandle<()>>>,
}
impl Input {
    fn start(status: &gtk::Label) -> Self {
        let (commands, requests) = std::sync::mpsc::sync_channel::<(std::time::Instant, u64, Value)>(4);
        let latest = Arc::new(std::sync::atomic::AtomicU64::new(0));
        let stop = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let stopping = stop.clone();
        let replies = Arc::new(Mutex::new(None::<(u64, String)>));
        let results = replies.clone();
        let worker = std::thread::spawn(move || {
            while !stopping.load(std::sync::atomic::Ordering::Relaxed) {
                if let Ok((created, sequence, value)) = requests.recv_timeout(Duration::from_millis(50)) {
                    *results.lock().unwrap() = Some((sequence,
                        if std::time::Instant::now().duration_since(created)
                            > Duration::from_millis(150)
                        {
                            "Input expired; try again".into()
                        } else {
                            request(value).err().unwrap_or_default()
                        },
                    ));
                }
            }
        });
        let weak = status.downgrade();
        let current = latest.clone();
        glib::timeout_add_local(Duration::from_millis(50), move || {
            let Some(status) = weak.upgrade() else {
                return glib::ControlFlow::Break;
            };
            if let Some((sequence, value)) = replies.lock().unwrap().take() {
                if sequence != current.load(std::sync::atomic::Ordering::Relaxed) {
                    return glib::ControlFlow::Continue;
                }
                status.set_text(if value.is_empty() {
                    "Keyboard ready"
                } else {
                    &value
                });
            }
            glib::ControlFlow::Continue
        });
        Self {
            commands: Commands { sender: commands, latest },
            stop,
            worker: Mutex::new(Some(worker)),
        }
    }
}
impl Input {
    fn close(&self) {
        self.stop.store(true, std::sync::atomic::Ordering::Relaxed);
        if let Some(worker) = self.worker.lock().unwrap().take() {
            let _ = worker.join();
        }
    }
}

impl Drop for Input {
    fn drop(&mut self) {
        self.close();
    }
}

pub struct Keyboard {
    window: gtk::ApplicationWindow,
    _library: libloading::Library,
    input: Input,
}
impl Keyboard {
    pub fn new(app: &gtk::Application) -> Result<Self, String> {
        let root = ui::column(8);
        root.set_margin_top(12);
        root.set_margin_bottom(12);
        root.set_margin_start(12);
        root.set_margin_end(12);
        let body = ui::column(8);
        let window = gtk::ApplicationWindow::builder()
            .application(app)
            .title("On-screen keyboard")
            .decorated(false)
            .child(&root)
            .build();
        window.add_css_class("seven-ui");
        let library = system_bar::configure_keyboard(&window)?;
        let header = ui::row(12);
        let title = ui::text("On-screen keyboard", true);
        title.set_selectable(false);
        let status = ui::status("Keyboard ready");
        status.set_selectable(false);
        status.set_hexpand(true);
        status.set_xalign(0.0);
        status.set_wrap(false);
        status.set_ellipsize(gtk::pango::EllipsizeMode::End);
        let input = Input::start(&status);
        let close = ui::button("Hide keyboard", ButtonVariant::Ghost, false);
        close.set_focus_on_click(false);
        let weak = window.downgrade();
        close.connect_clicked(move |_| {
            if let Some(window) = weak.upgrade() {
                window.set_visible(false);
            }
        });
        header.append(&title);
        header.append(&status);
        header.append(&close);
        root.append(&header);
        root.append(
            &gtk::ScrolledWindow::builder()
                .hscrollbar_policy(gtk::PolicyType::Automatic)
                .vscrollbar_policy(gtk::PolicyType::Automatic)
                .propagate_natural_height(true)
                .max_content_height(280)
                .child(&body)
                .build(),
        );
        let modifiers = Rc::new(Cell::new(0u64));
        let shifts = Rc::new(RefCell::new(Vec::<(gtk::Button, String, String)>::new()));
        let letters = [
            "1234567890-=",
            "qwertyuiop[]\\",
            "asdfghjkl;'",
            "zxcvbnm,./",
        ];
        let upper = [
            "!@#$%^&*()_+",
            "QWERTYUIOP{}|",
            "ASDFGHJKL:\"",
            "ZXCVBNM<>?",
        ];
        for (index, (lower, upper)) in letters.into_iter().zip(upper).enumerate() {
            let row = ui::row(6);
            if index == 1 {
                append_key(
                    &row,
                    "Tab",
                    gtk::gdk::Key::Tab,
                    modifiers.clone(),
                    status.clone(),
                    input.commands.clone(),
                    None,
                );
            }
            for (lower, upper) in lower.chars().zip(upper.chars()) {
                let key = append_key(
                    &row,
                    &lower.to_string(),
                    symbol(lower),
                    modifiers.clone(),
                    status.clone(),
                    input.commands.clone(),
                    Some(lower),
                );
                shifts
                    .borrow_mut()
                    .push((key, lower.to_string(), upper.to_string()));
            }
            if index == 0 {
                append_key(
                    &row,
                    "Backspace",
                    gtk::gdk::Key::BackSpace,
                    modifiers.clone(),
                    status.clone(),
                    input.commands.clone(),
                    None,
                );
            }
            if index == 2 {
                append_key(
                    &row,
                    "Enter",
                    gtk::gdk::Key::Return,
                    modifiers.clone(),
                    status.clone(),
                    input.commands.clone(),
                    None,
                );
            }
            body.append(&row);
        }
        let row = ui::row(6);
        for (label, mask) in [("Shift", 1), ("Ctrl", 4), ("Alt", 8), ("Insert", 16)] {
            let button = ui::button(label, ButtonVariant::Outline, false);
            button.set_focus_on_click(false);
            button.update_state(&[gtk::accessible::State::Pressed(
                gtk::AccessibleTristate::False,
            )]);
            let selected = modifiers.clone();
            let shifts = shifts.clone();
            button.connect_clicked(move |button| {
                let value = selected.get() ^ mask;
                selected.set(value);
                let active = value & mask != 0;
                button.set_label(&if active {
                    format!("{label} on")
                } else {
                    label.to_owned()
                });
                button.update_state(&[gtk::accessible::State::Pressed(if active {
                    gtk::AccessibleTristate::True
                } else {
                    gtk::AccessibleTristate::False
                })]);
                if active {
                    button.add_css_class("suggested-action");
                } else {
                    button.remove_css_class("suggested-action");
                }
                for (button, lower, upper) in shifts.borrow().iter() {
                    button.set_label(if value & 1 != 0 { upper } else { lower });
                }
            });
            row.append(&button);
        }
        append_key(
            &row,
            "Escape",
            gtk::gdk::Key::Escape,
            modifiers.clone(),
            status.clone(),
            input.commands.clone(),
            None,
        );
        let space = append_key(
            &row,
            "Space",
            gtk::gdk::Key::space,
            modifiers.clone(),
            status.clone(),
            input.commands.clone(),
            None,
        );
        space.set_hexpand(true);
        for (label, key) in [
            ("Left", gtk::gdk::Key::Left),
            ("Down", gtk::gdk::Key::Down),
            ("Up", gtk::gdk::Key::Up),
            ("Right", gtk::gdk::Key::Right),
        ] {
            append_key(
                &row,
                label,
                key,
                modifiers.clone(),
                status.clone(),
                input.commands.clone(),
                None,
            );
        }
        body.append(&row);
        let navigation = ui::row(6);
        navigation.set_homogeneous(true);
        for (label, key) in [
            ("Home", gtk::gdk::Key::Home),
            ("End", gtk::gdk::Key::End),
            ("Page Up", gtk::gdk::Key::Page_Up),
            ("Page Down", gtk::gdk::Key::Page_Down),
            ("Delete", gtk::gdk::Key::Delete),
        ] {
            append_key(
                &navigation,
                label,
                key,
                modifiers.clone(),
                status.clone(),
                input.commands.clone(),
                None,
            );
        }
        body.append(&navigation);
        window.connect_close_request(|window| {
            window.set_visible(false);
            glib::Propagation::Stop
        });
        if let Ok(path) = std::env::var("AGENT_OS_KEYBOARD_CAPTURE") {
            let weak = window.downgrade();
            let dismissal = close.downgrade();
            glib::timeout_add_local(Duration::from_millis(100), move || {
                let Some(window) = weak.upgrade() else {
                    return glib::ControlFlow::Break;
                };
                if window.is_visible() && system_bar::capture(&window, &path) {
                    if let Some(bounds) = dismissal.upgrade().and_then(|button| button.compute_bounds(&window)) {
                        let geometry = json!({"window":[window.width(),window.height()],
                            "dismissal":[bounds.x(),bounds.y(),bounds.width(),bounds.height()]});
                        let _ = std::fs::write(PathBuf::from(&path).with_extension("json"), geometry.to_string());
                    }
                    glib::ControlFlow::Break
                } else {
                    glib::ControlFlow::Continue
                }
            });
        }
        Ok(Self {
            window,
            _library: library,
            input,
        })
    }
    pub fn close(&self) {
        self.window.set_visible(false);
        self.input.close();
    }
    pub fn toggle(&self) {
        self.window.set_visible(!self.window.is_visible());
        if self.window.is_visible() {
            let _ = self.input.commands.send(json!({"op":"keyboard.restore_focus"}));
        }
    }
}

fn append_key(
    row: &gtk::Box,
    label: &str,
    key: gtk::gdk::Key,
    modifiers: Rc<Cell<u64>>,
    status: gtk::Label,
    commands: Commands,
    character: Option<char>,
) -> gtk::Button {
    let button = ui::button(label, ButtonVariant::Outline, false);
    button.set_focus_on_click(false);
    button.set_hexpand(true);
    button.connect_clicked(move |button| {
        // Resolve against the live compositor keymap delivered to GDK. The
        // current compact palette covers ASCII plus navigation; it does not
        // replace IME input or claim a complete international layout picker.
        let symbol = if character.is_some() {button.label().and_then(|label|label.chars().next()).map(symbol).unwrap_or(key)} else {key};
        let mapping = button.display().map_keyval(symbol).and_then(|keys|keys.into_iter().find(|entry| entry.group()==0 && (0..=1).contains(&entry.level())));
        let result = if let Some(mapping) = mapping {commands.send(json!({"op":"keyboard.stroke","keycode":mapping.keycode(),"modifiers":modifiers.get() | if mapping.level()==1 {1} else {0}}))} else {Err("This key is unavailable in the current layout".into())};
        status.set_text(result.err().as_deref().unwrap_or("Sending input…"));
    });
    row.append(&button);
    button
}

fn symbol(character: char) -> gtk::gdk::Key {
    unsafe { glib::translate::from_glib(gtk::gdk::ffi::gdk_unicode_to_keyval(character as u32)) }
}
