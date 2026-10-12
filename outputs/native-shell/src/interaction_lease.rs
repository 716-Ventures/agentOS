//! Native input protection includes mapped context menus during focus handoff.
use crate::transport::Command;
use gtk::prelude::*;
use seven_sixteen_ui::gtk::{self, glib};
use std::{
    cell::{Cell, RefCell},
    rc::Rc,
    sync::mpsc::Sender,
};

fn attached_popovers(widget: &gtk::Widget) -> Vec<gtk::Popover> {
    let mut pending = vec![widget.clone()];
    let mut popovers = Vec::new();
    while let Some(widget) = pending.pop() {
        if let Ok(popover) = widget.clone().downcast::<gtk::Popover>() {
            popovers.push(popover);
        }
        let mut child = widget.first_child();
        while let Some(widget) = child {
            child = widget.next_sibling();
            pending.push(widget);
        }
    }
    popovers
}

pub fn lease(widget: &gtk::Widget, surface: &str, id: &str, commands: &Sender<Command>) {
    let focus = gtk::EventControllerFocus::new();
    let active = Rc::new(Cell::new(false));
    let (surface, element, commands) = (surface.to_owned(), id.to_owned(), commands.clone());
    let publish: Rc<dyn Fn(bool)> = Rc::new(move |begin| {
        if active.replace(begin) != begin {
            let _ = commands.send(Command::Lease {
                surface: surface.clone(),
                element: element.clone(),
                begin,
            });
        }
    });
    // Collection menus are attached before this hook is installed. Hold weak
    // references so signal handlers cannot retain a removed widget subtree.
    let popovers = attached_popovers(widget);
    let tracked = popovers
        .iter()
        .map(|popover| popover.downgrade())
        .collect::<Vec<_>>();
    let weak_widget = widget.downgrade();
    let weak_focus = focus.downgrade();
    let changed = publish.clone();
    let refresh: Rc<dyn Fn()> = Rc::new(move || {
        let window = weak_widget
            .upgrade()
            .and_then(|widget| widget.root())
            .and_then(|root| root.downcast::<gtk::Window>().ok());
        let held = window.is_some_and(|window| {
            // GTK can briefly deactivate the parent while its popup owns
            // focus. Dismissal, rather than that transition, ends menu input.
            tracked
                .iter()
                .any(|popover| popover.upgrade().is_some_and(|popover| popover.is_mapped()))
                || window.is_active()
                    && weak_focus
                        .upgrade()
                        .is_some_and(|focus| focus.contains_focus())
        });
        changed(held);
    });
    let changed = refresh.clone();
    focus.connect_contains_focus_notify(move |_| changed());
    for popover in popovers {
        let changed = refresh.clone();
        popover.connect_map(move |_| changed());
        let changed = refresh.clone();
        popover.connect_unmap(move |_| changed());
    }
    let connection: Rc<RefCell<Option<(glib::WeakRef<gtk::Window>, glib::SignalHandlerId)>>> =
        Rc::new(RefCell::new(None));
    widget.connect_root_notify(move |widget| {
        let window = widget
            .root()
            .and_then(|root| root.downcast::<gtk::Window>().ok());
        if let (Some(window), Some((previous, _))) = (&window, connection.borrow().as_ref()) {
            if previous.upgrade().as_ref() == Some(window) {
                refresh();
                return;
            }
        }
        if let Some((window, handler)) = connection.borrow_mut().take() {
            if let Some(window) = window.upgrade() {
                window.disconnect(handler);
            }
        }
        publish(false);
        if let Some(window) = window {
            let changed = refresh.clone();
            let handler = window.connect_is_active_notify(move |_| changed());
            *connection.borrow_mut() = Some((window.downgrade(), handler));
        }
        refresh();
    });
    widget.add_controller(focus);
}
