use std::{ffi::OsString, sync::Arc};

use smithay::{
    desktop::{PopupManager, Space, Window, WindowSurfaceType},
    input::{Seat, SeatState},
    reexports::{
        calloop::{generic::Generic, EventLoop, Interest, LoopSignal, Mode, PostAction},
        wayland_server::{
            backend::{ClientData, ClientId, DisconnectReason},
            protocol::wl_surface::WlSurface,
            Display, DisplayHandle, Resource,
        },
    },
    utils::{Logical, Point},
    wayland::{
        compositor::{CompositorClientState, CompositorState},
        output::OutputManagerState,
        relative_pointer::RelativePointerManagerState,
        selection::{data_device::DataDeviceState, primary_selection::PrimarySelectionState},
        shell::xdg::XdgShellState,
        shm::ShmState,
        socket::ListeningSocketSource,
    },
};

use crate::CalloopData;

pub struct Smallvil {
    pub policy: crate::policy::Policy,
    pub bridge: Option<crate::bridge::Bridge>,
    pub applied_focus: Option<String>,
    pub viewport_offsets: std::collections::BTreeMap<String, (i32, i32)>,
    pub suppressed_keys: std::collections::BTreeSet<u32>,
    pub start_time: std::time::Instant,
    pub socket_name: OsString,
    pub display_handle: DisplayHandle,

    pub space: Space<Window>,
    pub loop_signal: LoopSignal,

    // Smithay State
    pub compositor_state: CompositorState,
    pub xdg_shell_state: XdgShellState,
    pub shm_state: ShmState,
    pub output_manager_state: OutputManagerState,
    pub _relative_pointer_manager: RelativePointerManagerState,
    pub seat_state: SeatState<Smallvil>,
    pub data_device_state: DataDeviceState,
    pub primary_selection_state: PrimarySelectionState,
    pub popups: PopupManager,

    pub drag_icon: Option<WlSurface>,
    pub drag_icon_render_submissions: u64,
    pub cursor_image: smithay::input::pointer::CursorImageStatus,
    pub direct_frames_presented: u64,
    pub direct_active: Option<bool>,
    pub direct_resume_error: Option<String>,
    pub presentation_state: Option<smithay::wayland::presentation::PresentationState>,
    #[cfg(feature = "direct-display")]
    pub direct_session: Option<smithay::backend::session::libseat::LibSeatSession>,
    pub seat: Seat<Self>,
}

impl Smallvil {
    pub fn new(event_loop: &mut EventLoop<CalloopData>, display: Display<Self>) -> Self {
        let start_time = std::time::Instant::now();

        let dh = display.handle();

        let compositor_state = CompositorState::new::<Self>(&dh);
        let xdg_shell_state = XdgShellState::new::<Self>(&dh);
        let shm_state = ShmState::new::<Self>(&dh, vec![]);
        let output_manager_state = OutputManagerState::new_with_xdg_output::<Self>(&dh);
        let relative_pointer_manager = RelativePointerManagerState::new::<Self>(&dh);
        let mut seat_state = SeatState::new();
        let data_device_state = DataDeviceState::new::<Self>(&dh);
        let primary_selection_state = PrimarySelectionState::new::<Self>(&dh);
        let popups = PopupManager::default();

        // A seat is a group of keyboards, pointer and touch devices.
        // A seat typically has a pointer and maintains a keyboard focus and a pointer focus.
        let mut seat: Seat<Self> = seat_state.new_wl_seat(&dh, "winit");

        // Notify clients that we have a keyboard, for the sake of the example we assume that keyboard is always present.
        // You may want to track keyboard hot-plug in real compositor.
        seat.add_keyboard(Default::default(), 200, 25).unwrap();

        // Notify clients that we have a pointer (mouse)
        // Here we assume that there is always pointer plugged in
        seat.add_pointer();

        // A space represents a two-dimensional plane. Windows and Outputs can be mapped onto it.
        //
        // Windows get a position and stacking order through mapping.
        // Outputs become views of a part of the Space and can be rendered via Space::render_output.
        let space = Space::default();

        let socket_name = Self::init_wayland_listener(display, event_loop);

        // Get the loop signal, used to stop the event loop
        let loop_signal = event_loop.get_signal();

        Self {
            policy: crate::policy::Policy::default(),
            bridge: std::env::var_os("AGENT_OS_COMPOSITOR_CORE")
                .map(|p| crate::bridge::Bridge::start(p.into())),
            applied_focus: None,
            viewport_offsets: Default::default(),
            suppressed_keys: Default::default(),
            start_time,
            display_handle: dh,

            space,
            loop_signal,
            socket_name,

            compositor_state,
            xdg_shell_state,
            shm_state,
            output_manager_state,
            _relative_pointer_manager: relative_pointer_manager,
            seat_state,
            data_device_state,
            primary_selection_state,
            popups,
            drag_icon: None,
            drag_icon_render_submissions: 0,
            cursor_image: smithay::input::pointer::CursorImageStatus::default_named(),
            direct_frames_presented: 0,
            direct_active: None,
            direct_resume_error: None,
            presentation_state: None,
            #[cfg(feature = "direct-display")]
            direct_session: None,
            seat,
        }
    }

