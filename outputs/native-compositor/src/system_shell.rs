//! Host-selected shell capability; never inferred from client titles or app IDs.
//! Layer placement uses Smithay's MIT-licensed layer map (see LICENSE-SMITHAY).
use crate::{process, state::ClientState, Smallvil};
use smithay::reexports::wayland_server::Resource;
use smithay::{
    desktop::{layer_map_for_output, LayerSurface, WindowSurfaceType},
    output::Output,
    reexports::wayland_server::protocol::{wl_output::WlOutput, wl_surface::WlSurface},
    wayland::{
        compositor::with_states,
        shell::wlr_layer::{
            Layer, LayerSurface as ProtocolLayer, LayerSurfaceData, WlrLayerShellHandler,
            WlrLayerShellState,
        },
    },
};
use std::{
    os::{
        fd::AsRawFd,
        unix::{net::UnixStream, process::CommandExt},
    },
    sync::{Arc, Mutex},
};

/// Authenticate the exact host-selected renderer, including process start time.
pub fn trusted_renderer(state: &Smallvil, peer: Option<u32>) -> Result<(), String> {
    let (pid, start) = state
        .shell_identity
        .as_ref()
        .ok_or("Trusted renderer unavailable")?;
    if peer != Some(*pid) {
        return Err("Trusted renderer required".into());
    }
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))
        .map_err(|_| "Trusted renderer exited")?;
    if stat
        .rsplit_once(')')
        .and_then(|(_, tail)| tail.split_whitespace().next())
        .is_some_and(|state| matches!(state, "Z" | "X"))
    {
        return Err("Trusted renderer exited".into());
    }
    if stat
        .rsplit_once(')')
        .and_then(|(_, tail)| tail.split_whitespace().nth(19))
        != Some(start.as_str())
    {
        return Err("Trusted renderer identity changed".into());
    }
    Ok(())
}

