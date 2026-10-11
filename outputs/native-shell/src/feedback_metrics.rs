//! Opt-in input-to-presentation receipts for the actual GTK root surface.
//! No key codes, text, document identity, or estimated GDK timings are recorded.
use crate::gtk::{self, glib, prelude::*};
use gdk4_wayland::prelude::WaylandSurfaceExtManual;
use serde_json::json;
use std::{
    cell::RefCell,
    io::Write,
    os::unix::fs::OpenOptionsExt,
    path::PathBuf,
    rc::Rc,
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};
use wayland_client::{protocol::wl_registry, Connection, Dispatch, EventQueue, Proxy, QueueHandle};
use wayland_protocols::wp::presentation_time::client::{wp_presentation, wp_presentation_feedback};
const LIMIT: usize = 256;
static NEXT: AtomicU64 = AtomicU64::new(0);
#[derive(Default)]
struct State {
    presentation: Option<wp_presentation::WpPresentation>,
    clock: Option<u32>,
    requested: usize,
    discarded: usize,
    invalid: usize,
    values: Vec<u32>,
}
impl Dispatch<wl_registry::WlRegistry, ()> for State {
    fn event(
        s: &mut Self,
        registry: &wl_registry::WlRegistry,
        event: wl_registry::Event,
        _: &(),
        _: &Connection,
        q: &QueueHandle<Self>,
    ) {
        if let wl_registry::Event::Global {
            name,
            interface,
            version,
        } = event
        {
            if interface == "wp_presentation" {
                s.presentation = Some(registry.bind(name, version.min(2), q, ()));
            }
        }
    }
}
impl Dispatch<wp_presentation::WpPresentation, ()> for State {
    fn event(
        s: &mut Self,
        _: &wp_presentation::WpPresentation,
        event: wp_presentation::Event,
        _: &(),
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        if let wp_presentation::Event::ClockId { clk_id } = event {
            s.clock = Some(clk_id);
        }
    }
}
fn latency_ms(clock: Option<u32>, seconds: u64, nanoseconds: u32, input_ms: u32) -> Option<u32> {
    if clock != Some(libc::CLOCK_MONOTONIC as u32) || nanoseconds >= 1_000_000_000 {
        return None;
    }
    let displayed_ms = seconds
        .checked_mul(1000)?
        .checked_add(u64::from(nanoseconds) / 1_000_000)? as u32;
    let elapsed = displayed_ms.wrapping_sub(input_ms);
    (elapsed < 2000).then_some(elapsed)
}
impl Dispatch<wp_presentation_feedback::WpPresentationFeedback, u32> for State {
    fn event(
        s: &mut Self,
        _: &wp_presentation_feedback::WpPresentationFeedback,
        event: wp_presentation_feedback::Event,
        input_ms: &u32,
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        match event {
            wp_presentation_feedback::Event::Presented {
                tv_sec_hi,
                tv_sec_lo,
                tv_nsec,
                ..
            } => {
                let seconds = (u64::from(tv_sec_hi) << 32) | u64::from(tv_sec_lo);
                if let Some(elapsed) = latency_ms(s.clock, seconds, tv_nsec, *input_ms) {
                    s.values.push(elapsed);
                } else {
                    s.invalid += 1;
                }
            }
            wp_presentation_feedback::Event::Discarded => s.discarded += 1,
            _ => {}
        }
    }
}
struct Recorder {
    queue: EventQueue<State>,
    state: State,
    path: PathBuf,
}
impl Recorder {
    fn publish(&self) {
        let mut values = self.state.values.clone();
        values.sort_unstable();
        let percentile = |fraction: f64| {
            values.get(((values.len() as f64 * fraction).ceil() as usize).saturating_sub(1))
        };
        let report = json!({"format":1,"clock_id":self.state.clock,"requested":self.state.requested,"presented":values.len(),"discarded":self.state.discarded,"invalid":self.state.invalid,"pending":self.state.requested-values.len()-self.state.discarded-self.state.invalid,"sample_limit":LIMIT,"p50_ms":percentile(0.5),"p95_ms":percentile(0.95),"max_ms":values.last(),"meaning":"Wayland key event timestamp to acknowledged presentation of the next GTK root surface commit; virtual display evidence is not physical display qualification"});
        let tmp = self.path.with_extension("tmp");
        let result = (|| -> std::io::Result<()> {
            let mut file = std::fs::OpenOptions::new()
                .create_new(true)
                .write(true)
                .mode(0o600)
                .open(&tmp)?;
            file.write_all(report.to_string().as_bytes())?;
            std::fs::rename(&tmp, &self.path)
        })();
        if result.is_err() {
            let _ = std::fs::remove_file(tmp);
        }
    }
}
impl Drop for Recorder {
    fn drop(&mut self) {
        if let Some(p) = &self.state.presentation {
            p.destroy();
        }
    }
}
/// Called once after the native window is mapped; disabled in normal sessions.
pub fn install(window: &gtk::ApplicationWindow) {
    if std::env::var("AGENT_OS_FEEDBACK_METRICS").as_deref() != Ok("1") {
        return;
    }
    let Some(directory) = std::env::var_os("AGENT_OS_METRICS_DIR")
        .map(PathBuf::from)
        .filter(|p| p.is_absolute() && p.is_dir())
    else {
        return;
    };
    let Some(display) = gtk::prelude::WidgetExt::display(window)
        .downcast::<gdk4_wayland::WaylandDisplay>()
        .ok()
        .and_then(|d| d.wl_display())
    else {
        return;
    };
    let Some(backend) = display.backend().upgrade() else {
        return;
    };
    let connection = Connection::from_backend(backend);
    let mut queue = connection.new_event_queue::<State>();
    let _registry = connection.display().get_registry(&queue.handle(), ());
    let mut state = State::default();
    if queue.roundtrip(&mut state).is_err() || queue.roundtrip(&mut state).is_err() {
        return;
    }
    if state.clock != Some(libc::CLOCK_MONOTONIC as u32) || state.presentation.is_none() {
        return;
    }
    let recorder = Rc::new(RefCell::new(Recorder {
        queue,
        state,
        path: directory.join(format!(
            "feedback-{}-{}.json",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        )),
    }));
    recorder.borrow().publish();
    let controller = gtk::EventControllerKey::new();
    controller.set_propagation_phase(gtk::PropagationPhase::Capture);
    let weak_window = window.downgrade();
    let captured = recorder.clone();
    controller.connect_key_pressed(move |controller, _, _, _| {
        if let Some(surface) = weak_window
            .upgrade()
            .and_then(|w| w.surface())
            .and_then(|s| s.downcast::<gdk4_wayland::WaylandSurface>().ok())
            .and_then(|s| s.wl_surface())
        {
            if let Some(event) = controller.current_event() {
                let mut recorder = captured.borrow_mut();
                if recorder.state.requested < LIMIT {
                    recorder.state.presentation.as_ref().unwrap().feedback(
                        &surface,
                        &recorder.queue.handle(),
                        event.time(),
                    );
                    recorder.state.requested += 1;
                    // GTK owns the following buffer commit; never commit its surface here.
                    let _ = recorder.queue.flush();
                    recorder.publish();
                }
            }
        }
        glib::Propagation::Proceed
    });
    window.add_controller(controller);
    let weak = Rc::downgrade(&recorder);
    let weak_window = window.downgrade();
    glib::timeout_add_local(Duration::from_millis(5), move || {
        if weak_window.upgrade().is_none() {
            return glib::ControlFlow::Break;
        }
        let Some(recorder) = weak.upgrade() else {
            return glib::ControlFlow::Break;
        };
        let mut recorder = recorder.borrow_mut();
        let Recorder { queue, state, .. } = &mut *recorder;
        // GDK reads the shared socket. Dispatch only our foreign-display event queue.
        match queue.dispatch_pending(state) {
            Ok(0) => {}
            Ok(_) => recorder.publish(),
            Err(_) => return glib::ControlFlow::Break,
        }
        glib::ControlFlow::Continue
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn key_clock_wrap_and_millisecond_quantization_are_preserved() {
        let display_ms = u64::from(u32::MAX) + 20;
        assert_eq!(
            latency_ms(
                Some(1),
                display_ms / 1000,
                ((display_ms % 1000) * 1_000_000 + 999_999) as u32,
                u32::MAX - 10
            ),
            Some(30)
        );
    }
    #[test]
    fn unknown_clock_future_input_and_invalid_receipts_do_not_become_fast_samples() {
        assert_eq!(latency_ms(None, 10, 0, 10000), None);
        assert_eq!(latency_ms(Some(0), 10, 0, 10000), None);
        assert_eq!(latency_ms(Some(1), 10, 0, 10001), None);
        assert_eq!(latency_ms(Some(1), 10, 0, 8000), None);
        assert_eq!(latency_ms(Some(1), 10, 1_000_000_000, 10000), None);
        assert_eq!(latency_ms(Some(1), u64::MAX, 0, 10000), None);
    }
}