    fn init_wayland_listener(
        display: Display<Smallvil>,
        event_loop: &mut EventLoop<CalloopData>,
    ) -> OsString {
        // Creates a new listening socket, automatically choosing the next available `wayland` socket name.
        let listening_socket = ListeningSocketSource::new_auto().unwrap();

        // Get the name of the listening socket.
        // Clients will connect to this socket.
        let socket_name = listening_socket.socket_name().to_os_string();

        let loop_handle = event_loop.handle();

        loop_handle
            .insert_source(listening_socket, move |client_stream, _, state| {
                // Inside the callback, you should insert the client into the display.
                //
                // You may also associate some data with the client when inserting the client.
                let peer = peer_identity(&client_stream);
                state
                    .display_handle
                    .insert_client(
                        client_stream,
                        Arc::new(ClientState {
                            peer,
                            ..ClientState::default()
                        }),
                    )
                    .unwrap();
            })
            .expect("Failed to init the wayland event source.");

        // You also need to add the display itself to the event loop, so that client events will be processed by wayland-server.
        loop_handle
            .insert_source(
                Generic::new(display, Interest::READ, Mode::Level),
                |_, display, state| {
                    // Safety: we don't drop the display
                    unsafe {
                        display
                            .get_mut()
                            .dispatch_clients(&mut state.state)
                            .unwrap();
                    }
                    Ok(PostAction::Continue)
                },
            )
            .unwrap();

        socket_name
    }

