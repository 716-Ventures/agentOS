//! Let a focused client prepare input damage before the next fixed scanout.
//! Frame callbacks are scheduling hints; completed DRM presentation remains the
//! only source of presentation receipts. This never queues an extra GPU frame.
use crate::Smallvil;
use smithay::{
    desktop::Window,
    output::Output,
    wayland::compositor::{with_states, SurfaceAttributes},
};
use std::time::{Duration, Instant};

fn interval(output: &Output) -> Duration {
    let refresh = output
        .current_mode()
        .filter(|mode| mode.refresh > 0)
        .map(|mode| mode.refresh)
        .unwrap_or(60_000);
    Duration::from_secs_f64(1000.0 / f64::from(refresh))
}
impl Smallvil {
    fn focused_frame_target(&self) -> Option<(Window, Output)> {
        let focus = self.seat.get_keyboard()?.current_focus()?;
        let window = self
            .space
            .elements()
            .find(|window| {
                window
                    .toplevel()
                    .is_some_and(|top| top.wl_surface() == &focus)
            })?
            .clone();
        let output = self.space.outputs_for_element(&window).into_iter().next()?;
        Some((window, output))
    }
    pub fn request_input_frame(&mut self) {
        let Some((window, output)) = self.focused_frame_target() else {
            return;
        };
        self.input_frame_surface = window.toplevel().map(|top| top.wl_surface().clone());
        self.input_frame_wake
            .request(Instant::now(), interval(&output));
    }
    pub fn wake_input_frame(&mut self) {
        if self.direct_active != Some(true) {
            self.input_frame_wake.cancel();
            self.input_frame_surface = None;
            return;
        }
        if self.input_frame_surface.is_none() {
            return;
        }
        let Some((window, output)) = self.focused_frame_target() else {
            self.input_frame_wake.cancel();
            self.input_frame_surface = None;
            return;
        };
        let surface = window.toplevel().unwrap().wl_surface();
        if self.input_frame_surface.as_ref() != Some(surface) {
            self.input_frame_wake.cancel();
            self.input_frame_surface = None;
            return;
        }
        let pending = with_states(surface, |states| {
            !states
                .cached_state
                .get::<SurfaceAttributes>()
                .current()
                .frame_callbacks
                .is_empty()
        });
        if self
            .input_frame_wake
            .ready(Instant::now(), pending, interval(&output))
        {
            window.send_frame(
                &output,
                self.start_time.elapsed(),
                Some(Duration::ZERO),
                |_, _| Some(output.clone()),
            );
            self.input_frame_surface = None;
            self.input_frame_wakeups = self.input_frame_wakeups.saturating_add(1);
        }
        if !self.input_frame_wake.pending() {
            self.input_frame_surface = None;
        }
    }
}
