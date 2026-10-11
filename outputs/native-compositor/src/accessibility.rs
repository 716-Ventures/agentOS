//! Opt-in session-local Orca keyboard monitor. No key history is retained.
use gio::glib::{self, variant::ToVariant};
use smithay::input::keyboard::{xkb, Keycode};
use std::{
    cell::RefCell,
    collections::{BTreeMap, BTreeSet},
    rc::Rc,
    time::{Duration, Instant},
};

const NAME: &str = "org.freedesktop.a11y.Manager";
const PATH: &str = "/org/freedesktop/a11y/Manager";
const INTERFACE: &str = "org.freedesktop.a11y.KeyboardMonitor";
const READER: &str = "org.gnome.Orca.KeyboardMonitor";
const XML: &str = r#"<node><interface name="org.freedesktop.a11y.KeyboardMonitor">
<method name="WatchKeyboard"/><method name="UnwatchKeyboard"/>
<method name="GrabKeyboard"/><method name="UngrabKeyboard"/>
<method name="SetKeyGrabs"><arg type="au" direction="in"/><arg type="a(uu)" direction="in"/></method>
<signal name="KeyEvent"><arg type="b"/><arg type="u"/><arg type="u"/><arg type="u"/><arg type="q"/></signal>
</interface></node>"#;

#[derive(Default)]
struct Rules {
    owner: Option<String>,
    verified: bool,
    watch: bool,
    grab: bool,
    modifiers: BTreeSet<u32>,
    strokes: BTreeSet<(u32, u32)>,
    held: BTreeMap<u32, u32>,
    consumed: BTreeSet<u32>,
    solo: Option<u32>,
    last_tap: Option<(u32, Instant)>,
}
impl Rules {
    fn event_destination(&self, consumed: bool) -> Option<&str> {
        (self.verified && (self.watch || consumed))
            .then_some(self.owner.as_deref())
            .flatten()
    }
    fn clear_owner(&mut self) {
        self.owner = None;
        self.verified = false;
        self.watch = false;
        self.grab = false;
        self.modifiers.clear();
        self.strokes.clear();
        self.solo = None;
        self.last_tap = None;
        // Keep consumed press identities until release, so clients never see an orphan key-up.
    }
    fn key(&mut self, code: u32, sym: u32, mask: u32, released: bool, now: Instant) -> bool {
        if released {
            self.held.remove(&code);
            if self.solo == Some(sym) {
                self.last_tap = Some((sym, now));
                self.solo = None;
            }
            return self.consumed.remove(&code);
        }
        let repeat = self.held.contains_key(&code);
        if repeat {
            return self.consumed.contains(&code);
        }
        let custom = self.modifiers.contains(&sym);
        let double_tap = !repeat
            && custom
            && self.last_tap.is_some_and(|(key, time)| {
                key == sym && now.duration_since(time) < Duration::from_millis(400)
            });
        let held_modifier = self.held.values().any(|s| self.modifiers.contains(s));
        if !repeat {
            if custom && self.held.is_empty() {
                self.solo = Some(sym);
            } else {
                self.solo = None;
                self.last_tap = None;
            }
        }
        self.held.insert(code, sym);
        let consume = self.owner.is_some()
            && !double_tap
            && (self.grab || custom || held_modifier || self.strokes.contains(&(sym, mask)));
        if double_tap {
            self.last_tap = None;
            self.solo = None;
        }
        if consume {
            self.consumed.insert(code);
        }
        consume
    }
}

