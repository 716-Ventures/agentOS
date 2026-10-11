//! Dedicated native PTY host. Rendering a document never attaches or sends input.
use super::pty_transport::Session;
use super::*;
pub struct PtyView {
    pub widget: gtk::Box,
    pub view: Rc<ui::TerminalView>,
    pub attach: gtk::Button,
    session: Rc<RefCell<Option<Session>>>,
    timer: Option<glib::SourceId>,
    available: Rc<Cell<bool>>,
    clipboard: Rc<terminal_actions::ClipboardActions>,
}
impl PtyView {
    pub fn new(label: &str, source: &str, activity: &str) -> Self {
        let view = Rc::new(ui::TerminalView::new(label).unwrap());
        let clipboard = Rc::new(terminal_actions::ClipboardActions::install(&view));
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
        let available = Rc::new(Cell::new(true));
        let availability = available.clone();
        let fault = Rc::new(RefCell::new(None::<String>));
        let failure = fault.clone();
        let (state, terminal, message) = (session.clone(), view.clone(), notice.clone());
        let (job, activity) = (
            source.strip_prefix("broker:").unwrap().to_string(),
            activity.to_string(),
        );
        attach.connect_clicked(move |_| {
            if !availability.get() || state.borrow().is_some() {
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
        let actions = clipboard.clone();
        detach.connect_clicked(move |_| {
            terminal.set_attached(false);
            actions.set_attached(false);
            state.borrow_mut().take();
            message.set_text("Detached · running work continues independently");
        });
        let (state, terminal, message) = (session.clone(), Rc::downgrade(&view), notice.clone());
        let failure = fault.clone();
        view.on_input(move |bytes| {
            if let Some(owned) = state.borrow().as_ref() {
                // Never truncate a paste or silently discard its suffix.
                if let Err(error) = owned.write(bytes) {
                    owned.cancel();
                    if let Some(terminal) = terminal.upgrade() {
                        terminal.set_attached(false);
                    }
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
        let availability = available.clone();
        let actions = clipboard.clone();
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
                    a.set_sensitive(availability.get());
                }
            } else {
                terminal.set_attached(false);
                d.set_sensitive(false);
                a.set_sensitive(availability.get());
            }
            actions.set_attached(terminal.input_enabled());
            glib::ControlFlow::Continue
        });
        Self {
            widget,
            view,
            attach,
            session,
            timer: Some(timer),
            available,
            clipboard,
        }
    }
    pub fn reconcile(&self, label: &str, available: bool) {
        self.available.set(available);
        if self.view.heading.selection_bounds().is_none() {
            self.view.heading.set_text(label);
        }
        self.attach
            .set_sensitive(available && self.session.borrow().is_none());
        if !available {
            self.view.set_attached(false);
            self.clipboard.set_attached(false);
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

#[cfg(test)]
mod tests {
    use super::*;
    /// Run only in the private Wayland/real-broker fixture in tests/pty_broker.py.
    #[test]
    #[ignore]
    fn manual_detach_restores_attach_without_a_source_refresh() {
        gtk::init().unwrap();
        let job = std::env::var("AGENT_OS_PTY_TEST_JOB").unwrap();
        let socket = std::env::var("AGENT_OS_PTY_TEST_SOCKET").unwrap();
        std::env::set_var("AGENT_OS_BROKER_SOCKET", socket);
        let view = PtyView::new(
            "Interactive fixture λ 日本語",
            &format!("broker:{job}"),
            "1",
        );
        let window = gtk::Window::builder().child(&view.widget).build();
        window.present();
        let pump = |predicate: &dyn Fn() -> bool| {
            let deadline = std::time::Instant::now() + Duration::from_secs(8);
            loop {
                while glib::MainContext::default().pending() {
                    glib::MainContext::default().iteration(false);
                }
                if predicate() {
                    break;
                }
                assert!(
                    std::time::Instant::now() < deadline,
                    "Terminal controls did not reach the expected state without a source refresh"
                );
                std::thread::sleep(Duration::from_millis(10));
            }
        };
        view.reconcile("Interactive fixture λ 日本語", false);
        pump(&|| !view.attach.is_sensitive());
        assert!(!view.view.input_enabled());
        view.reconcile("Interactive fixture λ 日本語", true);
        view.attach.emit_clicked();
        pump(&|| view.view.input_enabled());
        assert!(!view.attach.is_sensitive());
        let detach = view
            .widget
            .last_child()
            .unwrap()
            .last_child()
            .unwrap()
            .downcast::<gtk::Button>()
            .unwrap();
        detach.emit_clicked();
        pump(&|| view.attach.is_sensitive());
        assert!(!view.view.input_enabled());
        // Reattach to the same running work, then let a source outage detach it.
        view.attach.emit_clicked();
        pump(&|| view.view.input_enabled());
        view.reconcile("Interactive fixture λ 日本語", false);
        pump(&|| !view.attach.is_sensitive() && !view.view.input_enabled());
        // Several timer ticks must not resurrect an unavailable source.
        let until = std::time::Instant::now() + Duration::from_millis(150);
        while std::time::Instant::now() < until {
            glib::MainContext::default().iteration(false);
            assert!(!view.attach.is_sensitive());
            std::thread::sleep(Duration::from_millis(10));
        }
        view.reconcile("Interactive fixture λ 日本語", true);
        assert!(view.attach.is_sensitive());
        assert!(
            !view.view.input_enabled(),
            "Source recovery attached without a human action"
        );
        view.attach.emit_clicked();
        pump(&|| view.view.input_enabled());
        drop(detach);
        let released = Rc::downgrade(&view.view);
        window.set_child(None::<&gtk::Widget>);
        window.close();
        drop(window);
        drop(view);
        pump(&|| released.upgrade().is_none());
        println!("PASS: real broker native attach/detach/reattach, unavailable-source controls and reader cleanup");
    }
}
