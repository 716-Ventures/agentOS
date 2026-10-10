use smithay::{
    backend::input::{
        AbsolutePositionEvent, Axis, AxisSource, ButtonState, Event, InputBackend, InputEvent,
        KeyState, KeyboardKeyEvent, PointerAxisEvent, PointerButtonEvent, PointerMotionEvent,
    },
    input::{
        keyboard::FilterResult,
        pointer::{AxisFrame, ButtonEvent, MotionEvent, RelativeMotionEvent},
    },
    reexports::wayland_server::protocol::wl_surface::WlSurface,
    utils::SERIAL_COUNTER,
};

use crate::state::Smallvil;

impl Smallvil {
    fn clamp_pointer(
        &self,
        position: smithay::utils::Point<f64, smithay::utils::Logical>,
    ) -> Option<smithay::utils::Point<f64, smithay::utils::Logical>> {
        let outputs = self
            .space
            .outputs()
            .filter_map(|output| self.space.output_geometry(output))
            .map(|r| crate::pointer_geometry::OutputRect {
                x: r.loc.x,
                y: r.loc.y,
                width: r.size.w,
                height: r.size.h,
            });
        crate::pointer_geometry::clamp((position.x, position.y), outputs).map(Into::into)
    }

    fn move_pointer(
        &mut self,
        pos: smithay::utils::Point<f64, smithay::utils::Logical>,
        time: u32,
    ) {
        let Some(pointer) = self.seat.get_pointer() else {
            return;
        };
        let under = self.surface_under(pos);
        pointer.motion(
            self,
            under,
            &MotionEvent {
                location: pos,
                serial: SERIAL_COUNTER.next_serial(),
                time,
            },
        );
        pointer.frame(self);
    }