fn process_start(pid: u32) -> Option<String> {
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    let fields: Vec<_> = stat.rsplit_once(") ")?.1.split_whitespace().collect();
    (fields.first() != Some(&"Z"))
        .then(|| fields.get(19).map(|s| s.to_string()))
        .flatten()
}
fn reader_owned_by_session(pid: u32, parent: u32, start: &str) -> bool {
    use std::os::unix::fs::MetadataExt;
    let check = || -> Option<bool> {
        let directory = std::path::PathBuf::from(format!("/proc/{pid}"));
        if directory.metadata().ok()?.uid() != unsafe { libc::getuid() } {
            return Some(false);
        }
        let stat = std::fs::read_to_string(directory.join("stat")).ok()?;
        let fields: Vec<_> = stat.rsplit_once(") ")?.1.split_whitespace().collect();
        if fields.get(1)?.parse::<u32>().ok()? != parent {
            return Some(false);
        }
        let parent_stat = std::fs::read_to_string(format!("/proc/{parent}/stat")).ok()?;
        let parent_fields: Vec<_> = parent_stat
            .rsplit_once(") ")?
            .1
            .split_whitespace()
            .collect();
        if *parent_fields.get(19)? != start {
            return Some(false);
        }
        Some(true)
    };
    check() == Some(true)
}
fn apply_method(
    rules: &mut Rules,
    method: &str,
    parameters: &glib::Variant,
    invocation: gio::DBusMethodInvocation,
) {
    match method {
        "WatchKeyboard" => rules.watch = true,
        "UnwatchKeyboard" => rules.watch = false,
        "GrabKeyboard" => rules.grab = true,
        "UngrabKeyboard" => rules.grab = false,
        "SetKeyGrabs" => {
            let Some((modifiers, strokes)) = parameters.get::<(Vec<u32>, Vec<(u32, u32)>)>() else {
                invocation.return_dbus_error(
                    "org.freedesktop.DBus.Error.InvalidArgs",
                    "Invalid key grabs",
                );
                return;
            };
            if modifiers.len() > 32 || strokes.len() > 512 {
                invocation.return_dbus_error(
                    "org.freedesktop.DBus.Error.LimitsExceeded",
                    "Too many key grabs",
                );
                return;
            }
            rules.modifiers = modifiers.into_iter().collect();
            rules.strokes = strokes.into_iter().collect();
        }
        _ => {
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod",
                "Unknown keyboard monitor operation",
            );
            return;
        }
    }
    invocation.return_value(Some(&().to_variant()));
}

