//! Dedicated native PTY host. Rendering a document never attaches or sends input.
use super::pty_transport::Session;
use super::*;
pub struct PtyView {
    pub widget: gtk::Box,
    pub view: Rc<ui::TerminalView>,
    pub attach: gtk::Button,
    session: Rc<RefCell<Option<Session>>>,
    timer: Option<glib::SourceId>,
}
impl PtyView {
    pub fn new(label: &str, source: &str, activity: &str) -> Self {
        let view = Rc::new(ui::TerminalView::new(label).unwrap());
        let widget = ui::column(8);
        widget.append(&view.widget);
        let notice = ui::text("Detached · attach explicitly to send keyboard input", false);
        widget.append(&notice);
        let row = ui::row(8);
        let attach = ui::button("Attach terminal", ButtonVariant::Outline, false);
        let detach = ui::button("Detach terminal", ButtonVariant::Outline, true);
        row.append(&attach);
        row.append(&detach);
        widget.append(&row);
        let session = Rc::new(RefCell::new(None::<Session>));
        let fault = Rc::new(RefCell::new(None::<String>));
        let failure = fault.clone();
        let (state, terminal, message) = (session.clone(), view.clone(), notice.clone());
        let (job, activity) = (
            source.strip_prefix("broker:").unwrap().to_string(),
            activity.to_string(),
        );
        attach.connect_clicked(move |_| {
            if state.borrow().is_some() {
                return;
            }
            match Session::start(
                transport::broker_socket(),
                job.clone(),
                activity.clone(),
                terminal.grid(),
            ) {
                Ok(owned) => {
                    *failure.borrow_mut() = None;
                    *state.borrow_mut() = Some(owned);
                }
                Err(error) => message.set_text(&error),
            }
        });
        let (state, terminal, message) = (session.clone(), view.clone(), notice.clone());
        detach.connect_clicked(move |_| {
            terminal.set_attached(false);
            state.borrow_mut().take();
            message.set_text("Detached · running work continues independently");
        });
        let (state, terminal, message) = (session.clone(), view.clone(), notice.clone());
        let failure = fault.clone();
        view.on_input(move |bytes| {
            if let Some(owned) = state.borrow().as_ref() {
                // Never truncate a paste or silently discard its suffix.
                if let Err(error) = owned.write(bytes) {
                    owned.cancel();
                    terminal.set_attached(false);
                    message.set_text(&error);
                    *failure.borrow_mut() = Some(error);
                }
            }
        });
        let (state, terminal, message, a, d) = (
            session.clone(),
            view.clone(),
            notice,
            attach.clone(),
            detach,
        );
        let timer = glib::timeout_add_local(Duration::from_millis(20), move || {
            // Release all state borrows before feeding VTE: display protocol
            // responses may synchronously emit its commit signal.
            let update = {
                let session = state.borrow();
                session.as_ref().map(|owned| {
                    owned.resize(terminal.grid());
                    let mut display = owned.display.lock().unwrap();
                    let chunks = display.chunks.drain(..).collect::<Vec<_>>();
                    (
                        chunks,
                        display.attached && !owned.cancelled(),
                        display.finished,
                        display.notice.clone(),
                    )
                })
            };
            if let Some((chunks, attached, finished, notice)) = update {
                terminal.set_attached(attached);
                for (bytes, reset) in chunks {
                    let _ = terminal.feed(&bytes, reset);
                }
                message.set_text(fault.borrow().as_deref().unwrap_or(&notice));
                a.set_sensitive(false);
                d.set_sensitive(!finished);
                if finished {
                    state.borrow_mut().take();
                    a.set_sensitive(true);
                }
            } else {
                terminal.set_attached(false);
                d.set_sensitive(false);
            }
            glib::ControlFlow::Continue
        });
        Self {
            widget,
            view,
            attach,
            session,
            timer: Some(timer),
        }
    }
    pub fn reconcile(&self, label: &str, available: bool) {
        if self.view.heading.selection_bounds().is_none() {
            self.view.heading.set_text(label);
        }
        self.attach
            .set_sensitive(available && self.session.borrow().is_none());
        if !available {
            self.view.set_attached(false);
            self.session.borrow_mut().take();
        }
    }
}
impl Drop for PtyView {
    fn drop(&mut self) {
        if let Some(timer) = self.timer.take() {
            timer.remove();
        }
        self.view.set_attached(false);
        self.session.borrow_mut().take();
    }
}