    pub fn process_input_event<I: InputBackend>(&mut self, event: InputEvent<I>) {
        match event {
            InputEvent::Keyboard { event, .. } => {
                let serial = SERIAL_COUNTER.next_serial();
                let time = Event::time_msec(&event);

                let key = event.key_code().raw();
                let state = event.state();
                let action = self
                    .seat
                    .get_keyboard()
                    .unwrap()
                    .input(
                        self,
                        event.key_code(),
                        state,
                        serial,
                        time,
                        |data, modifiers, handle| {
                            if state == KeyState::Released && data.suppressed_keys.remove(&key) {
                                return FilterResult::Intercept(None);
                            }
                            #[cfg(feature = "direct-display")]
                            if state == KeyState::Pressed && modifiers.ctrl && modifiers.alt {
                                let symbol = handle.modified_sym().raw();
                                if (0xffbe..=0xffc3).contains(&symbol) {
                                    if let Some(session) = data.direct_session.as_mut() {
                                        use smithay::backend::session::Session;
                                        if let Err(error) =
                                            session.change_vt((symbol - 0xffbe + 1) as i32)
                                        {
                                            eprintln!("VT switch failed: {error}");
                                        }
                                        data.suppressed_keys.insert(key);
                                        return FilterResult::Intercept(None);
                                    }
                                }
                            }
                            if state == KeyState::Pressed && data.bridge.is_some() {
                                if let Some(action) = crate::shortcuts::decode(
                                    modifiers.ctrl,
                                    modifiers.alt,
                                    modifiers.shift,
                                    handle.modified_sym().raw(),
                                ) {
                                    data.suppressed_keys.insert(key);
                                    return FilterResult::Intercept(Some(action));
                                }
                            }
                            FilterResult::Forward
                        },
                    )
                    .flatten();
                if let Some(action) = action {
                    self.shortcut(action)
                }
            }
            InputEvent::PointerMotion { event, .. } => {
                let Some(pointer) = self.seat.get_pointer() else {
                    return;
                };
                let delta = event.delta();
                let unaccelerated = event.delta_unaccel();
                if ![delta.x, delta.y, unaccelerated.x, unaccelerated.y]
                    .iter()
                    .all(|v| v.is_finite())
                {
                    return;
                }
                let current = pointer.current_location();
                let Some(pos) = self.clamp_pointer(current + delta) else {
                    return;
                };
                let under = self.surface_under(current);
                pointer.relative_motion(
                    self,
                    under,
                    &RelativeMotionEvent {
                        delta,
                        delta_unaccel: unaccelerated,
                        utime: event.time(),
                    },
                );
                self.move_pointer(pos, event.time_msec());
            }
            InputEvent::PointerMotionAbsolute { event, .. } => {
                let Some(geometry) = self
                    .space
                    .outputs()
                    .find_map(|output| self.space.output_geometry(output))
                else {
                    return;
                };
                let pos = event.position_transformed(geometry.size) + geometry.loc.to_f64();
                if let Some(pos) = self.clamp_pointer(pos) {
                    self.move_pointer(pos, event.time_msec());
                }
            }
            InputEvent::PointerButton { event, .. } => {
                let pointer = self.seat.get_pointer().unwrap();
                let keyboard = self.seat.get_keyboard().unwrap();

                let serial = SERIAL_COUNTER.next_serial();

                let button = event.button_code();

                let button_state = event.state();

                if ButtonState::Pressed == button_state && !pointer.is_grabbed() {
                    if let Some((window, _loc)) = self
                        .space
                        .element_under(pointer.current_location())
                        .map(|(w, l)| (w.clone(), l))
                    {
                        if let Some(bridge) = &self.bridge {
                            use smithay::reexports::wayland_server::Resource;
                            let id = format!("{:?}", window.toplevel().unwrap().wl_surface().id());
                            bridge
                                .input(&id, serde_json::json!({"kind":"focus","element_id":null}));
                            // The committed scene applies focus. A stale command must not
                            // leave the seat focused on a different surface than the core.
                        } else {
                            self.space.raise_element(&window, true);
                            keyboard.set_focus(
                                self,
                                Some(window.toplevel().unwrap().wl_surface().clone()),
                                serial,
                            );
                            self.space.elements().for_each(|window| {
                                window.toplevel().unwrap().send_pending_configure();
                            });
                        }
                    } else {
                        self.space.elements().for_each(|window| {
                            window.set_activated(false);
                            window.toplevel().unwrap().send_pending_configure();
                        });
                        keyboard.set_focus(self, Option::<WlSurface>::None, serial);
                    }
                };

                pointer.button(
                    self,
                    &ButtonEvent {
                        button,
                        state: button_state,
                        serial,
                        time: event.time_msec(),
                    },
                );
                pointer.frame(self);
            }
            InputEvent::PointerAxis { event, .. } => {
                let source = event.source();

                let horizontal_amount = event.amount(Axis::Horizontal).unwrap_or_else(|| {
                    event.amount_v120(Axis::Horizontal).unwrap_or(0.0) * 15.0 / 120.
                });
                let vertical_amount = event.amount(Axis::Vertical).unwrap_or_else(|| {
                    event.amount_v120(Axis::Vertical).unwrap_or(0.0) * 15.0 / 120.
                });
                let horizontal_amount_discrete = event.amount_v120(Axis::Horizontal);
                let vertical_amount_discrete = event.amount_v120(Axis::Vertical);

                let mut frame = AxisFrame::new(event.time_msec()).source(source);
                if horizontal_amount != 0.0 {
                    frame = frame.value(Axis::Horizontal, horizontal_amount);
                    if let Some(discrete) = horizontal_amount_discrete {
                        frame = frame.v120(Axis::Horizontal, discrete as i32);
                    }
                }
                if vertical_amount != 0.0 {
                    frame = frame.value(Axis::Vertical, vertical_amount);
                    if let Some(discrete) = vertical_amount_discrete {
                        frame = frame.v120(Axis::Vertical, discrete as i32);
                    }
                }

                if source == AxisSource::Finger {
                    if event.amount(Axis::Horizontal) == Some(0.0) {
                        frame = frame.stop(Axis::Horizontal);
                    }
                    if event.amount(Axis::Vertical) == Some(0.0) {
                        frame = frame.stop(Axis::Vertical);
                    }
                }

                let pointer = self.seat.get_pointer().unwrap();
                pointer.axis(self, frame);
                pointer.frame(self);
            }
            _ => {}
        }
    }
}