    fn view_area(&self, id: &str) -> Option<smithay::utils::Rectangle<i32, Logical>> {
        if let Some(bridge) = &self.bridge {
            let scene = bridge.scene.lock().unwrap();
            if let Some(area) = scene
                .surface_outputs
                .get(id)
                .and_then(|output| scene.output_areas.get(output))
            {
                return Some(smithay::utils::Rectangle::new(
                    (area.x, area.y).into(),
                    (area.width, area.height).into(),
                ));
            }
        }
        self.space
            .outputs()
            .next()
            .and_then(|output| self.space.output_geometry(output))
    }
    pub fn pan_view(&mut self, id: &str, x: i32, y: i32) -> Result<(), String> {
        let scene = self
            .bridge
            .as_ref()
            .ok_or("Shared compositor required")?
            .scene
            .lock()
            .unwrap()
            .clone();
        let rect = scene.rectangles.get(id).ok_or("Visible view required")?;
        let area = self.view_area(id).ok_or("Output unavailable")?;
        let offset = self.viewport_offsets.entry(id.into()).or_default();
        offset.0 = (offset.0 + x * (area.size.w * 3 / 4).max(1))
            .clamp(0, (rect.width - area.size.w).max(0));
        offset.1 = (offset.1 + y * (area.size.h * 3 / 4).max(1))
            .clamp(0, (rect.height - area.size.h).max(0));
        Ok(())
    }
    pub fn shortcut(&mut self, action: crate::shortcuts::Shortcut) {
        use crate::shortcuts::Shortcut;
        let Some(bridge) = &self.bridge else { return };
        let scene = bridge.scene.lock().unwrap().clone();
        let ids = scene.visible.iter().cloned().collect::<Vec<_>>();
        if ids.is_empty() {
            return;
        }
        let current = scene
            .focus
            .as_ref()
            .filter(|id| ids.contains(id))
            .unwrap_or(&ids[0]);
        if let Shortcut::Cycle(reverse) = action {
            let index = ids.iter().position(|id| id == current).unwrap_or(0);
            let next = if reverse {
                (index + ids.len() - 1) % ids.len()
            } else {
                (index + 1) % ids.len()
            };
            bridge.input(
                &ids[next],
                serde_json::json!({"kind":"focus","element_id":null}),
            );
            return;
        }
        if let Shortcut::Pan { x, y } = action {
            let id = current.clone();
            let _ = self.pan_view(&id, x, y);
            return;
        }
        if action == Shortcut::Undo {
            bridge.undo_input();
            return;
        }
        if action == Shortcut::Close {
            if let Some(window) = self
                .space
                .elements()
                .find(|w| format!("{:?}", w.toplevel().unwrap().wl_surface().id()) == *current)
            {
                window.toplevel().unwrap().send_close();
            }
            return;
        }
        let edit = match action {
            Shortcut::Maximize => serde_json::json!({"kind":"maximize"}),
            Shortcut::Restore => serde_json::json!({"kind":"restore"}),
            Shortcut::Float | Shortcut::Nudge { .. } => {
                let mut rect =
                    scene
                        .rectangles
                        .get(current)
                        .copied()
                        .unwrap_or(crate::policy::Rect {
                            x: 0,
                            y: 0,
                            width: 640,
                            height: 480,
                        });
                if let Shortcut::Nudge { x, y, resize } = action {
                    if resize {
                        rect.width += x;
                        rect.height += y;
                    } else {
                        rect.x += x;
                        rect.y += y;
                    }
                }
                if let Some(area) = self.view_area(current) {
                    rect.width = rect.width.max(80).min(area.size.w);
                    rect.height = rect.height.max(32).min(area.size.h);
                    rect.x = rect
                        .x
                        .clamp(area.loc.x, area.loc.x + area.size.w - rect.width);
                    rect.y = rect
                        .y
                        .clamp(area.loc.y, area.loc.y + area.size.h - rect.height);
                }
                serde_json::json!({"kind":"float","output_id":scene.surface_outputs.get(current).map(String::as_str).unwrap_or("nested-primary"),"x":rect.x,"y":rect.y,"width":rect.width,"height":rect.height})
            }
            _ => return,
        };
        bridge.input(current, edit);
    }
    pub fn preview_geometry(&self, id: &str, mut rect: crate::policy::Rect) {
        if let Some(output) = self.view_area(id) {
            rect.width = rect.width.max(80).min(output.size.w);
            rect.height = rect.height.max(32).min(output.size.h);
            rect.x = rect
                .x
                .clamp(output.loc.x, output.loc.x + output.size.w - rect.width);
            rect.y = rect
                .y
                .clamp(output.loc.y, output.loc.y + output.size.h - rect.height);
        }
        if let Some(bridge) = &self.bridge {
            bridge.preview_grab(id, rect)
        }
    }
    pub fn arrange(&mut self) {
        let windows = self.space.elements().cloned().collect::<Vec<_>>();
        let ids = windows
            .iter()
            .map(|w| format!("{:?}", w.toplevel().unwrap().wl_surface().id()))
            .collect::<Vec<_>>();
        self.policy.synchronize(&ids);
        let mut observed_outputs: Vec<crate::bridge::OutputObservation> = self.space.outputs().filter_map(|output| {
            let geometry = self.space.output_geometry(output)?;
            Some(crate::bridge::OutputObservation {
                id: if output.name()=="winit" {"nested-primary".into()} else {format!("drm-{}",output.name())},
                area: crate::policy::Rect {x:geometry.loc.x,y:geometry.loc.y,width:geometry.size.w,height:geometry.size.h},
                metadata: serde_json::json!({"scale":output.current_scale().fractional_scale(),"transform":format!("{:?}",output.current_transform())}),
            })
        }).collect();
        observed_outputs.sort_by(|a, b| a.area.x.cmp(&b.area.x).then_with(|| a.id.cmp(&b.id)));
        if let Some(bridge) = &self.bridge {
            // new_toplevel is inserted into Space before the client attaches
            // content so we can send its initial configure. Do not publish that
            // protocol setup (or a later null-buffer unmap) as visible work.
            let mapped = windows.iter().filter(|window| {
                smithay::backend::renderer::utils::with_renderer_surface_state(
                    window.toplevel().unwrap().wl_surface(),
                    |state| state.buffer().is_some(),
                ).unwrap_or(false)
            });
            bridge.observe(mapped.map(observe).collect(), observed_outputs);
        }
        let Some(output) = self.space.outputs().next() else {
            return;
        };
        let Some(area) = self.space.output_geometry(output) else {
            return;
        };
        let area = crate::policy::Rect {
            x: area.loc.x,
            y: area.loc.y,
            width: area.size.w,
            height: area.size.h,
        };
        let mut placements = self.policy.arrange(area);
        let mut maximized = std::collections::BTreeSet::new();
        if let Some(bridge) = &self.bridge {
            let scene = bridge.scene.lock().unwrap().clone();
            for id in scene
                .identities
                .keys()
                .filter(|id| !scene.rectangles.contains_key(*id))
            {
                // Preserve the live application and its placement while its activity is set aside.
                placements.insert(
                    id.clone(),
                    crate::policy::Rect {
                        x: -100000,
                        y: -100000,
                        width: windows
                            .iter()
                            .zip(&ids)
                            .find(|(_, window_id)| *window_id == id)
                            .map(|(w, _)| w.geometry().size.w.max(80))
                            .unwrap_or(80),
                        height: windows
                            .iter()
                            .zip(&ids)
                            .find(|(_, window_id)| *window_id == id)
                            .map(|(w, _)| w.geometry().size.h.max(32))
                            .unwrap_or(32),
                    },
                );
            }
            maximized = scene.maximized;
            placements.extend(scene.rectangles);
            for (id, preview) in bridge
                .previews
                .lock()
                .unwrap()
                .iter()
                .filter(|(_, p)| p.active)
            {
                placements.insert(id.clone(), preview.rect);
                maximized.remove(id);
            }
            if scene.focus != self.applied_focus {
                if let Some(window) = windows.iter().find(|w| {
                    Some(format!("{:?}", w.toplevel().unwrap().wl_surface().id())) == scene.focus
                }) {
                    self.applied_focus = scene.focus.clone();
                    self.space.raise_element(window, true);
                    if let Some(keyboard) = self.seat.get_keyboard() {
                        keyboard.set_focus(
                            self,
                            Some(window.toplevel().unwrap().wl_surface().clone()),
                            smithay::utils::SERIAL_COUNTER.next_serial(),
                        );
                    }
                } else if scene.focus.is_none() {
                    if let Some(keyboard) = self.seat.get_keyboard() {
                        keyboard.set_focus(
                            self,
                            None,
                            smithay::utils::SERIAL_COUNTER.next_serial(),
                        );
                    }
                    self.applied_focus = None;
                }
                // A shared surface can be selected before its Wayland window
                // maps. Retain the pending focus until the seat actually gets
                // that window; otherwise later mapping never sends keyboard enter.
            } else if let Some(keyboard) = self.seat.get_keyboard() {
                let popup_grab = keyboard
                    .with_grab(|_, grab| grab.is::<smithay::desktop::PopupKeyboardGrab<Smallvil>>())
                    .unwrap_or(false);
                if popup_grab {
                    // The popup grab rejects this while active, and restores
                    // the authoritative root once ended. Do not leave focus
                    // on a closed popup until another key happens to arrive.
                    let focus = windows
                        .iter()
                        .find(|w| {
                            Some(format!("{:?}", w.toplevel().unwrap().wl_surface().id()))
                                == scene.focus
                        })
                        .map(|w| w.toplevel().unwrap().wl_surface().clone());
                    keyboard.set_focus(self, focus, smithay::utils::SERIAL_COUNTER.next_serial());
                }
            }
        }
        self.viewport_offsets.retain(|id, _| ids.contains(id));
        for (id, rect) in &mut placements {
            let viewport_area = self
                .view_area(id)
                .map(|r| crate::policy::Rect {
                    x: r.loc.x,
                    y: r.loc.y,
                    width: r.size.w,
                    height: r.size.h,
                })
                .unwrap_or(area);
            if let Some(offset) = self.viewport_offsets.get_mut(id) {
                *rect = crate::pressure::viewport(*rect, viewport_area, offset);
            }
        }
        for (id, window) in ids.iter().zip(windows) {
            if let Some(rect) = placements.get(id) {
                let top = window.toplevel().unwrap();
                let target = (rect.width, rect.height).into();
                let changed = top.with_pending_state(|pending| {
                    use smithay::reexports::wayland_protocols::xdg::shell::server::xdg_toplevel;
                    let was_maximized = pending.states.contains(xdg_toplevel::State::Maximized);
                    let now_maximized = if self.bridge.is_some() {
                        maximized.contains(id)
                    } else {
                        matches!(
                            self.policy.current.placements.get(id),
                            Some(crate::policy::Placement::Maximized)
                        )
                    };
                    if now_maximized {
                        pending.states.set(xdg_toplevel::State::Maximized);
                    } else {
                        pending.states.unset(xdg_toplevel::State::Maximized);
                    }
                    if pending.size != Some(target) || was_maximized != now_maximized {
                        pending.size = Some(target);
                        true
                    } else {
                        false
                    }
                });
                if changed {
                    top.send_pending_configure();
                }
                self.space.map_element(window, (rect.x, rect.y), false);
            }
        }
    }