pub fn spawn(
    state: &mut Smallvil,
    command: &mut std::process::Command,
    owned: &Arc<Mutex<Option<std::process::Child>>>,
) -> Result<(), Box<dyn std::error::Error>> {
    let (server, socket) = UnixStream::pair()?;
    let fd = socket.as_raw_fd();
    command
        .env("WAYLAND_SOCKET", fd.to_string())
        .env("AGENT_OS_TRUSTED_SHELL", "1");
    let prior = std::env::var("LD_PRELOAD").unwrap_or_default();
    command.env("LD_PRELOAD", format!("libgtk4-layer-shell.so.0 {prior}"));
    process::configure_child(command);
    unsafe {
        command.pre_exec(move || {
            if libc::fcntl(fd, libc::F_SETFD, 0) == -1 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    let child = command.spawn()?;
    let pid = child.id();
    *owned.lock().unwrap() = Some(child);
    // SO_PEERCRED on a socketpair identifies its creator. The selected child is
    // the actual renderer; retain its start time for existing core identity checks.
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    let start = stat
        .rsplit_once(')')
        .and_then(|(_, tail)| tail.split_whitespace().nth(19))
        .ok_or("Renderer start identity unavailable")?;
    state.shell_identity = Some((pid, start.to_owned()));
    state.display_handle.insert_client(
        server,
        Arc::new(ClientState {
            peer: Some((unsafe { libc::geteuid() }, format!("{pid}:{start}"))),
            system_shell: true,
            ..ClientState::default()
        }),
    )?;
    Ok(())
}
impl WlrLayerShellHandler for Smallvil {
    fn shell_state(&mut self) -> &mut WlrLayerShellState {
        &mut self.system_shell_state
    }
    fn new_layer_surface(
        &mut self,
        surface: ProtocolLayer,
        requested: Option<WlOutput>,
        layer: Layer,
        namespace: String,
    ) {
        if !matches!(
            (namespace.as_str(), layer),
            ("agentos-system-bar", Layer::Top) | ("agentos-launcher", Layer::Overlay) | ("agentos-keyboard", Layer::Overlay)
        ) {
            surface.send_close();
            return;
        }
        remember_role(&surface, layer);
        let output = requested
            .as_ref()
            .and_then(Output::from_resource)
            .filter(|output| self.space.outputs().any(|known| known == output))
            .or_else(|| self.space.outputs().next().cloned());
        let Some(output) = output else {
            surface.send_close();
            return;
        };
        let mut map = layer_map_for_output(&output);
        if map.layers().any(|known| known.namespace() == namespace) {
            surface.send_close();
            return;
        }
        if map
            .map_layer(&LayerSurface::new(surface.clone(), namespace))
            .is_err()
        {
            surface.send_close();
        }
    }
    fn new_popup(
        &mut self,
        _parent: ProtocolLayer,
        popup: smithay::wayland::shell::xdg::PopupSurface,
    ) {
        self.unconstrain_popup(&popup);
        let _ = self
            .popups
            .track_popup(smithay::desktop::PopupKind::Xdg(popup));
    }
    fn layer_destroyed(&mut self, surface: ProtocolLayer) {
        release_launcher(self, surface.wl_surface());
        for output in self.space.outputs() {
            let mut map = layer_map_for_output(output);
            let layer = map
                .layers()
                .find(|layer| layer.layer_surface() == &surface)
                .cloned();
            if let Some(layer) = layer {
                map.unmap_layer(&layer);
                break;
            }
        }
    }
}
pub fn committed(state: &mut Smallvil, surface: &WlSurface) {
    let mut launcher = false;
    for output in state.space.outputs() {
        let mut map = layer_map_for_output(output);
        let Some(layer) = map
            .layer_for_surface(surface, WindowSurfaceType::TOPLEVEL)
            .cloned()
        else {
            continue;
        };
        launcher = layer.namespace() == "agentos-launcher";
        map.arrange();
        let initial = with_states(surface, |states| {
            states
                .data_map
                .get::<LayerSurfaceData>()
                .unwrap()
                .lock()
                .unwrap()
                .initial_configure_sent
        });
        if !initial {
            layer.layer_surface().send_configure();
        } else {
            layer.layer_surface().send_pending_configure();
        }
        break;
    }
    if launcher {
        let mapped =
            smithay::backend::renderer::utils::with_renderer_surface_state(surface, |state| {
                state.buffer().is_some()
            })
            .unwrap_or(false);
        if mapped && state.active_launcher.as_ref() != Some(surface) {
            state.active_launcher = Some(surface.clone());
            if let Some(keyboard) = state.seat.get_keyboard() {
                keyboard.set_focus(
                    state,
                    Some(surface.clone()),
                    smithay::utils::SERIAL_COUNTER.next_serial(),
                );
            }
        } else if !mapped {
            release_launcher(state, surface);
        }
    }
}
fn release_launcher(state: &mut Smallvil, surface: &WlSurface) {
    if state.active_launcher.as_ref() == Some(surface) {
        state.active_launcher = None;
        state.applied_focus = None;
        if let Some(keyboard) = state.seat.get_keyboard() {
            keyboard.set_focus(state, None, smithay::utils::SERIAL_COUNTER.next_serial());
        }
    }
}
smithay::delegate_layer_shell!(Smallvil);

/// Match the actual keyboard layer's output, including after a remap. Before
/// its first map, use the same fallback output as new_layer_surface.
pub fn keyboard_output_height(state: &Smallvil) -> Option<i32> {
    let output = state.space.outputs().find(|output| {
        layer_map_for_output(output).layers().any(|layer| layer.namespace() == "agentos-keyboard")
    }).or_else(|| state.space.outputs().next())?;
    state.space.output_geometry(output).map(|geometry| geometry.size.h)
}

/// Output-local reservation translated into the compositor's global coordinates.
pub fn work_area(
    state: &Smallvil,
    output: &Output,
) -> Option<smithay::utils::Rectangle<i32, smithay::utils::Logical>> {
    let geometry = state.space.output_geometry(output)?;
    let mut map = layer_map_for_output(output);
    map.arrange();
    let mut area = map.non_exclusive_zone();
    area.loc += geometry.loc;
    Some(area)
}

pub fn surface_under(
    state: &Smallvil,
    pos: smithay::utils::Point<f64, smithay::utils::Logical>,
) -> Option<(
    WlSurface,
    smithay::utils::Point<f64, smithay::utils::Logical>,
)> {
    for output in state.space.outputs() {
        let geometry = state.space.output_geometry(output)?;
        if !geometry.to_f64().contains(pos) {
            continue;
        }
        let map = layer_map_for_output(output);
        for level in [Layer::Overlay, Layer::Top] {
            let Some(layer) = map.layer_under(level, pos - geometry.loc.to_f64()) else {
                continue;
            };
            let origin = geometry.loc + map.layer_geometry(layer)?.loc;
            if let Some((surface, offset)) =
                layer.surface_under(pos - origin.to_f64(), WindowSurfaceType::ALL)
            {
                return Some((surface, (origin + offset).to_f64()));
            }
        }
    }
    None
}

pub fn send_frames(state: &Smallvil, output: &Output) {
    for layer in layer_map_for_output(output).layers() {
        layer.send_frame(
            output,
            state.start_time.elapsed(),
            Some(std::time::Duration::ZERO),
            |_, _| Some(output.clone()),
        );
    }
}

pub fn snapshot(state: &Smallvil) -> serde_json::Value {
    serde_json::Value::Array(state.space.outputs().flat_map(|output| {
        let work = work_area(state, output);
        let map = layer_map_for_output(output);
        map.layers().map(|layer| {
            serde_json::json!({"id":format!("{:?}",layer.wl_surface().id()),"mapped":smithay::backend::renderer::utils::with_renderer_surface_state(layer.wl_surface(), |state|state.buffer().is_some()).unwrap_or(false),"output":output.name(),"namespace":layer.namespace(),"geometry":map.layer_geometry(layer).map(|r|serde_json::json!({"x":r.loc.x,"y":r.loc.y,"width":r.size.w,"height":r.size.h})),"work_area":work.map(|r|serde_json::json!({"x":r.loc.x,"y":r.loc.y,"width":r.size.w,"height":r.size.h}))})
        }).collect::<Vec<_>>()
    }).collect())
}

/// Smithay 0.6 leaves its layer-size validation hook installed after role
/// destruction, then resets size/anchors to zero. GTK legally destroys the role
/// before committing a null buffer on hide. Neutralize only the dead role's
/// cached size before that old hook runs; a new role gets fresh defaults below.
/// This hook must be registered at wl_surface creation, before the role hook.
pub fn prepare_surface(surface: &WlSurface) {
    type Role = Mutex<Option<smithay::reexports::wayland_server::Weak<smithay::reexports::wayland_protocols_wlr::layer_shell::v1::server::zwlr_layer_surface_v1::ZwlrLayerSurfaceV1>>>;
    smithay::wayland::compositor::add_pre_commit_hook::<Smallvil, _>(surface, |_, _, surface| {
        with_states(surface, |states| {
            let Some(role) = states.data_map.get::<Role>() else {
                return;
            };
            let role = role.lock().unwrap();
            if role.as_ref().is_some_and(|role| role.upgrade().is_err()) {
                states
                    .cached_state
                    .get::<smithay::wayland::shell::wlr_layer::LayerSurfaceCachedState>()
                    .pending()
                    .size = (1, 1).into();
            }
        });
    });
}
fn remember_role(surface: &ProtocolLayer, layer: Layer) {
    type Role = Mutex<Option<smithay::reexports::wayland_server::Weak<smithay::reexports::wayland_protocols_wlr::layer_shell::v1::server::zwlr_layer_surface_v1::ZwlrLayerSurfaceV1>>>;
    with_states(surface.wl_surface(), |states| {
        states
            .data_map
            .insert_if_missing_threadsafe(|| Role::new(None));
        *states.data_map.get::<Role>().unwrap().lock().unwrap() =
            Some(surface.shell_surface().downgrade());
        // Restore protocol defaults if this wl_surface previously had a dead
        // layer role. Client requests arrive after this role creation callback.
        let mut cached = states
            .cached_state
            .get::<smithay::wayland::shell::wlr_layer::LayerSurfaceCachedState>();
        *cached.pending() = Default::default();
        cached.pending().layer = layer;
    });
}

pub fn root_geometry(
    state: &Smallvil,
    surface: &WlSurface,
) -> Option<(
    smithay::utils::Rectangle<i32, smithay::utils::Logical>,
    smithay::utils::Point<i32, smithay::utils::Logical>,
)> {
    for output in state.space.outputs() {
        let map = layer_map_for_output(output);
        if let Some(layer) = map.layer_for_surface(surface, WindowSurfaceType::TOPLEVEL) {
            let output_geometry = state.space.output_geometry(output)?;
            let origin = output_geometry.loc + map.layer_geometry(layer)?.loc;
            return Some((output_geometry, origin));
        }
    }
    None
}

pub fn close_launcher(state: &Smallvil) {
    let Some(active) = &state.active_launcher else {
        return;
    };
    for output in state.space.outputs() {
        let map = layer_map_for_output(output);
        if let Some(layer) = map.layer_for_surface(active, WindowSurfaceType::TOPLEVEL) {
            layer.layer_surface().send_close();
            return;
        }
    }
}

fn has_namespace(state: &Smallvil, surface: &WlSurface, namespace: &str) -> bool {
    state.space.outputs().any(|output| layer_map_for_output(output).layers().any(|layer| layer.namespace() == namespace && layer.wl_surface() == surface))
}
pub fn is_keyboard(state: &Smallvil, surface: &WlSurface) -> bool {has_namespace(state, surface, "agentos-keyboard")}
pub fn is_bar(state: &Smallvil, surface: &WlSurface) -> bool {has_namespace(state, surface, "agentos-system-bar")}
