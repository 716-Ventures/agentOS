//! Native terminal clipboard actions share selection and explicit-attach guards.
use super::*;
use gtk::gio;
use vte4::prelude::*;

struct Host {
    terminal: vte4::Terminal,
    widget: gtk::Widget,
    enabled: Rc<dyn Fn() -> bool>,
}
impl Host {
    fn input_enabled(&self) -> bool {
        (self.enabled)()
    }
}

pub struct ClipboardActions {
    host: Rc<Host>,
    paste: gio::SimpleAction,
    menu: gtk::Popover,
}

impl ClipboardActions {
    pub fn install(view: &Rc<ui::TerminalView>) -> Self {
        let guarded = Rc::downgrade(view);
        Self::install_host(
            Rc::new(Host {
                terminal: view.terminal.clone(),
                widget: view.widget.clone().upcast(),
                enabled: Rc::new(move || {
                    guarded.upgrade().is_some_and(|view| view.input_enabled())
                }),
            }),
            true,
        )
    }
    pub fn install_local(
        terminal: &vte4::Terminal,
        parent: &gtk::Box,
        ready: Rc<Cell<bool>>,
    ) -> Self {
        Self::install_host(
            Rc::new(Host {
                terminal: terminal.clone(),
                widget: parent.clone().upcast(),
                enabled: Rc::new(move || ready.get()),
            }),
            false,
        )
    }
    fn install_host(view: Rc<Host>, attached_only: bool) -> Self {
        let group = gio::SimpleActionGroup::new();
        let copy = gio::SimpleAction::new("copy", None);
        copy.set_enabled(view.terminal.has_selection());
        let terminal = Rc::downgrade(&view);
        copy.connect_activate(move |_, _| {
            if let Some(view) = terminal.upgrade() {
                if view.terminal.has_selection() {
                    view.terminal.copy_clipboard_format(vte4::Format::Text);
                }
            }
        });
        let action = copy.downgrade();
        view.terminal.connect_selection_changed(move |terminal| {
            if let Some(action) = action.upgrade() {
                action.set_enabled(terminal.has_selection());
            }
        });
        let paste = gio::SimpleAction::new("paste", None);
        paste.set_enabled(view.input_enabled());
        let terminal = Rc::downgrade(&view);
        paste.connect_activate(move |_, _| {
            if let Some(view) = terminal.upgrade() {
                // Recheck at invocation: a menu may remain open across detach.
                if view.input_enabled() {
                    view.terminal.paste_clipboard();
                }
            }
        });
        group.add_action(&copy);
        group.add_action(&paste);
        view.widget.insert_action_group("terminal", Some(&group));
        // Generated menu items exported empty accessible names in the guest.
        // Use explicit native names/roles and the same guarded GActions.
        let items = gtk::Box::new(gtk::Orientation::Vertical, 0);
        let menu = gtk::Popover::builder()
            .has_arrow(false)
            .accessible_role(gtk::AccessibleRole::Menu)
            .child(&items)
            .build();
        for (label, action) in [("Copy", "terminal.copy"), ("Paste", "terminal.paste")] {
            let item = gtk::Button::builder()
                .label(label)
                .action_name(action)
                .accessible_role(gtk::AccessibleRole::MenuItem)
                .build();
            item.add_css_class("flat");
            item.update_property(&[gtk::accessible::Property::Label(label)]);
            let popup = menu.downgrade();
            item.connect_clicked(move |_| {
                if let Some(popup) = popup.upgrade() {
                    popup.popdown();
                }
            });
            items.append(&item);
        }
        menu.set_parent(&view.widget);
        let terminal = Rc::downgrade(&view);
        menu.connect_closed(move |_| {
            if let Some(view) = terminal.upgrade() {
                // Restore local widget focus without requesting seat focus
                // or activating a different application.
                if view.terminal.root().is_some() {
                    view.terminal.grab_focus();
                }
            }
        });
        let click = gtk::GestureClick::new();
        click.set_button(3);
        click.set_propagation_phase(gtk::PropagationPhase::Capture);
        let (popup, terminal) = (menu.downgrade(), Rc::downgrade(&view));
        click.connect_pressed(move |gesture, _, x, y| {
            if let (Some(popup), Some(view)) = (popup.upgrade(), terminal.upgrade()) {
                gesture.set_state(gtk::EventSequenceState::Claimed);
                show_menu(&popup, &view, x, y);
            }
        });
        view.terminal.add_controller(click);

        let keys = gtk::EventControllerKey::new();
        keys.set_propagation_phase(gtk::PropagationPhase::Capture);
        let actions = group.downgrade();
        let (popup, terminal) = (menu.downgrade(), Rc::downgrade(&view));
        keys.connect_key_pressed(move |_, key, _, modifiers| {
            use gtk::gdk::{Key, ModifierType as M};
            let relevant = M::CONTROL_MASK
                | M::SHIFT_MASK
                | M::ALT_MASK
                | M::SUPER_MASK
                | M::META_MASK
                | M::HYPER_MASK;
            let held = modifiers & relevant;
            if key == Key::Menu && held.is_empty() || key == Key::F10 && held == M::SHIFT_MASK {
                if let (Some(popup), Some(view)) = (popup.upgrade(), terminal.upgrade()) {
                    show_menu(
                        &popup,
                        &view,
                        f64::from(view.terminal.width()) / 2.0,
                        f64::from(view.terminal.height()) / 2.0,
                    );
                }
                return glib::Propagation::Stop;
            }
            if modifiers & relevant != (M::CONTROL_MASK | M::SHIFT_MASK) {
                return glib::Propagation::Proceed;
            }
            let action = if matches!(key, Key::c | Key::C) {
                "copy"
            } else if matches!(key, Key::v | Key::V) {
                "paste"
            } else {
                return glib::Propagation::Proceed;
            };
            if let Some(actions) = actions.upgrade() {
                actions.activate_action(action, None);
            }
            glib::Propagation::Stop
        });
        view.terminal.add_controller(keys);
        view.terminal.set_tooltip_text(Some(
            "Copy: Ctrl+Shift+C · Paste: Ctrl+Shift+V (attached only)",
        ));
        view.terminal.update_property(&[gtk::accessible::Property::Description("Ctrl+Shift+C copies selected terminal text. Ctrl+Shift+V pastes only while attached. Copy and Paste are also available in the context menu. Ctrl+C remains program input.")]);
        if !attached_only {
            view.terminal
                .set_tooltip_text(Some("Copy: Ctrl+Shift+C · Paste: Ctrl+Shift+V"));
            view.terminal.update_property(&[gtk::accessible::Property::Description("Ctrl+Shift+C copies selected terminal text. Ctrl+Shift+V pastes into the local shell. Copy and Paste are also available in the context menu. Ctrl+C remains program input.")]);
        }
        Self {
            paste,
            menu,
            host: view,
        }
    }

    pub fn verify_popup(&self) {
        // Capture fixtures have no kernel input serial. Normal mouse/Menu/
        // Shift+F10 paths above retain their ordinary grabbing popover.
        self.menu.set_autohide(false);
        show_menu(
            &self.menu,
            &self.host,
            f64::from(self.host.terminal.width()) / 2.0,
            f64::from(self.host.terminal.height()) / 2.0,
        );
    }
    pub fn close(&self) {
        self.dismiss();
        if self.menu.parent().is_some() {
            self.menu.unparent();
        }
    }
    pub fn dismiss(&self) {self.menu.popdown();}
    pub fn set_attached(&self, attached: bool) {
        self.paste.set_enabled(attached);
    }
}

fn show_menu(menu: &gtk::Popover, view: &Host, x: f64, y: f64) {
    if let Some(point) = view
        .terminal
        .compute_point(&view.widget, &gtk::graphene::Point::new(x as f32, y as f32))
    {
        menu.set_pointing_to(Some(&gtk::gdk::Rectangle::new(
            point.x() as i32,
            point.y() as i32,
            1,
            1,
        )));
        menu.popup();
    }
}

impl Drop for ClipboardActions {
    fn drop(&mut self) {
        self.close();
    }
}