pub struct Service {
    connection: gio::DBusConnection,
    rules: Rc<RefCell<Rules>>,
    state: xkb::State,
    parent: u32,
    parent_start: String,
    reader: Rc<RefCell<Option<(u32, String)>>>,
    registration: Option<gio::RegistrationId>,
    unwatch: Option<Box<dyn FnOnce()>>,
}
impl Service {
    pub fn start(keymap: String) -> Result<Self, Box<dyn std::error::Error>> {
        let connection = gio::bus_get_sync(gio::BusType::Session, gio::Cancellable::NONE)?;
        // DO_NOT_QUEUE: never replace another compositor's accessibility service.
        let reply = connection.call_sync(
            Some("org.freedesktop.DBus"),
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "RequestName",
            Some(&(NAME, 4u32).to_variant()),
            None,
            gio::DBusCallFlags::NONE,
            1000,
            gio::Cancellable::NONE,
        )?;
        if reply.get::<(u32,)>() != Some((1,)) {
            return Err("Accessibility manager already owned".into());
        }
        let rules = Rc::new(RefCell::new(Rules::default()));
        let appeared = rules.clone();
        let vanished = rules.clone();
        let watcher = gio::bus_watch_name_on_connection(
            &connection,
            READER,
            gio::BusNameWatcherFlags::NONE,
            move |_, _, owner| {
                let mut rules = appeared.borrow_mut();
                rules.clear_owner();
                rules.owner = Some(owner.to_owned());
            },
            move |_, _| vanished.borrow_mut().clear_owner(),
        );
        let info = gio::DBusNodeInfo::for_xml(XML)?
            .lookup_interface(INTERFACE)
            .unwrap();
        let methods = rules.clone();
        let parent = std::env::var("AGENT_OS_SESSION_OWNER_PID")?.parse::<u32>()?;
        let parent_start = std::env::var("AGENT_OS_SESSION_OWNER_START")?;
        let reader = Rc::new(RefCell::new(None::<(u32, String)>));
        let authorized = reader.clone();
        let method_parent_start = parent_start.clone();
        let pending = Rc::new(std::cell::Cell::new(0usize));
        let registration = connection
            .register_object(PATH, &info)
            .method_call(
                move |connection, sender, _, _, method, parameters, invocation| {
                    let Some(sender) = sender.map(str::to_owned) else {
                        invocation.return_dbus_error(
                            "org.freedesktop.DBus.Error.AccessDenied",
                            "Missing monitor identity",
                        );
                        return;
                    };
                    if methods.borrow().owner.as_deref() != Some(sender.as_str()) {
                        invocation.return_dbus_error(
                            "org.freedesktop.DBus.Error.AccessDenied",
                            "Only the session-owned Orca monitor may access keyboard input",
                        );
                        return;
                    }
                    if parameters.size() > 8192 {
                        invocation.return_dbus_error(
                            "org.freedesktop.DBus.Error.LimitsExceeded",
                            "Keyboard monitor request too large",
                        );
                        return;
                    }
                    if methods.borrow().verified {
                        apply_method(&mut methods.borrow_mut(), method, &parameters, invocation);
                        return;
                    }
                    if pending.get() >= 8 {
                        invocation.return_dbus_error(
                            "org.freedesktop.DBus.Error.LimitsExceeded",
                            "Monitor verification busy",
                        );
                        return;
                    }
                    pending.set(pending.get() + 1);
                    let methods = methods.clone();
                    let pending = pending.clone();
                    let method = method.to_owned();
                    let parent_start = method_parent_start.clone();
                    let authorized = authorized.clone();
                    connection.call(
                        Some("org.freedesktop.DBus"),
                        "/org/freedesktop/DBus",
                        "org.freedesktop.DBus",
                        "GetConnectionUnixProcessID",
                        Some(&(sender.as_str(),).to_variant()),
                        None,
                        gio::DBusCallFlags::NONE,
                        500,
                        gio::Cancellable::NONE,
                        move |result| {
                            pending.set(pending.get() - 1);
                            let pid = result.ok().and_then(|v| v.get::<(u32,)>());
                            let mut rules = methods.borrow_mut();
                            if rules.owner.as_deref() != Some(sender.as_str())
                                || !pid.is_some_and(|(pid,)| {
                                    reader_owned_by_session(pid, parent, &parent_start)
                                        && authorized.borrow().as_ref().is_some_and(
                                            |(expected, start)| {
                                                *expected == pid
                                                    && process_start(pid).as_deref()
                                                        == Some(start.as_str())
                                            },
                                        )
                                })
                            {
                                invocation.return_dbus_error(
                                    "org.freedesktop.DBus.Error.AccessDenied",
                                    "Monitor is not the session-owned Orca process",
                                );
                                return;
                            }
                            rules.verified = true;
                            apply_method(&mut rules, &method, &parameters, invocation);
                        },
                    );
                },
            )
            .build()?;
        let context = xkb::Context::new(xkb::CONTEXT_NO_FLAGS);
        let keymap = xkb::Keymap::new_from_string(
            &context,
            keymap,
            xkb::KEYMAP_FORMAT_TEXT_V1,
            xkb::KEYMAP_COMPILE_NO_FLAGS,
        )
        .ok_or("Invalid accessibility keymap")?;
        Ok(Self {
            connection,
            rules,
            state: xkb::State::new(&keymap),
            parent,
            parent_start,
            reader,
            registration: Some(registration),
            unwatch: Some(Box::new(move || gio::bus_unwatch_name(watcher))),
        })
    }
    pub fn register(
        &mut self,
        peer: Option<u32>,
        pid: Option<u64>,
        start: Option<&str>,
    ) -> Result<(), &'static str> {
        if peer != Some(self.parent)
            || process_start(self.parent).as_deref() != Some(self.parent_start.as_str())
        {
            return Err("Only the owning graphical session may register its reader");
        }
        let pid = pid
            .and_then(|p| u32::try_from(p).ok())
            .ok_or("Invalid reader PID")?;
        let start = start.ok_or("Reader start identity required")?;
        if process_start(pid).as_deref() != Some(start)
            || !reader_owned_by_session(pid, self.parent, &self.parent_start)
        {
            return Err("Reader is not the session's live child");
        }
        *self.reader.borrow_mut() = Some((pid, start.to_owned()));
        Ok(())
    }
    pub fn dispatch(&self) {
        let context = glib::MainContext::default();
        for _ in 0..16 {
            if !context.pending() {
                break;
            }
            context.iteration(false);
        }
        if self.connection.is_closed() {
            self.rules.borrow_mut().clear_owner();
        }
    }
    pub fn pause(&mut self) {
        self.state = xkb::State::new(&self.state.get_keymap());
        let mut rules = self.rules.borrow_mut();
        rules.held.clear();
        rules.consumed.clear();
        rules.solo = None;
        rules.last_tap = None;
    }
    pub fn reserved_vt(&self, code: Keycode) -> Option<i32> {
        let mask = self.state.serialize_mods(xkb::STATE_MODS_EFFECTIVE);
        let sym = crate::shortcuts::function_key(self.state.key_get_one_sym(code).raw());
        ((mask & 12) == 12 && (0xffbe..=0xffc3).contains(&sym)).then_some((sym as i32) - 0xffbe + 1)
    }
    pub fn key(&mut self, code: Keycode, released: bool) -> bool {
        let sym = self
            .rules
            .borrow()
            .held
            .get(&code.raw())
            .copied()
            .unwrap_or_else(|| self.state.key_get_one_sym(code).raw());
        let mask = self.state.serialize_mods(xkb::STATE_MODS_EFFECTIVE);
        let consume = self
            .rules
            .borrow_mut()
            .key(code.raw(), sym, mask, released, Instant::now());
        let unicode = self.state.key_get_utf32(code);
        let rules = self.rules.borrow();
        if let Some(owner) = rules.event_destination(consume) {
            if self
                .connection
                .emit_signal(
                    Some(owner),
                    PATH,
                    INTERFACE,
                    "KeyEvent",
                    Some(&(released, mask, sym, unicode, code.raw() as u16).to_variant()),
                )
                .is_err()
            {
                drop(rules);
                self.rules.borrow_mut().clear_owner();
                return consume;
            }
        }
        // Grabbed locks never change the application keyboard state. Still track
        // ordinary held modifiers here for assistive commands during full grabs.
        if !consume || !matches!(sym, 0xffe5 | 0xffe6 | 0xff7f | 0xff14) {
            self.state.update_key(
                code,
                if released {
                    xkb::KeyDirection::Up
                } else {
                    xkb::KeyDirection::Down
                },
            );
        }
        consume
    }
}
impl Drop for Service {
    fn drop(&mut self) {
        if let Some(unwatch) = self.unwatch.take() {
            unwatch();
        }
        if let Some(registration) = self.registration.take() {
            let _ = self.connection.unregister_object(registration);
        }
        let _ = self.connection.call_sync(
            Some("org.freedesktop.DBus"),
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "ReleaseName",
            Some(&(NAME,).to_variant()),
            None,
            gio::DBusCallFlags::NONE,
            500,
            gio::Cancellable::NONE,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn reader() -> Rules {
        Rules {
            owner: Some(":1.5".into()),
            verified: true,
            modifiers: BTreeSet::from([0xff63]),
            ..Rules::default()
        }
    }
    #[test]
    fn monitor_commands_consume_balanced_pairs_and_disconnect_releases_ownership() {
        let mut r = reader();
        let now = Instant::now();
        assert!(r.key(118, 0xff63, 0, false, now));
        assert!(r.key(43, 104, 0, false, now));
        r.clear_owner();
        assert!(r.key(43, 104, 0, true, now));
        assert!(r.key(118, 0xff63, 0, true, now));
        assert!(!r.key(38, 97, 0, false, now));
        assert!(!r.key(38, 97, 0, true, now));
    }
    #[test]
    fn replacement_bus_owner_cannot_receive_a_previous_readers_pending_key_release() {
        let mut r = reader();
        r.grab = true;
        let now = Instant::now();
        assert!(r.key(38, 97, 0, false, now));
        assert_eq!(r.event_destination(true), Some(":1.5"));
        r.clear_owner();
        r.owner = Some(":1.9".into()); // Name appearance precedes PID authentication.
        let consumed = r.key(38, 97, 0, true, now);
        assert!(
            consumed,
            "Never forward an orphan release into application input"
        );
        assert_eq!(r.event_destination(consumed), None);
    }
    #[test]
    fn grab_does_not_orphan_a_previously_forwarded_key_release() {
        let mut r = reader();
        let now = Instant::now();
        assert!(!r.key(38, 97, 0, false, now));
        r.grab = true;
        assert!(!r.key(38, 97, 0, true, now));
        assert!(r.key(39, 115, 0, false, now));
        r.grab = false;
        assert!(r.key(39, 115, 0, true, now));
    }
    #[test]
    fn custom_modifier_double_tap_restores_ordinary_key_behavior() {
        let mut r = reader();
        let now = Instant::now();
        assert!(r.key(118, 0xff63, 0, false, now));
        assert!(r.key(118, 0xff63, 0, true, now));
        assert!(!r.key(118, 0xff63, 0, false, now + Duration::from_millis(100)));
        assert!(!r.key(118, 0xff63, 0, true, now + Duration::from_millis(110)));
    }
    #[test]
    fn exact_mask_grab_and_watch_never_consume_unrelated_typing() {
        let mut r = reader();
        r.watch = true;
        r.strokes.insert((104, 4));
        let now = Instant::now();
        assert!(!r.key(43, 104, 0, false, now));
        assert!(!r.key(43, 104, 0, true, now));
        assert!(r.key(43, 104, 4, false, now));
        assert!(r.key(43, 104, 0, true, now));
    }
}
