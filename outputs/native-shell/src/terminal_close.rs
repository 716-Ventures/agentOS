//! Protect human-owned terminal work without changing the PTY size or workspace.
use super::*;
use std::os::fd::AsRawFd;
use vte4::prelude::*;

fn running(terminal: &vte4::Terminal, shell: i32) -> bool {
    if shell <= 0 {
        return false;
    }
    let foreground = terminal
        .pty()
        .map(|pty| unsafe { libc::tcgetpgrp(pty.fd().as_raw_fd()) })
        .unwrap_or(-1);
    if foreground > 0 && foreground != shell {
        return true;
    }
    // Background jobs also lose their terminal on close. Inspect only the
    // direct children of this window's owned shell, never other login work.
    std::fs::read_to_string(format!("/proc/{shell}/task/{shell}/children"))
        .is_ok_and(|children| !children.trim().is_empty())
}

pub struct Guard {
    panel: gtk::Box,
    body: glib::WeakRef<gtk::Widget>,
    cancel: gtk::Button,
    window: glib::WeakRef<gtk::ApplicationWindow>,
    terminal: glib::WeakRef<vte4::Terminal>,
    clipboard: Rc<terminal_actions::ClipboardActions>,
    ready: Rc<Cell<bool>>,
    child: Rc<Cell<i32>>,
    closed: Rc<Cell<bool>>,
    forced: Cell<bool>,
}
impl Guard {
    pub fn new(
        window: &gtk::ApplicationWindow,
        overlay: &gtk::Overlay,
        terminal: &vte4::Terminal,
        clipboard: Rc<terminal_actions::ClipboardActions>,
        ready: Rc<Cell<bool>>,
        child: Rc<Cell<i32>>,
        closed: Rc<Cell<bool>>,
    ) -> Rc<Self> {
        let panel = gtk::Box::builder()
            .orientation(gtk::Orientation::Vertical)
            .spacing(12)
            .accessible_role(gtk::AccessibleRole::AlertDialog)
            .halign(gtk::Align::Center)
            .valign(gtk::Align::Start)
            .margin_top(24)
            .margin_start(16)
            .margin_end(16)
            .visible(false)
            .build();
        panel.add_css_class("terminal-close-panel");
        panel.update_property(&[
            gtk::accessible::Property::Label("Close terminal?"),
            gtk::accessible::Property::Modal(true),
        ]);
        let content = ui::column(12);
        content.set_margin_top(20);
        content.set_margin_bottom(20);
        content.set_margin_start(20);
        content.set_margin_end(20);
        panel.append(&content);
        let title = ui::text("Close terminal?", true);
        title.set_selectable(false);
        content.append(&title);
        let message = ui::text(
            "A program is still running. Closing this terminal will end it.",
            false,
        );
        message.set_selectable(false);
        message.set_wrap(true);
        message.set_max_width_chars(42);
        let explanation = gtk::ScrolledWindow::builder()
            .hscrollbar_policy(gtk::PolicyType::Never)
            .vscrollbar_policy(gtk::PolicyType::Automatic)
            .propagate_natural_height(true)
            .max_content_height(180)
            .propagate_natural_width(true)
            .max_content_width(680)
            .child(&message)
            .build();
        explanation.set_overlay_scrolling(false);
        content.append(&explanation);
        let actions = ui::row(12);
        actions.set_halign(gtk::Align::End);
        let cancel = ui::button("Cancel", ButtonVariant::Outline, false);
        let close = ui::button("Close terminal", ButtonVariant::Destructive, false);
        actions.append(&cancel);
        actions.append(&close);
        content.append(&actions);
        overlay.add_overlay(&panel);
        overlay.set_measure_overlay(&panel, false);
        let guard = Rc::new(Self {
            panel,
            body: overlay.child().expect("Terminal content").downgrade(),
            cancel: cancel.clone(),
            window: window.downgrade(),
            terminal: terminal.downgrade(),
            clipboard,
            ready,
            child,
            closed,
            forced: Cell::new(false),
        });
        let target = Rc::downgrade(&guard);
        cancel.connect_clicked(move |_| {
            if let Some(guard) = target.upgrade() {
                guard.cancel();
            }
        });
        let target = Rc::downgrade(&guard);
        close.connect_clicked(move |_| {
            if let Some(guard) = target.upgrade() {
                guard.force();
                if let Some(window) = guard.window.upgrade() {
                    window.close();
                }
            }
        });
        let keys = gtk::EventControllerKey::new();
        keys.set_propagation_phase(gtk::PropagationPhase::Capture);
        let target = Rc::downgrade(&guard);
        keys.connect_key_pressed(move |_, key, _, modifiers| {
            if let Some(guard) = target.upgrade() {
                if guard.panel.is_visible()
                    && matches!(key, gtk::gdk::Key::Tab | gtk::gdk::Key::ISO_Left_Tab)
                {
                    let direction = if modifiers.contains(gtk::gdk::ModifierType::SHIFT_MASK)
                        || key == gtk::gdk::Key::ISO_Left_Tab
                    {
                        gtk::DirectionType::TabBackward
                    } else {
                        gtk::DirectionType::TabForward
                    };
                    if !guard.panel.child_focus(direction) {
                        if let Some(window) = guard.window.upgrade() {
                            gtk::prelude::GtkWindowExt::set_focus(&window, gtk::Widget::NONE);
                        }
                        guard.panel.child_focus(direction);
                    }
                    return glib::Propagation::Stop;
                }
                if guard.panel.is_visible() && key == gtk::gdk::Key::Escape {
                    guard.cancel();
                    return glib::Propagation::Stop;
                }
            }
            glib::Propagation::Proceed
        });
        window.add_controller(keys);
        guard
    }
    pub fn allow_close(&self) -> bool {
        if self.forced.get() || self.closed.get() {
            return true;
        }
        let Some(terminal) = self.terminal.upgrade() else {
            return true;
        };
        if !running(&terminal, self.child.get()) {
            return true;
        }
        self.clipboard.dismiss();
        self.ready.set(false);
        self.clipboard.set_attached(false);
        terminal.set_input_enabled(false);
        if let Some(body) = self.body.upgrade() {
            body.set_sensitive(false);
        }
        self.panel.set_visible(true);
        if let Some(window) = self.window.upgrade() {
            window.set_default_widget(Some(&self.cancel));
        }
        self.cancel.grab_focus();
        if let Ok(path) = std::env::var("AGENT_OS_TERMINAL_CLOSE_CAPTURE") {
            let window = self.window.clone();
            glib::timeout_add_local_once(Duration::from_millis(350), move || {
                if let Some(window) = window.upgrade() {
                    let _ = system_bar::capture(&window, &path);
                }
            });
        }
        false
    }
    fn cancel(&self) {
        self.panel.set_visible(false);
        if let Some(body) = self.body.upgrade() {
            body.set_sensitive(true);
        }
        if let Some(window) = self.window.upgrade() {
            window.set_default_widget(gtk::Widget::NONE);
        }
        let ready = self.child.get() > 0 && !self.closed.get();
        self.ready.set(ready);
        self.clipboard.set_attached(ready);
        if let Some(terminal) = self.terminal.upgrade() {
            terminal.set_input_enabled(ready);
            terminal.grab_focus();
        }
    }
    pub fn force(&self) {
        self.forced.set(true);
    }
}