    pub fn surface_under(
        &self,
        pos: Point<f64, Logical>,
    ) -> Option<(WlSurface, Point<f64, Logical>)> {
        self.space
            .element_under(pos)
            .and_then(|(window, location)| {
                window
                    .surface_under(pos - location.to_f64(), WindowSurfaceType::ALL)
                    .map(|(s, p)| (s, (p + location).to_f64()))
            })
    }
}

#[derive(Default)]
pub struct ClientState {
    pub compositor_state: CompositorClientState,
    pub peer: Option<(u32, String)>,
    // Only a compositor-created private socket can receive this capability.
    pub input_method: bool,
}

impl ClientData for ClientState {
    fn initialized(&self, _client_id: ClientId) {}
    fn disconnected(&self, _client_id: ClientId, _reason: DisconnectReason) {}
}

pub fn observe(window: &Window) -> crate::bridge::Observed {
    let surface = window.toplevel().unwrap().wl_surface();
    let (title, app_id) = smithay::wayland::compositor::with_states(surface, |states| {
        let data = states
            .data_map
            .get::<smithay::wayland::shell::xdg::XdgToplevelSurfaceData>()
            .unwrap()
            .lock()
            .unwrap();
        (
            data.title.clone().unwrap_or_default(),
            data.app_id.clone().unwrap_or_default(),
        )
    });
    let minimum = smithay::wayland::compositor::with_states(surface, |states| {
        states
            .cached_state
            .get::<smithay::wayland::shell::xdg::SurfaceCachedState>()
            .current()
            .min_size
    });
    let peer = surface.client().and_then(|client| {
        client
            .get_data::<ClientState>()
            .and_then(|d| d.peer.clone())
    });
    let (uid, session) = peer.unwrap_or((u32::MAX, String::new()));
    crate::bridge::Observed {
        id: format!("{:?}", surface.id()),
        title,
        app_id,
        uid,
        session,
        min_width: minimum.w.max(80),
        min_height: minimum.h.max(32),
    }
}
fn peer_identity(stream: &std::os::unix::net::UnixStream) -> Option<(u32, String)> {
    use std::os::fd::AsRawFd;
    let mut credential = std::mem::MaybeUninit::<libc::ucred>::uninit();
    let mut size = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    if unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            credential.as_mut_ptr().cast(),
            &mut size,
        )
    } != 0
    {
        return None;
    }
    if size as usize != std::mem::size_of::<libc::ucred>() {
        return None;
    }
    let credential = unsafe { credential.assume_init() };
    let stat = std::fs::read_to_string(format!("/proc/{}/stat", credential.pid)).ok()?;
    let start = stat.rsplit_once(')')?.1.split_whitespace().nth(19)?;
    Some((credential.uid, format!("{}:{start}", credential.pid)))
}

smithay::delegate_presentation!(Smallvil);
